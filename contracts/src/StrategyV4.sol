// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V4 - More aggressive adverse protection with vol-adaptive favorable
/// @notice Key idea: Maximize adverse fee, keep favorable competitive,
///         wider symmetric zone to avoid direction errors
contract Strategy is AMMStrategyBase {

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot;
        slots[1] = spot;
        slots[2] = 0;
        slots[3] = 0;
        slots[4] = bpsToWad(15);
        slots[5] = bpsToWad(95);
        slots[6] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
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

        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        // --- pHat update ---
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                pHat = wmul(pHat, WAD - 25e16) + wmul(pImplied, 25e16);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 1e16) + wmul(pImplied, 1e16);
            }
        } else if (dt == 0) {
            if (phase < 10) phase += 1;
        }

        // --- Vol ---
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);

        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // --- Adverse fee: higher floor, steeper scaling ---
        uint256 adverseBps = (devBps * 8) / 10 + (volBps * 13) / 10;
        if (dt > 0) {
            adverseBps += 4;
        }
        if (adverseBps < 42) adverseBps = 42;

        // --- Favorable fee: moderate range 5-18 bps ---
        uint256 favorBps;
        if (devBps <= 10) {
            favorBps = 18;
        } else if (devBps >= 60) {
            favorBps = 5;
        } else {
            favorBps = 18 - (devBps - 10) * (18 - 5) / (60 - 10);
        }

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));

        // --- Assignment with wide symmetric zone ---
        if (devBps < 10) {
            bidFee = bpsToWad(28);
            askFee = bpsToWad(28);
        } else if (spot > pHat) {
            askFee = favor;
            bidFee = adverse;
        } else {
            bidFee = favor;
            askFee = adverse;
        }

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
        return "OptV4";
    }
}
