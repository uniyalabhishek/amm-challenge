// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V12 - Adaptive pHat: use trade direction (isBuy) to estimate fair price
/// @notice Key insight: In constant-product with fee-on-input, after arb:
///   - If arb bought X (isBuy=false, AMM sold X): post-trade spot = γ_ask * fair
///   - If arb sold X (isBuy=true, AMM bought X): post-trade spot = fair / γ_bid
///   So: fair ≈ spot / γ_ask (after sell) or fair ≈ spot * γ_bid (after buy)
///   This gives a direct fair price estimate without EMA!
///   For the first trade of a new step (likely arb), use this direct estimate.
///   For subsequent trades, use gentle EMA.
contract Strategy is AMMStrategyBase {

    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot;     // pHat
        slots[1] = spot;     // prevSpot
        slots[2] = 0;        // emaAbsMove
        slots[3] = 0;        // lastTs
        slots[4] = bpsToWad(15);
        slots[5] = bpsToWad(95);
        slots[6] = 0;        // phase

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

        // --- pHat update ---
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            // Direct fair price estimate from post-arb spot:
            // After arb buy (isBuy=true, AMM bought X): spot = fair/γ_bid → fair = spot * γ_bid
            // After arb sell (isBuy=false, AMM sold X): spot = γ_ask * fair → fair = spot/γ_ask
            uint256 pDirect = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);

            if (dt > 0) {
                // First trade of new step: strong update using direct estimate
                // Use 40% weight - the first trade is highly informative
                pHat = wmul(pHat, WAD - 40e16) + wmul(pDirect, 40e16);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                // Same-step: weak update
                pHat = wmul(pHat, WAD - 1e16) + wmul(pDirect, 1e16);
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

        // --- Fees (same as baseline) ---
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 4;
        if (adverseBps < 38) adverseBps = 38;

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
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee; slots[6] = phase;
        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) { return "OptV12"; }
}
