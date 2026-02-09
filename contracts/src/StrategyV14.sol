// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V14 - Regime detection: vol-adaptive everything
/// @notice Key structural change: use volatility regime to scale ALL parameters.
///   High vol regime: wider symmetric zone, higher all fees, more cautious.
///   Low vol regime: narrower symmetric zone, competitive fees, more aggressive.
///   This is qualitatively different from the baseline which only scales adverse fee with vol.
contract Strategy is AMMStrategyBase {

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6];
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) { pHat = wmul(pHat, WAD - 25e16) + wmul(pImplied, 25e16); phase = 0; }
            else { if (phase < 10) phase += 1; pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16); }
        } else if (dt == 0) { if (phase < 10) phase += 1; }

        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // --- Vol regime detection ---
        // Low vol (volBps <= 10): market is quiet, be more aggressive with direction
        // Med vol (10 < volBps <= 25): normal market
        // High vol (volBps > 25): market is volatile, be more cautious
        uint256 symThresh;
        uint256 symFee;
        uint256 advFloor;
        uint256 favHigh;

        if (volBps <= 10) {
            // Low vol: confident direction, narrow sym zone, competitive fees
            symThresh = 6;
            symFee = 27;
            advFloor = 36;
            favHigh = 18;
        } else if (volBps <= 25) {
            // Normal: baseline-like
            symThresh = 8;
            symFee = 28;
            advFloor = 38;
            favHigh = 20;
        } else {
            // High vol: wider sym zone, higher fees
            symThresh = 10;
            symFee = 29;
            advFloor = 40;
            favHigh = 22;
        }

        // --- Adverse fee ---
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 4;
        if (adverseBps < advFloor) adverseBps = advFloor;

        // --- Favorable fee ---
        uint256 favorBps;
        if (devBps <= symThresh) { favorBps = favHigh; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = favHigh - (devBps - symThresh) * (favHigh - 1) / (50 - symThresh); }

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));

        if (devBps < symThresh) {
            bidFee = bpsToWad(symFee);
            askFee = bpsToWad(symFee);
        } else if (spot > pHat) {
            askFee = favor;
            bidFee = adverse;
        } else {
            bidFee = favor;
            askFee = adverse;
        }

        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee; slots[6] = phase;
        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) { return "OptV14"; }
}
