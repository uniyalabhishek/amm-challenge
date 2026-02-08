// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy, TradeInfo} from "./IAMMStrategy.sol";

/// @title Adaptive Skew Strategy
/// @notice Dynamic fee strategy that skews fees around an estimated fair price.
contract Strategy is AMMStrategyBase {
    uint256 private constant LOW_FEE = 3 * BPS; // 3 bps
    uint256 private constant HIGH_FEE = 45 * BPS; // 45 bps
    uint256 private constant MAX_FEE_CAP = 120 * BPS; // hard cap for returned fees

    uint256 private constant MAX_RISK = 15 * BPS;
    uint256 private constant MAX_SKEW = 40 * BPS;

    // Scale factors in WAD (1e18)
    uint256 private constant RISK_SCALE = 5e17; // 0.5
    uint256 private constant SKEW_SCALE = 25e17; // 2.5

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

        uint256 baseFee = isNewStep ? LOW_FEE : HIGH_FEE;
        uint256 riskAdd = wmul(deviationPct, RISK_SCALE);
        if (riskAdd > MAX_RISK) {
            riskAdd = MAX_RISK;
        }
        baseFee += riskAdd;
        if (baseFee > MAX_FEE_CAP) {
            baseFee = MAX_FEE_CAP;
        }

        uint256 skew = wmul(deviationPct, SKEW_SCALE);
        if (skew > MAX_SKEW) {
            skew = MAX_SKEW;
        }

        if (spot >= anchor) {
            // Overpriced: favor selling X (lower ask), penalize buying X (higher bid).
            askFee = baseFee > skew ? baseFee - skew : 0;
            bidFee = baseFee + skew;
        } else {
            // Underpriced: favor buying X (lower bid), penalize selling X (higher ask).
            bidFee = baseFee > skew ? baseFee - skew : 0;
            askFee = baseFee + skew;
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
