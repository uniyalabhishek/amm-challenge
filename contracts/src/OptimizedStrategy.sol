// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Optimized Dynamic Fee Strategy
/// @notice Uses a filtered fair-price proxy and directional spread widening.
/// @dev This keeps a low-mid fee most of the time and widens one side when
///      observed reserve-implied price deviates from the filtered fair proxy.
contract Strategy is AMMStrategyBase {
    // Directional fee regime (in bps)
    uint256 internal constant HIGH = 120 * BPS;
    uint256 internal constant LOW = 20 * BPS;
    uint256 internal constant MID = 38 * BPS;

    // If |spot - fair| / fair is below this band, quote symmetric mid fee.
    uint256 internal constant BAND = 36 * BPS;

    // EMA smoothing for fair proxy updates on step transitions.
    uint256 internal constant FAIR_EMA_N = 4;

    // slots[0] = fair proxy
    // slots[1] = last timestamp
    // slots[2] = previous bid fee
    // slots[3] = previous ask fee
    function afterInitialize(uint256 initialX, uint256 initialY)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        slots[0] = wdiv(initialY, initialX);
        slots[1] = type(uint256).max;
        slots[2] = MID;
        slots[3] = MID;
        return (MID, MID);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 fair = slots[0];
        uint256 spot = wdiv(trade.reserveY, trade.reserveX);
        uint256 prevBid = slots[2];
        uint256 prevAsk = slots[3];

        // Only refresh fair proxy once per simulation step using the first
        // observed trade in that step.
        if (trade.timestamp != slots[1]) {
            uint256 fairObservation = trade.isBuy
                ? wmul(spot, WAD - prevBid)
                : wdiv(spot, WAD - prevAsk);

            fair = ((fair * (FAIR_EMA_N - 1)) + fairObservation) / FAIR_EMA_N;
            slots[0] = fair;
            slots[1] = trade.timestamp;
        }

        uint256 mispricing = spot >= fair
            ? wdiv(spot - fair, fair)
            : wdiv(fair - spot, fair);

        // Inside a small band around fair proxy: stay symmetric.
        if (mispricing < BAND) {
            bidFee = MID;
            askFee = MID;
        } else if (spot > fair) {
            // Spot too high: make bid expensive, ask cheap.
            bidFee = HIGH;
            askFee = LOW;
        } else {
            // Spot too low: make ask expensive, bid cheap.
            bidFee = LOW;
            askFee = HIGH;
        }

        slots[2] = bidFee;
        slots[3] = askFee;
    }

    function getName() external pure override returns (string memory) {
        return "Optimized_ProxyBand_A3";
    }
}
