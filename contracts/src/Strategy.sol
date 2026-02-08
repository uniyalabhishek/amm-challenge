// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy, TradeInfo} from "./IAMMStrategy.sol";

/// @title Adaptive Skew Strategy
/// @notice Dynamic fee strategy that skews fees around an estimated fair price.
contract Strategy is AMMStrategyBase {
    uint256 private constant LOW_FEE = 20 * BPS; // 20 bps
    uint256 private constant BASE_FEE = 30 * BPS; // 30 bps
    uint256 private constant HIGH_FEE = 120 * BPS; // 120 bps
    uint256 private constant MAX_FEE_CAP = 150 * BPS; // hard cap for returned fees

    uint256 private constant DEAD_BAND = 5 * BPS; // 5 bps

    // EMA weights in WAD
    uint256 private constant ALPHA_NEW_STEP = 7e17; // 0.7
    uint256 private constant ALPHA_SAME_STEP = 0; // 0.0

    function afterInitialize(uint256 initialX, uint256 initialY)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[2] = spot; // anchor price
        slots[4] = type(uint256).max; // last timestamp sentinel
        slots[0] = HIGH_FEE; // last bid fee
        slots[1] = HIGH_FEE; // last ask fee
        return (HIGH_FEE, HIGH_FEE);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 bidPrev = slots[0];
        uint256 askPrev = slots[1];
        uint256 anchor = slots[2];
        uint256 lastTimestamp = slots[4];

        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        if (anchor == 0) {
            anchor = spot;
        }

        bool isNewStep = trade.timestamp != lastTimestamp;

        uint256 appliedFee = trade.isBuy ? bidPrev : askPrev;
        uint256 gamma = appliedFee >= WAD ? 0 : (WAD - appliedFee);
        uint256 target = spot;
        if (gamma > 0) {
            target = trade.isBuy ? wmul(gamma, spot) : wdiv(spot, gamma);
        }

        uint256 alpha = isNewStep ? ALPHA_NEW_STEP : ALPHA_SAME_STEP;
        anchor = _ema(anchor, target, alpha);
        slots[2] = anchor;

        uint256 deviation = anchor > 0 ? absDiff(spot, anchor) : 0;
        uint256 deviationPct = anchor > 0 ? wdiv(deviation, anchor) : 0;

        uint256 baseFee = isNewStep ? LOW_FEE : BASE_FEE;

        if (deviationPct <= DEAD_BAND) {
            bidFee = baseFee;
            askFee = baseFee;
        } else if (spot >= anchor) {
            // Overpriced: favor selling X (lower ask), block buying X (higher bid).
            askFee = baseFee;
            bidFee = HIGH_FEE;
        } else {
            // Underpriced: favor buying X (lower bid), block selling X (higher ask).
            bidFee = baseFee;
            askFee = HIGH_FEE;
        }

        if (bidFee > MAX_FEE_CAP) {
            bidFee = MAX_FEE_CAP;
        }
        if (askFee > MAX_FEE_CAP) {
            askFee = MAX_FEE_CAP;
        }

        bidFee = clampFee(bidFee);
        askFee = clampFee(askFee);

        slots[0] = bidFee;
        slots[1] = askFee;
        slots[4] = trade.timestamp;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "AdaptiveSkewStrategy_v1";
    }

    function _ema(uint256 previous, uint256 value, uint256 alphaWad)
        internal
        pure
        returns (uint256)
    {
        if (previous == 0) {
            return value;
        }
        if (value >= previous) {
            return previous + wmul(alphaWad, value - previous);
        }
        return previous - wmul(alphaWad, previous - value);
    }

}
