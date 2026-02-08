// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy, TradeInfo} from "./IAMMStrategy.sol";

/// @title Adaptive Skew Strategy
/// @notice Dynamic fee strategy that skews fees around an estimated fair price.
contract Strategy is AMMStrategyBase {
    uint256 private constant BASE_LOW = 10 * BPS; // 10 bps
    uint256 private constant BASE_HIGH = 50 * BPS; // 50 bps
    uint256 private constant ALPHA = 1e17; // 0.10

    function afterInitialize(uint256 initialX, uint256 initialY)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; // anchor price
        slots[1] = BASE_HIGH; // last bid fee
        slots[2] = BASE_HIGH; // last ask fee
        return (BASE_HIGH, BASE_HIGH);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 anchor = slots[0];
        uint256 lastBid = slots[1];
        uint256 lastAsk = slots[2];

        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        if (anchor == 0) {
            anchor = spot;
        }

        uint256 appliedFee = trade.isBuy ? lastBid : lastAsk;
        uint256 gamma = appliedFee >= WAD ? 0 : (WAD - appliedFee);
        uint256 target = spot;
        if (gamma > 0) {
            target = trade.isBuy ? wmul(gamma, spot) : wdiv(spot, gamma);
        }

        anchor = _ema(anchor, target, ALPHA);
        slots[0] = anchor;

        if (spot >= anchor) {
            uint256 ratio = wdiv(anchor, spot);
            uint256 blockFee = WAD > ratio ? (WAD - ratio) : 0;
            if (blockFee < BASE_HIGH) blockFee = BASE_HIGH;
            bidFee = blockFee;
            askFee = BASE_LOW;
        } else {
            uint256 ratio = wdiv(spot, anchor);
            uint256 blockFee = WAD > ratio ? (WAD - ratio) : 0;
            if (blockFee < BASE_HIGH) blockFee = BASE_HIGH;
            askFee = blockFee;
            bidFee = BASE_LOW;
        }

        bidFee = clampFee(bidFee);
        askFee = clampFee(askFee);

        slots[1] = bidFee;
        slots[2] = askFee;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "BlockArb_v1";
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
