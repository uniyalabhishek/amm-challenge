// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Optimized AMM Strategy v2
/// @notice Key improvements over baseline:
///   - Higher favorable fees (volume share barely changes, but we earn more per trade)
///   - Tighter symmetric zone with competitive fee
///   - Better adverse fee scaling with trade-size toxicity signal
///   - Faster pHat convergence on new steps
contract Strategy is AMMStrategyBase {
    // Slot layout:
    // 0: pHat (fair price estimate)
    // 1: prevSpot
    // 2: emaAbsMove (volatility EMA)
    // 3: lastTs (last timestamp)
    // 4: lastBid
    // 5: lastAsk
    // 6: phase (same-step trade counter)
    // 7: emaTradeSizeY (trade size EMA in Y terms)
    // 8: cumTradesInStep

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot;     // pHat
        slots[1] = spot;     // prevSpot
        slots[2] = 0;        // emaAbsMove
        slots[3] = 0;        // lastTs
        uint256 initFee = bpsToWad(26);
        slots[4] = initFee;  // lastBid
        slots[5] = initFee;  // lastAsk
        slots[6] = 0;        // phase
        slots[7] = 0;        // emaTradeSizeY
        slots[8] = 0;        // cumTradesInStep

        return (initFee, initFee);
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
        uint256 emaTradeSizeY = slots[7];
        uint256 cumTradesInStep = slots[8];

        if (lastBid == 0) lastBid = bpsToWad(26);
        if (lastAsk == 0) lastAsk = bpsToWad(26);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        // Update trade size EMA (in Y terms)
        uint256 tradeY = trade.amountY;
        emaTradeSizeY = wmul(emaTradeSizeY, WAD - 15e16) + wmul(tradeY, 15e16);

        // Track trades within step
        if (dt > 0) {
            cumTradesInStep = 1;
        } else {
            cumTradesInStep += 1;
        }

        // --- Fair price estimation ---
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                // New step: use stronger EMA weight for first trade (arb reveals fair price)
                pHat = wmul(pHat, WAD - 30e16) + wmul(pImplied, 30e16);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                // Same-step: mild update
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) {
            if (phase < 10) phase += 1;
        }

        // --- Volatility estimation ---
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);

        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // --- Trade size toxicity ---
        // Large trades relative to reserves are more likely informed (arb)
        uint256 tradeImpact = trade.reserveY == 0 ? 0 : wdiv(tradeY, trade.reserveY);
        uint256 impactBps = wadToBps(tradeImpact);
        uint256 toxicityBoost = 0;
        if (impactBps > 30) {
            // Large trade: boost adverse fee
            toxicityBoost = (impactBps - 30) / 3;
            if (toxicityBoost > 20) toxicityBoost = 20;
        }

        // --- Adverse fee calculation ---
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10 + toxicityBoost;
        if (dt > 0) {
            // First trade of new step is more likely arb
            adverseBps += 5;
        }
        if (adverseBps < 42) adverseBps = 42;

        // --- Favorable fee calculation ---
        // Higher favorable fees since volume share barely changes
        uint256 favorBps;
        if (devBps <= 10) {
            favorBps = 24;
        } else if (devBps >= 60) {
            favorBps = 8;
        } else {
            favorBps = 24 - (devBps - 10) * (24 - 8) / (60 - 10);
        }

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));

        // --- Fee assignment ---
        if (devBps < 6) {
            // Small deviation: uncertain direction, use competitive symmetric fee
            bidFee = bpsToWad(27);
            askFee = bpsToWad(27);
        } else if (spot > pHat) {
            // Spot above fair: arbs sell X to AMM (bid side is adverse)
            askFee = favor;
            bidFee = adverse;
        } else {
            // Spot below fair: arbs buy X from AMM (ask side is adverse)
            bidFee = favor;
            askFee = adverse;
        }

        // --- Save state ---
        slots[0] = pHat;
        slots[1] = spot;
        slots[2] = emaAbsMove;
        slots[3] = ts;
        slots[4] = bidFee;
        slots[5] = askFee;
        slots[6] = phase;
        slots[7] = emaTradeSizeY;
        slots[8] = cumTradesInStep;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "OptV2";
    }
}
