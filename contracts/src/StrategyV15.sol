// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V15 - Post-arb retail optimization
/// @notice Key insight: After arb (first trade of step), next trades are likely retail.
///   Reduce adverse fee for retail window to attract more flow.
///   Arb has ALREADY happened at the old fees — we're setting fees for what comes NEXT.
///   After same-step trades, restore higher adverse for next step's arb.
contract Strategy is AMMStrategyBase {
    // slots: 0=pHat, 1=prevSpot, 2=emaAbsMove, 3=lastTs,
    //        4=lastBid, 5=lastAsk, 6=phase, 7=baseAdverseBps (for next step's arb)

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0;
        slots[7] = 38; // baseAdverseBps
        return (bpsToWad(15), bpsToWad(95));
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6];
        uint256 baseAdv = slots[7];
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);
        if (baseAdv == 0) baseAdv = 38;

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
        } else if (dt == 0) { if (phase < 10) phase += 1; }

        // --- Vol ---
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // --- Compute base adverse fee (for arb defense) ---
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (adverseBps < 38) adverseBps = 38;

        // --- Phase-dependent fee adjustment ---
        if (dt > 0) {
            // Just processed a new-step trade (arb).
            // Save the full adverse fee for NEXT step's arb defense
            baseAdv = adverseBps + 4;
            // But set LOWER fees for same-step retail that's about to arrive
            adverseBps = adverseBps > 6 ? adverseBps - 6 : adverseBps;
        } else {
            // Same-step trade (retail). Keep competitive fees.
            // If this is the last retail before next step, we need to set arb-defense fees.
            // Use the saved baseAdv for next step's first trade
            adverseBps = baseAdv;
        }

        // --- Favorable fee (same as baseline) ---
        uint256 favorBps;
        if (devBps <= 8) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8); }

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));

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

        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = baseAdv;
        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) { return "OptV15"; }
}
