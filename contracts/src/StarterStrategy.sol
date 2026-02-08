// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy, TradeInfo} from "./IAMMStrategy.sol";

/// @title Adaptive Volatility + Skew Strategy
/// @notice Balances retail capture with volatility-aware spread control.
contract Strategy is AMMStrategyBase {
    // --- Tunables (basis points unless noted) ---
    uint256 private constant BASE_FEE_BPS = 8;
    uint256 private constant MIN_FEE_BPS = 2;
    uint256 private constant MAX_RETAIL_FEE_BPS = 75;
    uint256 private constant MAX_ARB_FEE_BPS = 130;
    uint256 private constant RETAIL_DISCOUNT_BPS = 5;
    uint256 private constant ARB_PREMIUM_BPS = 25;
    uint256 private constant RETAIL_TRADE_LIMIT = 2;

    // EMA parameters
    uint256 private constant VOL_DECAY = 12; // EMA window size
    uint256 private constant PRICE_ALPHA = 1e17; // 0.10 in WAD
    uint256 private constant VOL_MULTIPLIER = 3e18; // 3.0x in WAD

    // Skew control
    uint256 private constant SKEW_COEF = 9e17; // 0.9 in WAD
    uint256 private constant MAX_SKEW_BPS = 35;

    // --- Slot layout ---
    // slot[0] = last timestamp
    // slot[1] = price EMA (WAD)
    // slot[2] = volatility EMA (WAD)
    // slot[3] = last spot price (WAD)
    // slot[4] = last bid fee (WAD)
    // slot[5] = last ask fee (WAD)
    // slot[6] = retail trades seen in step

    function afterInitialize(uint256 initialX, uint256 initialY)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 spot = wdiv(initialY, initialX);
        slots[0] = 0;
        slots[1] = spot;
        slots[2] = 0;
        slots[3] = spot;
        bidFee = bpsToWad(BASE_FEE_BPS);
        askFee = bidFee;
        slots[4] = bidFee;
        slots[5] = askFee;
        slots[6] = 0;
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 lastTimestamp = slots[0];
        uint256 priceEma = slots[1];
        uint256 volEma = slots[2];
        uint256 lastSpot = slots[3];
        uint256 retailCount = slots[6];

        uint256 spot = wdiv(trade.reserveY, trade.reserveX);

        // Track step boundaries to bias fees toward retail early in the step.
        if (trade.timestamp > lastTimestamp) {
            retailCount = 0;
            lastTimestamp = trade.timestamp;
        } else {
            retailCount += 1;
        }

        // Update volatility EMA from spot-to-spot moves.
        if (lastSpot > 0) {
            uint256 absReturn = wdiv(absDiff(spot, lastSpot), lastSpot);
            volEma = (volEma * (VOL_DECAY - 1) + absReturn) / VOL_DECAY;
        }

        // Compute base fee from volatility.
        uint256 minFee = bpsToWad(MIN_FEE_BPS);
        uint256 maxRetailFee = bpsToWad(MAX_RETAIL_FEE_BPS);
        uint256 maxArbFee = bpsToWad(MAX_ARB_FEE_BPS);

        uint256 baseFee = bpsToWad(BASE_FEE_BPS) + wmul(volEma, VOL_MULTIPLIER);
        if (baseFee < minFee) baseFee = minFee;
        if (baseFee > maxArbFee) baseFee = maxArbFee;

        uint256 retailFee = baseFee;
        uint256 discount = bpsToWad(RETAIL_DISCOUNT_BPS);
        if (retailFee > discount) {
            retailFee -= discount;
        } else {
            retailFee = minFee;
        }
        if (retailFee > maxRetailFee) retailFee = maxRetailFee;

        uint256 arbFee = baseFee + bpsToWad(ARB_PREMIUM_BPS);
        if (arbFee > maxArbFee) arbFee = maxArbFee;

        uint256 midFee = retailCount < RETAIL_TRADE_LIMIT ? retailFee : arbFee;

        // Skew adjustment versus EMA price anchor.
        uint256 skewAdj = 0;
        if (priceEma > 0) {
            uint256 skewRatio = wdiv(absDiff(spot, priceEma), priceEma);
            skewAdj = wmul(skewRatio, SKEW_COEF);
            uint256 maxSkew = bpsToWad(MAX_SKEW_BPS);
            if (skewAdj > maxSkew) skewAdj = maxSkew;
        }

        if (spot > priceEma) {
            // Spot above EMA: discourage buys (AMM buys X), encourage sells.
            bidFee = clampFee(midFee + skewAdj);
            askFee = midFee > skewAdj ? midFee - skewAdj : minFee;
        } else if (spot < priceEma) {
            // Spot below EMA: encourage buys (AMM buys X), discourage sells.
            bidFee = midFee > skewAdj ? midFee - skewAdj : minFee;
            askFee = clampFee(midFee + skewAdj);
        } else {
            bidFee = midFee;
            askFee = midFee;
        }

        // Update price EMA after using the old anchor.
        if (priceEma == 0) {
            priceEma = spot;
        } else if (spot >= priceEma) {
            priceEma += wmul(spot - priceEma, PRICE_ALPHA);
        } else {
            priceEma -= wmul(priceEma - spot, PRICE_ALPHA);
        }

        // Persist state for next trade.
        slots[0] = lastTimestamp;
        slots[1] = priceEma;
        slots[2] = volEma;
        slots[3] = spot;
        slots[4] = bidFee;
        slots[5] = askFee;
        slots[6] = retailCount;
    }

    function getName() external pure override returns (string memory) {
        return "AdaptiveVolSkew_v2";
    }
}
