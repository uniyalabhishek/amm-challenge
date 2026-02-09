#!/usr/bin/env python3
"""Run parameter sweep using small batches to avoid segfault."""

import sys
import os
import re
import subprocess
import time
import json
import numpy as np
from pathlib import Path

# Run a strategy at N sims using multiple small batches
def run_strategy_safe(sol_path, total_sims=50, batch_size=10):
    """Run strategy in small batches of batch_size to avoid segfault."""
    edges = []
    for start in range(0, total_sims, batch_size):
        n = min(batch_size, total_sims - start)
        try:
            out = subprocess.run(
                ["amm-match", "run", sol_path, "--simulations", str(n)],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "N_WORKERS": "1"}
            )
            output = out.stdout + out.stderr
            for line in output.split('\n'):
                m = re.search(r'Edge:\s+([\d.]+)', line)
                if m:
                    val = float(m.group(1))
                    if val > 50 and val < 1000:
                        edges.append((n, val))
        except:
            pass

    if not edges:
        return None

    # Weight by number of sims
    total_n = sum(n for n, _ in edges)
    total_edge = sum(n * e for n, e in edges)
    return total_edge / total_n

# But wait - seeds are fixed (0 to n-1), so each batch starts from seed 0!
# Each batch of 10 sims uses seeds 0-9. Running 5 batches gives 5x the same result.
# We need a different approach.

# Instead, let's just run with max sims that work (seems to be 20-40 range)
# and compare strategies on the same seeds.

TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {{
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {{
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0; slots[7] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }}
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {{
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
        bool confirming = false;
        if (lastDir == 1 && trade.isBuy) confirming = true;
        if (lastDir == 0 && !trade.isBuy) confirming = true;
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {{
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {{
                uint256 alpha = confirming ? {alpha_confirm}e16 : {alpha_contra}e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            }} else {{
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - {alpha_same}e16) + wmul(pImplied, {alpha_same}e16);
            }}
        }} else if (dt == 0) {{ if (phase < 10) phase += 1; }}
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);
        uint256 adverseBps = (devBps * {dev_coeff}) / 10 + (volBps * {vol_coeff}) / 10;
        if (dt > 0) adverseBps += {boost};
        if (adverseBps < {adv_floor}) adverseBps = {adv_floor};
        uint256 favorBps;
        if (devBps <= {threshold}) {{ favorBps = {favor_top}; }}
        else if (devBps >= 50) {{ favorBps = {favor_floor}; }}
        else {{ favorBps = {favor_top} - (devBps - {threshold}) * ({favor_top} - {favor_floor}) / (50 - {threshold}); }}
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < {threshold}) {{
            bidFee = bpsToWad({sym_fee});
            askFee = bpsToWad({sym_fee});
        }} else if (spot > pHat) {{
            askFee = favor;
            bidFee = adverse;
        }} else {{
            bidFee = favor;
            askFee = adverse;
        }}
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }}
    function getName() external pure override returns (string memory) {{ return "Sweep"; }}
}}
"""

SOL_PATH = "/home/user/amm-challenge/contracts/src/Sweep.sol"
N_SIMS = 20  # Use 20 sims to avoid segfault
ENV = {**os.environ, "N_WORKERS": "1"}

BEST = {
    "alpha_confirm": 28, "alpha_contra": 22, "alpha_same": 1,
    "sym_fee": 28, "adv_floor": 38, "favor_floor": 1, "favor_top": 20,
    "dev_coeff": 7, "vol_coeff": 12, "boost": 4, "threshold": 8,
}

def run_one(params):
    code = TEMPLATE.format(**params)
    with open(SOL_PATH, 'w') as f:
        f.write(code)
    try:
        out = subprocess.run(
            ["amm-match", "run", SOL_PATH, "--simulations", str(N_SIMS)],
            capture_output=True, text=True, timeout=60, env=ENV
        )
        output = out.stdout + out.stderr
        for line in output.split('\n'):
            m = re.search(r'Edge:\s+([\d.]+)', line)
            if m:
                val = float(m.group(1))
                if val > 100 and val < 800:
                    return val
    except:
        pass
    return None

def sweep(param_name, values, current_best):
    print(f"\n--- {param_name}: {values} ---")
    results = []
    for val in values:
        params = dict(current_best)
        params[param_name] = val
        edge = run_one(params)
        cur = " <-cur" if val == current_best[param_name] else ""
        if edge:
            results.append((val, edge))
            print(f"  {param_name}={val}: {edge:.2f}{cur}")
        else:
            print(f"  {param_name}={val}: FAIL{cur}")
    if results:
        best_val, best_edge = max(results, key=lambda x: x[1])
        print(f"  BEST: {param_name}={best_val} ({best_edge:.2f})")
        return best_val
    return current_best[param_name]

# Test baseline
print("V13 baseline (20 sims)...")
base_edge = run_one(BEST)
print(f"Baseline: {base_edge}\n")

# Also test original baseline (no dir-adaptive)
ORIG = dict(BEST)
ORIG["alpha_confirm"] = 25
ORIG["alpha_contra"] = 25
orig_edge = run_one(ORIG)
print(f"Original (no dir-adaptive): {orig_edge}\n")

best = dict(BEST)

# Sweep each parameter
best["alpha_confirm"] = sweep("alpha_confirm", [24,26,28,30,32,35], best)
best["alpha_contra"] = sweep("alpha_contra", [16,18,20,22,24,26], best)
best["alpha_same"] = sweep("alpha_same", [1,2,3,5], best)
best["sym_fee"] = sweep("sym_fee", [25,26,27,28,29,30,32], best)
best["adv_floor"] = sweep("adv_floor", [34,35,36,37,38,39,40,42], best)
best["favor_floor"] = sweep("favor_floor", [1,2,3,5,8,10], best)
best["favor_top"] = sweep("favor_top", [15,18,20,22,25], best)
best["dev_coeff"] = sweep("dev_coeff", [5,6,7,8,9], best)
best["vol_coeff"] = sweep("vol_coeff", [8,10,12,14,16], best)
best["boost"] = sweep("boost", [2,3,4,5,6,8], best)
best["threshold"] = sweep("threshold", [5,6,7,8,9,10,12], best)

print(f"\n{'='*60}")
print("FINAL BEST PARAMETERS:")
for k, v in best.items():
    changed = " ** CHANGED **" if v != BEST[k] else ""
    print(f"  {k}: {v}{changed}")
final_edge = run_one(best)
print(f"\nFinal: {final_edge} | V13 baseline: {base_edge} | Orig: {orig_edge}")
if final_edge and base_edge:
    print(f"Improvement over V13: {final_edge - base_edge:+.2f}")
if final_edge and orig_edge:
    print(f"Improvement over orig: {final_edge - orig_edge:+.2f}")
