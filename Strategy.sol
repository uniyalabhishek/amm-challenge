// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./contracts/src/AMMStrategyBase.sol";
import {IAMMStrategy, TradeInfo} from "./contracts/src/IAMMStrategy.sol";

/// @title Adaptive Skew Strategy
/// @notice Dynamic fee strategy that skews fees around an estimated fair price.
contract Strategy is AMMStrategyBase {
    uint256 private constant BASE_FEE = 10 * BPS; // 10 bps
    uint256 private constant MAX_BASE_FEE = 45 * BPS; // soft cap for base fee
    uint256 private constant MAX_FEE_CAP = 80 * BPS; // hard cap for returned fees

    uint256 private constant LOW_STEP_ADJ = 3 * BPS;
    uint256 private constant HIGH_STEP_ADJ = 6 * BPS;

    uint256 private constant MAX_RISK = 20 * BPS;
    uint256 private constant MAX_SKEW = 25 * BPS;

    // Scale factors in WAD (1e18)
    uint256 private constant RISK_SCALE = 6e17; // 0.6
    uint256 private constant SKEW_SCALE = 12e17; // 1.2

    // EMA weights in WAD
    uint256 private constant ALPHA_NEW_STEP = 25e16; // 0.25
    uint256 private constant ALPHA_SAME_STEP = 5e16; // 0.05

    function afterInitialize(uint256 initialX, uint256 initialY)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[2] = spot; // anchor price
        slots[4] = 0; // last timestamp
        slots[0] = BASE_FEE; // last bid fee
        slots[1] = BASE_FEE; // last ask fee
        return (BASE_FEE, BASE_FEE);
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

        bool isNewStep = trade.timestamp > lastTimestamp;

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

        uint256 baseFee = BASE_FEE;
        if (isNewStep) {
            baseFee = baseFee > LOW_STEP_ADJ ? baseFee - LOW_STEP_ADJ : 0;
        } else {
            baseFee += HIGH_STEP_ADJ;
        }

        uint256 riskAdd = wmul(deviationPct, RISK_SCALE);
        if (riskAdd > MAX_RISK) {
            riskAdd = MAX_RISK;
        }
        baseFee += riskAdd;
        if (baseFee > MAX_BASE_FEE) {
            baseFee = MAX_BASE_FEE;
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
