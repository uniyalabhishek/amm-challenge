#!/usr/bin/env python3
"""Test vol-adaptive strategies across different regimes."""

import subprocess
import os
import re

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

# Current best: StrategyFinal
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

# V44: Vol-adaptive with higher fees in high vol
# High vol (volBps>15): sym=32, thresh=10, advFloor=45
# Low vol (volBps<=10): sym=26, thresh=6, advFloor=38
# Medium: defaults (sym=28, thresh=8, advFloor=40)
V44_VOLADAPT2 = """// SPDX-License-Identifier: MIT
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

        // Vol-adaptive parameters
        uint256 symFeeBps; uint256 threshold; uint256 advFloor;
        if (volBps > 15) {
            symFeeBps = 32; threshold = 10; advFloor = 45;
        } else if (volBps <= 10) {
            symFeeBps = 26; threshold = 6; advFloor = 38;
        } else {
            symFeeBps = 28; threshold = 8; advFloor = 40;
        }

        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < advFloor) adverseBps = advFloor;
        uint256 favorBps;
        if (devBps <= threshold) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - threshold) * (20 - 1) / (50 - threshold); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < threshold) {
            bidFee = bpsToWad(symFeeBps); askFee = bpsToWad(symFeeBps);
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

# V45: Continuous vol-adaptive (linear interpolation)
# symFee = 22 + volBps (clamped 22-40)
# threshold = max(5, 8 + (volBps-12)/3) (clamped 5-15)
# advFloor = 35 + volBps/2 (clamped 35-50)
V45_CONTVOLADAPT = """// SPDX-License-Identifier: MIT
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

        // Continuous vol-adaptive: smoothly scale fees with vol
        // symFee scales from 24 (vol=5) to 36 (vol=25)
        uint256 vClamped = volBps > 25 ? 25 : (volBps < 5 ? 5 : volBps);
        uint256 symFeeBps = 24 + (vClamped - 5) * 12 / 20; // 24 to 36
        // advFloor scales from 36 (vol=5) to 48 (vol=25)
        uint256 advFloor = 36 + (vClamped - 5) * 12 / 20;  // 36 to 48
        // threshold scales from 6 (vol=5) to 12 (vol=25)
        uint256 threshold = 6 + (vClamped - 5) * 6 / 20;    // 6 to 12

        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < advFloor) adverseBps = advFloor;
        uint256 favorBps;
        if (devBps <= threshold) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - threshold) * (20 - 1) / (50 - threshold); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < threshold) {
            bidFee = bpsToWad(symFeeBps); askFee = bpsToWad(symFeeBps);
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

# V46: Conservative high-vol protection (only activate for vol>15, don't change low vol)
V46_HIVOL = """// SPDX-License-Identifier: MIT
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

        // Default params (same as StrategyFinal)
        uint256 symFeeBps = 28; uint256 threshold = 8; uint256 advFloor = 40;
        // ONLY adjust for high vol: raise protection
        if (volBps > 15) {
            symFeeBps = 28 + (volBps - 15) / 2;  // 28 at vol=15, 33 at vol=25
            if (symFeeBps > 36) symFeeBps = 36;
            advFloor = 40 + (volBps - 15) / 2;   // 40 at vol=15, 45 at vol=25
            if (advFloor > 48) advFloor = 48;
            threshold = 8 + (volBps - 15) / 4;   // 8 at vol=15, 10 at vol=25
            if (threshold > 12) threshold = 12;
        }

        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < advFloor) adverseBps = advFloor;
        uint256 favorBps;
        if (devBps <= threshold) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - threshold) * (20 - 1) / (50 - threshold); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < threshold) {
            bidFee = bpsToWad(symFeeBps); askFee = bpsToWad(symFeeBps);
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

strategies = [
    ("CURRENT", CURRENT),
    ("V44-VolAdapt2", V44_VOLADAPT2),
    ("V45-ContVolAdapt", V45_CONTVOLADAPT),
    ("V46-HiVolProtect", V46_HIVOL),
]

regimes = [
    ("20sim-default", 20, None),
    ("30sim-default", 30, None),
    ("HighVol-LowRet", 20, ["--volatility", "0.001008", "--retail-rate", "0.6"]),
    ("LowVol-HiRet", 20, ["--volatility", "0.000882", "--retail-rate", "1.0"]),
    ("MedVol-MedRet", 20, ["--volatility", "0.000945", "--retail-rate", "0.8"]),
]

print("=" * 80)
print("VOL-ADAPTIVE STRATEGY CROSS-REGIME COMPARISON")
print("=" * 80)

all_results = {}
for strat_name, strat_code in strategies:
    all_results[strat_name] = {}
    print(f"\n--- {strat_name} ---")
    for regime_name, n_sims, args in regimes:
        edge = run_sol(strat_code, f"{strat_name}/{regime_name}", n_sims=n_sims, extra_args=args)
        all_results[strat_name][regime_name] = edge

# Print comparison table
print(f"\n{'='*80}")
print(f"{'Strategy':<20}", end="")
for regime_name, _, _ in regimes:
    print(f"{regime_name:>15}", end="")
print()
print("-" * 95)
for strat_name in [s[0] for s in strategies]:
    print(f"{strat_name:<20}", end="")
    for regime_name, _, _ in regimes:
        val = all_results[strat_name].get(regime_name)
        if val is not None:
            print(f"{val:>15.2f}", end="")
        else:
            print(f"{'FAIL':>15}", end="")
    print()

# Print diffs from CURRENT
print(f"\n{'='*80}")
print("DIFFERENCES FROM CURRENT:")
ref_results = all_results.get("CURRENT", {})
for strat_name in [s[0] for s in strategies]:
    if strat_name == "CURRENT":
        continue
    print(f"\n{strat_name}:")
    for regime_name, _, _ in regimes:
        ref = ref_results.get(regime_name)
        val = all_results[strat_name].get(regime_name)
        if ref and val:
            print(f"  {regime_name:20s}: {val-ref:+.2f}")
