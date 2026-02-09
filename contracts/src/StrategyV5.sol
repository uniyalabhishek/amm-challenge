// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V5 - Geometric mean spread approach
/// @notice Key insight: Instead of directional asymmetry, use the geometric
///         mean of adverse/favorable fees. This ensures the spread product
///         (bid*ask) stays competitive while still protecting the adverse side.
///         Also: track consecutive arb direction to improve pHat confidence.
contract Strategy is AMMStrategyBase {

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot;      // pHat
        slots[1] = spot;      // prevSpot
        slots[2] = 0;         // emaAbsMove
        slots[3] = 0;         // lastTs
        slots[4] = bpsToWad(15);  // lastBid
        slots[5] = bpsToWad(95);  // lastAsk
        slots[6] = 0;         // phase
        slots[7] = 0;         // consecutive same-direction arb count
        slots[8] = 0;         // last arb direction (1=up, 2=down)

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
        uint256 consecDir = slots[7];
        uint256 lastDir = slots[8];

        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        // --- pHat and direction tracking ---
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        uint256 curDir = spot > pHat ? 1 : 2; // 1=spot above pHat, 2=below

        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                // Track arb direction consistency
                if (curDir == lastDir) {
                    if (consecDir < 20) consecDir += 1;
                } else {
                    consecDir = 0;
                }
                lastDir = curDir;

                // Adaptive EMA: faster when direction is consistent
                uint256 alpha = 25e16;
                if (consecDir > 3) {
                    alpha = 35e16; // More aggressive when direction is stable
                }
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
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

        // --- Adverse fee ---
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) {
            adverseBps += 4;
        }
        // Higher floor when direction is consistent (more confident)
        uint256 floorBps = 38;
        if (consecDir > 2) {
            floorBps = 40 + consecDir;
            if (floorBps > 50) floorBps = 50;
        }
        if (adverseBps < floorBps) adverseBps = floorBps;

        // --- Favorable fee ---
        uint256 favorBps;
        if (devBps <= 8) {
            favorBps = 20;
        } else if (devBps >= 50) {
            favorBps = 1;
        } else {
            favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8);
        }

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));

        // --- Assignment ---
        if (devBps < 8) {
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
        slots[7] = consecDir;
        slots[8] = lastDir;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "OptV5";
    }
}
