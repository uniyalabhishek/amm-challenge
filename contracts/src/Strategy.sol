// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy, TradeInfo} from "./IAMMStrategy.sol";

/// @title Combined Block + Affine Strategy
/// @notice Blends pHat inference, vol tracking, and arb-blocking fees.
contract Strategy is AMMStrategyBase {
    // EMA parameters (WAD)
    uint256 private constant EMA_NEW = 25e16; // 0.25
    uint256 private constant EMA_SAME = 1e16; // 0.01
    uint256 private constant VOL_ALPHA = 2e17; // 0.20

    // Favorable side fee curve (bps)
    uint256 private constant FAVOR_MAX = 20;
    uint256 private constant FAVOR_MIN = 1;
    uint256 private constant FAVOR_DEV_LOW = 8;
    uint256 private constant FAVOR_DEV_HIGH = 50;

    // Adverse side fee floor (bps)
    uint256 private constant ADV_VOL_W = 12;
    uint256 private constant ADV_DEV_W = 7;
    uint256 private constant ADV_FLOOR = 38;
    uint256 private constant ADV_STEP_BONUS = 4;

    // Arb-blocking floor (bps)
    uint256 private constant BLOCK_FLOOR = 35;
    uint256 private constant BLOCK_BUFFER = 0;

    function afterInitialize(uint256 initialX, uint256 initialY)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; // pHat
        slots[1] = spot; // prev spot
        slots[2] = 0; // ema abs move
        slots[3] = 0; // last timestamp
        slots[4] = bpsToWad(15); // last bid
        slots[5] = bpsToWad(95); // last ask
        slots[6] = 0; // phase
        return (slots[4], slots[5]);
    }

    function afterSwap(TradeInfo calldata trade)
        external
        override
        returns (uint256 bidFee, uint256 askFee)
    {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0];
        if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1];
        if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2];
        uint256 lastTs = slots[3];
        uint256 lastBid = slots[4];
        uint256 lastAsk = slots[5];
        uint256 phase = slots[6];

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                pHat = wmul(pHat, WAD - EMA_NEW) + wmul(pImplied, EMA_NEW);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - EMA_SAME) + wmul(pImplied, EMA_SAME);
            }
        } else if (dt == 0) {
            if (phase < 10) phase += 1;
        }

        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - VOL_ALPHA) + wmul(absMove, VOL_ALPHA);

        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        uint256 adverseBps = (devBps * ADV_DEV_W) / 10 + (volBps * ADV_VOL_W) / 10;
        if (dt > 0) adverseBps += ADV_STEP_BONUS;
        if (adverseBps < ADV_FLOOR) adverseBps = ADV_FLOOR;

        uint256 favorBps;
        if (devBps <= FAVOR_DEV_LOW) {
            favorBps = FAVOR_MAX;
        } else if (devBps >= FAVOR_DEV_HIGH) {
            favorBps = FAVOR_MIN;
        } else {
            favorBps =
                FAVOR_MAX
                - (devBps - FAVOR_DEV_LOW) * (FAVOR_MAX - FAVOR_MIN)
                / (FAVOR_DEV_HIGH - FAVOR_DEV_LOW);
        }

        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 favor = bpsToWad(favorBps);

        if (spot >= pHat) {
            uint256 ratio = wdiv(pHat, spot);
            uint256 blockFee = WAD > ratio ? (WAD - ratio) : 0;
            blockFee = blockFee + bpsToWad(BLOCK_BUFFER);
            uint256 blockFloor = bpsToWad(BLOCK_FLOOR);
            if (blockFee < blockFloor) blockFee = blockFloor;
            uint256 adv = blockFee > adverse ? blockFee : adverse;
            bidFee = adv;
            askFee = favor;
        } else {
            uint256 ratio = wdiv(spot, pHat);
            uint256 blockFee = WAD > ratio ? (WAD - ratio) : 0;
            blockFee = blockFee + bpsToWad(BLOCK_BUFFER);
            uint256 blockFloor = bpsToWad(BLOCK_FLOOR);
            if (blockFee < blockFloor) blockFee = blockFloor;
            uint256 adv = blockFee > adverse ? blockFee : adverse;
            askFee = adv;
            bidFee = favor;
        }

        bidFee = clampFee(bidFee);
        askFee = clampFee(askFee);

        slots[0] = pHat;
        slots[1] = spot;
        slots[2] = emaAbsMove;
        slots[3] = ts;
        slots[4] = bidFee;
        slots[5] = askFee;
        slots[6] = phase;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "CombinedBlockAffine_v1";
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
