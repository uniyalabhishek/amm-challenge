#!/usr/bin/env python3
"""Test strategies at 200 sims with better parsing."""

import subprocess
import time
import os
import re

STRATEGIES = [
    ("V13 (dir-adaptive)", "contracts/src/StrategyV13.sol"),
    ("V24 (avg-gamma)", "contracts/src/StrategyV24.sol"),
    ("V25 (fixed-gamma-25)", "contracts/src/StrategyV25.sol"),
    ("V26 (raw-spot-pHat)", "contracts/src/StrategyV26.sol"),
    ("V27 (fixed-gamma+floor8)", "contracts/src/StrategyV27.sol"),
    ("V29 (pure-sym-vol)", "contracts/src/StrategyV29.sol"),
    ("V30 (const-sym-30)", "contracts/src/StrategyV30.sol"),
    ("V31 (high-conf-asym)", "contracts/src/StrategyV31.sol"),
]

N_SIMS = 200
env = {**os.environ, "N_WORKERS": "1"}
results = []

for name, path in STRATEGIES:
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    start = time.time()

    try:
        out = subprocess.run(
            ["amm-match", "run", path, "--simulations", str(N_SIMS)],
            capture_output=True, text=True, timeout=300, env=env
        )
        elapsed = time.time() - start
        output = out.stdout + out.stderr

        # Parse edge: look for "Edge: XXX.XX" pattern in output
        edge = None
        for line in output.split('\n'):
            # Match pattern like "StrategyName Edge: 529.28"
            m = re.search(r'Edge:\s+([\d.]+)', line)
            if m:
                val = float(m.group(1))
                # Skip "200" from "200 simulations"
                if val > 300 and val < 800:
                    edge = val

        if edge is None:
            # Print last 10 lines for debugging
            print("PARSE FAILED. Last lines:")
            for line in output.split('\n')[-10:]:
                print(f"  {line}")

        results.append((name, edge, elapsed))
        print(f"Edge: {edge}, Time: {elapsed:.1f}s")

    except subprocess.TimeoutExpired:
        print("TIMEOUT")
        results.append((name, None, 300))
    except Exception as e:
        print(f"ERROR: {e}")
        results.append((name, None, 0))

print(f"\n\n{'='*60}")
print(f"RESULTS ({N_SIMS} sims each)")
print(f"{'='*60}")
print(f"{'Strategy':<30} {'Edge':>8}")
print(f"{'-'*40}")
for name, edge, elapsed in sorted(results, key=lambda x: x[1] if x[1] else 0, reverse=True):
    edge_str = f"{edge:.2f}" if edge else "ERROR"
    print(f"{name:<30} {edge_str:>8}")
