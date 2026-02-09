// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title Optimized AMM Fee Strategy
/// @notice Direction-adaptive pHat with optimized parameters from coordinate descent.
///   Key improvements over baseline:
///   - Direction-confirming adaptive pHat (alpha=30% confirming, 22% contradicting)
///   - Same-step pHat update at 2% (vs 1%)
///   - Higher adverse floor (40 bps vs 38 bps)
///   - Lower new-step boost (3 bps vs 4 bps)
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot;
        slots[1] = spot;
        slots[2] = 0;
        slots[3] = 0;

        uint256 initFee = bpsToWad(15);
        slots[4] = initFee;
        slots[5] = bpsToWad(95);
        slots[6] = 0;
        slots[7] = 0;

        return (initFee, bpsToWad(95));
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
        uint256 lastDir = slots[7];

        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        // Direction-confirming adaptive pHat update
        bool confirming = false;
        if (lastDir == 1 && trade.isBuy) confirming = true;
        if (lastDir == 0 && !trade.isBuy) confirming = true;

        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                // Confirming trades get 30% weight, contradicting get 22%
                uint256 alpha = confirming ? 30e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                // Same-step update at 2%
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) {
            if (phase < 10) phase += 1;
        }

        // Volatility estimation
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);

        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // Adverse fee calculation
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) {
            adverseBps += 3;
        }
        if (adverseBps < 40) adverseBps = 40;

        // Favorable fee: linear interpolation from 20 bps to 1 bps
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

        // Update direction tracking
        uint256 newDir = spot > pHat ? 1 : 0;

        // Fee assignment
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

        // Store state
        slots[0] = pHat;
        slots[1] = spot;
        slots[2] = emaAbsMove;
        slots[3] = ts;
        slots[4] = bidFee;
        slots[5] = askFee;
        slots[6] = phase;
        slots[7] = newDir;

        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) {
        return "OptimizedAdaptive";
    }
}
