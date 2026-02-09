#!/usr/bin/env python3
"""Batch test multiple strategies at 200 sims for quick comparison."""

import subprocess
import sys
import time

STRATEGIES = [
    ("Baseline (28sym/1floor)", "contracts/src/Strategy.sol"),
    ("V13 (dir-adaptive 28/22)", "contracts/src/StrategyV13.sol"),
    ("V18 (30sym/3floor/dir)", "contracts/src/StrategyV18.sol"),
    ("V19 (32sym/40adv/3floor)", "contracts/src/StrategyV19.sol"),
    ("V20 (quad-adv/vol-alpha/30sym)", "contracts/src/StrategyV20.sol"),
    ("V21 (30sym/5floor/wide-zone)", "contracts/src/StrategyV21.sol"),
]

N_SIMS = 200

results = []
for name, path in STRATEGIES:
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"File: {path}")
    start = time.time()

    try:
        out = subprocess.run(
            ["amm-match", "run", path, "--simulations", str(N_SIMS)],
            capture_output=True, text=True, timeout=300,
            env={**__import__('os').environ, "N_WORKERS": "1"}
        )
        elapsed = time.time() - start

        # Parse output for edge score
        output = out.stdout + out.stderr
        edge = None
        wins = None
        for line in output.split('\n'):
            if 'Edge' in line and ('submission' in line.lower() or 'your' in line.lower() or 'strategy' in line.lower()):
                # Try to extract number
                parts = line.split()
                for p in parts:
                    try:
                        val = float(p.replace(',', ''))
                        if 100 < val < 1000:
                            edge = val
                    except ValueError:
                        pass
            if 'Win' in line or 'win' in line:
                wins = line.strip()

        # Fallback: just look for any float in reasonable range
        if edge is None:
            for line in output.split('\n'):
                parts = line.split()
                for p in parts:
                    try:
                        val = float(p.replace(',', ''))
                        if 400 < val < 700:
                            edge = val
                            break
                    except ValueError:
                        pass
                if edge:
                    break

        print(f"Output:\n{output[-500:]}")
        results.append((name, edge, elapsed, wins))
        print(f"Edge: {edge}, Time: {elapsed:.1f}s")

    except Exception as e:
        print(f"ERROR: {e}")
        results.append((name, None, 0, None))

print(f"\n\n{'='*60}")
print(f"RESULTS SUMMARY ({N_SIMS} simulations each)")
print(f"{'='*60}")
print(f"{'Strategy':<35} {'Edge':>8} {'Time':>8}")
print(f"{'-'*55}")
for name, edge, elapsed, wins in results:
    edge_str = f"{edge:.2f}" if edge else "ERROR"
    print(f"{name:<35} {edge_str:>8} {elapsed:>7.1f}s")
    if wins:
        print(f"  {wins}")
