#!/usr/bin/env python3
"""Coordinate descent parameter sweep for V13-based strategy."""

import subprocess
import os
import re
import time

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
N_SIMS = 50
ENV = {**os.environ, "N_WORKERS": "1"}

# V13 baseline parameters
BEST = {
    "alpha_confirm": 28,
    "alpha_contra": 22,
    "alpha_same": 1,
    "sym_fee": 28,
    "adv_floor": 38,
    "favor_floor": 1,
    "favor_top": 20,
    "dev_coeff": 7,
    "vol_coeff": 12,
    "boost": 4,
    "threshold": 8,
}

def run_strategy(params):
    code = TEMPLATE.format(**params)
    with open(SOL_PATH, 'w') as f:
        f.write(code)
    try:
        out = subprocess.run(
            ["amm-match", "run", SOL_PATH, "--simulations", str(N_SIMS)],
            capture_output=True, text=True, timeout=120, env=ENV
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

def sweep_param(param_name, values, current_best):
    print(f"\n--- Sweeping {param_name}: {values} ---")
    results = []
    for val in values:
        params = dict(current_best)
        params[param_name] = val
        edge = run_strategy(params)
        marker = " <-- current" if val == current_best[param_name] else ""
        best_marker = ""
        results.append((val, edge))
        if edge:
            print(f"  {param_name}={val}: {edge:.2f}{marker}")
        else:
            print(f"  {param_name}={val}: FAILED{marker}")

    # Find best
    valid = [(v, e) for v, e in results if e is not None]
    if valid:
        best_val, best_edge = max(valid, key=lambda x: x[1])
        print(f"  BEST: {param_name}={best_val} -> {best_edge:.2f}")
        return best_val
    return current_best[param_name]

# Run baseline first
print("Testing V13 baseline...")
baseline_edge = run_strategy(BEST)
print(f"V13 baseline: {baseline_edge}")

# Coordinate descent
best = dict(BEST)

best["alpha_confirm"] = sweep_param("alpha_confirm", [24, 26, 28, 30, 32, 35], best)
best["alpha_contra"] = sweep_param("alpha_contra", [16, 18, 20, 22, 24, 26], best)
best["alpha_same"] = sweep_param("alpha_same", [1, 2, 3], best)
best["sym_fee"] = sweep_param("sym_fee", [25, 26, 27, 28, 29, 30, 32], best)
best["adv_floor"] = sweep_param("adv_floor", [34, 35, 36, 37, 38, 39, 40, 42], best)
best["favor_floor"] = sweep_param("favor_floor", [1, 2, 3, 5, 8], best)
best["favor_top"] = sweep_param("favor_top", [15, 18, 20, 22, 25], best)
best["dev_coeff"] = sweep_param("dev_coeff", [5, 6, 7, 8, 9], best)
best["vol_coeff"] = sweep_param("vol_coeff", [8, 10, 12, 14, 16], best)
best["boost"] = sweep_param("boost", [2, 3, 4, 5, 6, 8], best)
best["threshold"] = sweep_param("threshold", [5, 6, 7, 8, 9, 10, 12], best)

# Final test with best params
print(f"\n{'='*60}")
print(f"FINAL BEST PARAMETERS:")
for k, v in best.items():
    changed = " (CHANGED)" if v != BEST[k] else ""
    print(f"  {k}: {v}{changed}")

final_edge = run_strategy(best)
print(f"\nFinal edge: {final_edge}")
print(f"Baseline edge: {baseline_edge}")
if final_edge and baseline_edge:
    print(f"Improvement: {final_edge - baseline_edge:+.2f}")
