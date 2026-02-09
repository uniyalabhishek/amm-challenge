#!/usr/bin/env python3
"""Test a strategy that adapts to estimated retail flow rate (lambda)."""

import subprocess, os, re

SOL_PATH = "/home/user/amm-challenge/contracts/src/Sweep.sol"
ENV = {**os.environ, "N_WORKERS": "1"}

def run_sol(code, label, n_sims=20, extra_args=None):
    with open(SOL_PATH, 'w') as f:
        f.write(code)
    cmd = ["amm-match", "run", SOL_PATH, "--simulations", str(n_sims)]
    if extra_args:
        cmd.extend(extra_args)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=ENV)
        output = out.stdout + out.stderr
        for line in output.split('\n'):
            m = re.search(r'Edge:\s+([\d.-]+)', line)
            if m:
                val = float(m.group(1))
                if val > -500 and val < 1500:
                    print(f"  {label}: {val:.2f}")
                    return val
        print(f"  {label}: PARSE FAIL")
    except Exception as e:
        print(f"  {label}: ERROR {e}")
    return None

# V47: Retail-adaptive strategy
# Track estimated retail rate using EMA of phase counts per step
# In high-retail regime: can afford to be more aggressive (lower favorable)
# In low-retail regime: need more protection (higher symmetric)
V47_RETAIL = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0; slots[7] = 0;
        slots[8] = 0;  // emaRetailPerStep (in WAD: 0.5 = 5e17)
        slots[9] = 0;  // stepPhaseCount (retail trades in current step)
        return (bpsToWad(15), bpsToWad(95));
    }
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6]; uint256 lastDir = slots[7];
        uint256 emaRetail = slots[8];
        uint256 stepPhaseCount = slots[9];
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);
        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;
        bool confirming = (lastDir == 1 && trade.isBuy) || (lastDir == 0 && !trade.isBuy);
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                // New step: update retail EMA from previous step's count
                // emaRetail = 0.95 * emaRetail + 0.05 * stepPhaseCount_WAD
                uint256 countWad = stepPhaseCount * WAD;  // convert count to WAD
                emaRetail = wmul(emaRetail, 95e16) + wmul(countWad, 5e16);
                stepPhaseCount = 0;  // reset for new step

                uint256 alpha = confirming ? 30e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                stepPhaseCount += 1;  // count retail trades
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) {
            if (phase < 10) phase += 1;
            stepPhaseCount += 1;
        }
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // Estimate retail rate: emaRetail/WAD ≈ avg retail trades per step for our AMM
        // Our AMM gets ~50% of total retail. So total lambda ≈ 2 * emaRetail/WAD
        // lambda range: 0.6 to 1.0. Our share: 0.3 to 0.5 trades per step
        // In WAD: 0.3 = 3e17, 0.5 = 5e17

        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;

        // Retail-adaptive: in low retail, raise adverse floor
        uint256 advFloor = 40;
        if (emaRetail < 3e17) {
            // Very low retail: raise floor to 44
            advFloor = 44;
        } else if (emaRetail < 4e17) {
            // Low retail: raise floor to 42
            advFloor = 42;
        }
        // In high retail, could lower floor, but baseline 40 seems near-optimal

        if (adverseBps < advFloor) adverseBps = advFloor;
        uint256 favorBps;
        if (devBps <= 8) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < 8) {
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        } else if (spot > pHat) {
            askFee = favor; bidFee = adverse;
        } else {
            bidFee = favor; askFee = adverse;
        }
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        slots[8] = emaRetail; slots[9] = stepPhaseCount;
        return (bidFee, askFee);
    }
    function getName() external pure override returns (string memory) { return "Sweep"; }
}
"""

# CURRENT reference
CURRENT = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0; slots[7] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6]; uint256 lastDir = slots[7];
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);
        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;
        bool confirming = (lastDir == 1 && trade.isBuy) || (lastDir == 0 && !trade.isBuy);
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                uint256 alpha = confirming ? 30e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) { if (phase < 10) phase += 1; }
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < 40) adverseBps = 40;
        uint256 favorBps;
        if (devBps <= 8) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < 8) {
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        } else if (spot > pHat) {
            askFee = favor; bidFee = adverse;
        } else {
            bidFee = favor; askFee = adverse;
        }
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }
    function getName() external pure override returns (string memory) { return "Sweep"; }
}
"""

print("=" * 60)
print("RETAIL-ADAPTIVE STRATEGY TEST")
print("=" * 60)

# Test across regimes
for strat_name, strat_code in [("CURRENT", CURRENT), ("V47-RetailAdapt", V47_RETAIL)]:
    print(f"\n--- {strat_name} ---")
    run_sol(strat_code, f"{strat_name}/20sim")
    run_sol(strat_code, f"{strat_name}/HighVol-LowRet",
            extra_args=["--volatility", "0.001008", "--retail-rate", "0.6"])
    run_sol(strat_code, f"{strat_name}/LowVol-HiRet",
            extra_args=["--volatility", "0.000882", "--retail-rate", "1.0"])
