// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V19 - Higher symmetric (32) + adverse floor 40 + favorable floor 3 + direction-adaptive
/// @notice More aggressive symmetric fee. Adverse floor slightly higher.
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0;
        slots[7] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6];
        uint256 lastDir = slots[7];
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        bool confirming = false;
        if (lastDir == 1 && trade.isBuy) confirming = true;
        if (lastDir == 0 && !trade.isBuy) confirming = true;

        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                uint256 alpha = confirming ? 28e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 1e16) + wmul(pImplied, 1e16);
            }
        } else if (dt == 0) {
            if (phase < 10) phase += 1;
        }

        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 4;
        if (adverseBps < 40) adverseBps = 40;  // Higher adverse floor

        uint256 favorBps;
        if (devBps <= 8) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 3; }
        else { favorBps = 20 - (devBps - 8) * (20 - 3) / (50 - 8); }

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;

        // Higher symmetric: 32 bps
        if (devBps < 8) {
            bidFee = bpsToWad(32);
            askFee = bpsToWad(32);
        } else if (spot > pHat) {
            askFee = favor;
            bidFee = adverse;
        } else {
            bidFee = favor;
            askFee = adverse;
        }

        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) { return "OptV19"; }
}
