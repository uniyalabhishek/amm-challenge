#!/usr/bin/env python3
"""Test pHat correction variants at 500 sims."""

import subprocess
import sys
import time
import os

STRATEGIES = [
    ("Baseline", "contracts/src/Strategy.sol"),
    ("V13 (dir-adaptive)", "contracts/src/StrategyV13.sol"),
    ("V22 (high-favor-floor-8)", "contracts/src/StrategyV22.sol"),
    ("V23 (vol-scaled-sym)", "contracts/src/StrategyV23.sol"),
    ("V24 (avg-gamma)", "contracts/src/StrategyV24.sol"),
    ("V25 (fixed-gamma-25)", "contracts/src/StrategyV25.sol"),
    ("V26 (raw-spot-pHat)", "contracts/src/StrategyV26.sol"),
]

N_SIMS = 500

env = {**os.environ, "N_WORKERS": "1"}
results = []

for name, path in STRATEGIES:
    print(f"\n{'='*60}")
    print(f"Testing: {name} @ {N_SIMS} sims")
    start = time.time()

    try:
        out = subprocess.run(
            ["amm-match", "run", path, "--simulations", str(N_SIMS)],
            capture_output=True, text=True, timeout=600, env=env
        )
        elapsed = time.time() - start
        output = out.stdout + out.stderr

        edge = None
        for line in output.split('\n'):
            parts = line.split()
            for p in parts:
                try:
                    val = float(p.replace(',', ''))
                    if 100 < val < 700:
                        edge = val
                        break
                except ValueError:
                    pass
            if edge:
                break

        print(f"Edge: {edge}, Time: {elapsed:.1f}s")
        results.append((name, edge, elapsed))

    except Exception as e:
        print(f"ERROR: {e}")
        results.append((name, None, 0))

print(f"\n\n{'='*60}")
print(f"RESULTS SUMMARY ({N_SIMS} sims)")
print(f"{'='*60}")
print(f"{'Strategy':<30} {'Edge':>8} {'Diff':>8}")
print(f"{'-'*50}")
baseline_edge = results[0][1] if results[0][1] else 0
for name, edge, elapsed in results:
    edge_str = f"{edge:.2f}" if edge else "ERROR"
    diff = f"{edge - baseline_edge:+.2f}" if edge and baseline_edge else ""
    print(f"{name:<30} {edge_str:>8} {diff:>8}")
