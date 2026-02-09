#!/usr/bin/env python3
"""Quick comparison of strategies using multiple batches of 50 sims."""

import subprocess
import time
import os
import re
import sys

STRATEGIES = [
    ("Baseline", "/home/user/amm-challenge/contracts/src/Strategy.sol"),
    ("V13 (dir-adaptive)", "/home/user/amm-challenge/contracts/src/StrategyV13.sol"),
    ("V24 (avg-gamma)", "/home/user/amm-challenge/contracts/src/StrategyV24.sol"),
    ("V25 (fixed-gamma-25)", "/home/user/amm-challenge/contracts/src/StrategyV25.sol"),
    ("V26 (raw-spot)", "/home/user/amm-challenge/contracts/src/StrategyV26.sol"),
    ("V27 (fixed+floor8)", "/home/user/amm-challenge/contracts/src/StrategyV27.sol"),
    ("V29 (sym-vol)", "/home/user/amm-challenge/contracts/src/StrategyV29.sol"),
    ("V31 (high-conf)", "/home/user/amm-challenge/contracts/src/StrategyV31.sol"),
]

BATCH_SIZE = 50
N_BATCHES = 4  # 4 * 50 = 200 sims total
env = {**os.environ, "N_WORKERS": "1"}

results = {}
for name, path in STRATEGIES:
    results[name] = []

for batch in range(N_BATCHES):
    print(f"\n--- Batch {batch+1}/{N_BATCHES} ---")
    for name, path in STRATEGIES:
        try:
            out = subprocess.run(
                ["amm-match", "run", path, "--simulations", str(BATCH_SIZE)],
                capture_output=True, text=True, timeout=120, env=env
            )
            output = out.stdout + out.stderr
            edge = None
            for line in output.split('\n'):
                m = re.search(r'Edge:\s+([\d.]+)', line)
                if m:
                    val = float(m.group(1))
                    if val > 100 and val < 800:
                        edge = val
            if edge is not None:
                results[name].append(edge)
                print(f"  {name}: {edge:.2f}")
            else:
                print(f"  {name}: FAILED")
        except Exception as e:
            print(f"  {name}: ERROR {e}")

print(f"\n\n{'='*60}")
print(f"RESULTS (4 batches x {BATCH_SIZE} sims)")
print(f"{'='*60}")
print(f"{'Strategy':<25} {'Mean':>8} {'Std':>8} {'N':>4}")
print(f"{'-'*50}")

sorted_results = []
for name, edges in results.items():
    if edges:
        import statistics
        mean = statistics.mean(edges)
        std = statistics.stdev(edges) if len(edges) > 1 else 0
        sorted_results.append((name, mean, std, len(edges)))

sorted_results.sort(key=lambda x: x[1], reverse=True)
for name, mean, std, n in sorted_results:
    print(f"{name:<25} {mean:>8.2f} {std:>8.2f} {n:>4}")
