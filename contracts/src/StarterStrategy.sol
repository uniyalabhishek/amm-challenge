// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy, TradeInfo} from "./IAMMStrategy.sol";

/// @title First-Principles Dynamic Skew Strategy
/// @notice Tracks an internal fair anchor and skews bid/ask with spot deviation.
contract Strategy is AMMStrategyBase {
    // Core fee shape: low base to win routing, large cap to defend stale states.
    uint256 public constant BASE = 31 * BPS;
    uint256 public constant FLOOR = 3 * BPS;
    uint256 public constant CAP = 969 * BPS;

    // Fair-price anchor update speeds.
    uint256 public constant STEP_W = 154_508_021_063_245_728; // ~0.1545
    uint256 public constant INTRA_W = 18_485_180_910_640_472; // ~0.0185

    // Deviation -> fee skew mapping.
    uint256 public constant SLOPE = 770_054_042_076_264_320; // ~0.7701
    uint256 public constant AGGR = 764_559_939_161_155_584; // ~0.7646

    function _blend(uint256 a, uint256 b, uint256 w) internal pure returns (uint256) {
        if (w == 0) return a;
        if (w >= WAD) return b;
        return (a * (WAD - w) + b * w) / WAD;
    }

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        slots[0] = wdiv(initialY, initialX); // fair anchor
        slots[1] = type(uint256).max; // last timestamp sentinel
        slots[2] = BASE; // previous bid fee
        slots[3] = BASE; // previous ask fee
        return (BASE, BASE);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = wdiv(trade.reserveY, trade.reserveX);
        uint256 fair = slots[0];
        if (fair == 0) fair = spot;

        bool newStep = trade.timestamp != slots[1];
        slots[1] = trade.timestamp;

        uint256 prevBid = slots[2];
        uint256 prevAsk = slots[3];

        if (newStep) {
            // First trade each step is often arb; use that to re-anchor fair.
            uint256 gamma = WAD - (trade.isBuy ? prevBid : prevAsk);
            if (gamma < WAD / 2) gamma = WAD / 2;
            uint256 inferredFair = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            fair = _blend(fair, inferredFair, STEP_W);
        } else if (INTRA_W > 0) {
            fair = _blend(fair, spot, INTRA_W);
        }
        slots[0] = fair;

        uint256 ratio = spot >= fair ? wdiv(spot, fair) : wdiv(fair, spot);
        uint256 deviation = ratio > WAD ? ratio - WAD : 0;

        uint256 extra = wmul(deviation, SLOPE);
        if (extra > CAP) extra = CAP;

        uint256 hi = clampFee(BASE + extra);
        uint256 cut = wmul(extra, AGGR);
        uint256 lo = BASE > cut ? BASE - cut : FLOOR;
        if (lo < FLOOR) lo = FLOOR;
        lo = clampFee(lo);

        if (spot > fair) {
            bidFee = hi;
            askFee = lo;
        } else if (spot < fair) {
            bidFee = lo;
            askFee = hi;
        } else {
            bidFee = BASE;
            askFee = BASE;
        }

        slots[2] = bidFee;
        slots[3] = askFee;
        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "FirstPrinciples_LinearSkew_v1";
    }
}
