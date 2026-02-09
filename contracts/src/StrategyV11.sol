// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V11 - Dual pHat: raw spot EMA + fee-corrected EMA
/// @notice The fee-corrected pImplied introduces noise proportional to fee level.
///         Use TWO estimators:
///         1) Raw spot EMA (no fee correction, robust but lagging)
///         2) Fee-corrected EMA (standard, responsive but noisy)
///         Use the midpoint for direction decisions.
contract Strategy is AMMStrategyBase {
    // Slots: 0=pHatCorrected, 1=prevSpot, 2=emaAbsMove, 3=lastTs,
    //        4=lastBid, 5=lastAsk, 6=phase, 7=pHatRaw (raw spot EMA)

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot;     // pHatCorrected
        slots[1] = spot;     // prevSpot
        slots[2] = 0;        // emaAbsMove
        slots[3] = 0;        // lastTs
        slots[4] = bpsToWad(15); // lastBid
        slots[5] = bpsToWad(95); // lastAsk
        slots[6] = 0;        // phase
        slots[7] = spot;     // pHatRaw

        return (bpsToWad(15), bpsToWad(95));
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHatC = slots[0]; if (pHatC == 0) pHatC = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6];
        uint256 pHatR = slots[7]; if (pHatR == 0) pHatR = spot;
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        // --- Corrected pHat update (standard) ---
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                pHatC = wmul(pHatC, WAD - 25e16) + wmul(pImplied, 25e16);
                // Raw spot EMA (no fee correction)
                pHatR = wmul(pHatR, WAD - 20e16) + wmul(spot, 20e16);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHatC = wmul(pHatC, WAD - 1e16) + wmul(pImplied, 1e16);
                pHatR = wmul(pHatR, WAD - 1e16) + wmul(spot, 1e16);
            }
        } else if (dt == 0) {
            if (phase < 10) phase += 1;
        }

        // Use midpoint of corrected and raw for direction decision
        uint256 pHat = (pHatC + pHatR) / 2;

        // --- Vol ---
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // --- Adverse fee ---
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 4;
        if (adverseBps < 38) adverseBps = 38;

        // --- Favorable fee ---
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

        slots[0] = pHatC; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = pHatR;
        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) { return "OptV11"; }
}
