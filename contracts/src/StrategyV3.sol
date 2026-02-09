// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V3 - Refined baseline with careful parameter tuning
/// @notice Changes from baseline:
///   - Widen symmetric zone threshold (less direction errors)
///   - Better adverse fee formula (higher floor, vol-aware)
///   - Moderate favorable fees (not too low)
///   - Faster pHat EMA on new-step for quicker adaptation
contract Strategy is AMMStrategyBase {

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot;
        slots[1] = spot;
        slots[2] = 0;
        slots[3] = 0;

        uint256 initBid = bpsToWad(15);
        uint256 initAsk = bpsToWad(95);
        slots[4] = initBid;
        slots[5] = initAsk;
        slots[6] = 0;

        return (initBid, initAsk);
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

        // --- Fair price estimation ---
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                // New step: first trade is usually arb, reveals fair price direction
                pHat = wmul(pHat, WAD - 28e16) + wmul(pImplied, 28e16);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 1e16) + wmul(pImplied, 1e16);
            }
        } else if (dt == 0) {
            if (phase < 10) phase += 1;
        }

        // --- Volatility ---
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);

        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // --- Adverse fee ---
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 13) / 10;
        if (dt > 0) {
            adverseBps += 5;
        }
        if (adverseBps < 40) adverseBps = 40;

        // --- Favorable fee ---
        uint256 favorBps;
        if (devBps <= 10) {
            favorBps = 18;
        } else if (devBps >= 50) {
            favorBps = 3;
        } else {
            favorBps = 18 - (devBps - 10) * (18 - 3) / (50 - 10);
        }

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));

        // --- Fee assignment ---
        if (devBps < 8) {
            // Uncertain direction: slightly undercut vanilla
            bidFee = bpsToWad(27);
            askFee = bpsToWad(27);
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
        return "OptV3";
    }
}
