#!/usr/bin/env python3
"""Analyze the parameter distribution across 1000 seeds and test at specific regimes."""

import numpy as np
import subprocess, os, re

# Compute exact parameters for each seed
params = []
for i in range(1000):
    rng = np.random.default_rng(seed=i)
    sigma = rng.uniform(0.000882, 0.001008)
    lam = rng.uniform(0.6, 1.0)
    size = rng.uniform(19.0, 21.0)
    params.append((i, sigma, lam, size))

sigmas = [p[1] for p in params]
lambdas = [p[2] for p in params]
sizes = [p[3] for p in params]

print("=" * 60)
print("PARAMETER DISTRIBUTION ACROSS 1000 SEEDS")
print("=" * 60)
print(f"\nSigma: min={min(sigmas):.6f}, max={max(sigmas):.6f}, mean={np.mean(sigmas):.6f}")
print(f"Lambda: min={min(lambdas):.4f}, max={max(lambdas):.4f}, mean={np.mean(lambdas):.4f}")
print(f"Size:   min={min(sizes):.4f}, max={max(sizes):.4f}, mean={np.mean(sizes):.4f}")

# Categorize seeds into regimes
high_vol_low_ret = [(i, s, l, sz) for i, s, l, sz in params if s > 0.000975 and l < 0.7]
low_vol_high_ret = [(i, s, l, sz) for i, s, l, sz in params if s < 0.000905 and l > 0.9]
nominal = [(i, s, l, sz) for i, s, l, sz in params if 0.000920 < s < 0.000970 and 0.75 < l < 0.85]

print(f"\nRegime breakdown:")
print(f"  HighVol-LowRet (sigma>0.000975, lambda<0.7): {len(high_vol_low_ret)} seeds")
print(f"  LowVol-HighRet (sigma<0.000905, lambda>0.9): {len(low_vol_high_ret)} seeds")
print(f"  Nominal (middle): {len(nominal)} seeds")

# Find the 5 worst-case seeds (highest sigma, lowest lambda)
worst_seeds = sorted(params, key=lambda p: p[1] / p[2], reverse=True)[:10]
best_seeds = sorted(params, key=lambda p: p[2] / p[1], reverse=True)[:10]

print("\nTop 10 HARDEST seeds (high sigma/lambda ratio):")
for i, s, l, sz in worst_seeds:
    print(f"  Seed {i:3d}: sigma={s:.6f}, lambda={l:.4f}, size={sz:.2f}, ratio={s/l:.6f}")

print("\nTop 10 EASIEST seeds (low sigma/lambda ratio):")
for i, s, l, sz in best_seeds:
    print(f"  Seed {i:3d}: sigma={s:.6f}, lambda={l:.4f}, size={sz:.2f}, ratio={s/l:.6f}")

# Compute average parameters (what the strategy is optimized for)
avg_sigma = np.mean(sigmas)
avg_lambda = np.mean(lambdas)
avg_size = np.mean(sizes)
print(f"\nAverage: sigma={avg_sigma:.6f}, lambda={avg_lambda:.4f}, size={avg_size:.2f}")

# The key question: how much does edge vary across seeds?
# We can estimate by testing at different specific parameter points

# Quartile analysis
sigmas_arr = np.array(sigmas)
lambdas_arr = np.array(lambdas)
print(f"\nSigma quartiles: {np.percentile(sigmas_arr, [25, 50, 75])}")
print(f"Lambda quartiles: {np.percentile(lambdas_arr, [25, 50, 75])}")

# Correlation between sigma and lambda across seeds
corr = np.corrcoef(sigmas, lambdas)[0, 1]
print(f"\nCorrelation between sigma and lambda: {corr:.4f}")
# (Should be ~0 since they're independently drawn)

# Now test at specific parameter combinations to understand the edge surface
SOL_PATH = "/home/user/amm-challenge/contracts/src/Sweep.sol"
STRAT_PATH = "/home/user/amm-challenge/contracts/src/Strategy.sol"
ENV = {**os.environ, "N_WORKERS": "1"}

def run_regime(sigma, retail_rate, n_sims=20, label=""):
    try:
        out = subprocess.run(
            ["amm-match", "run", STRAT_PATH, "--simulations", str(n_sims),
             "--volatility", str(sigma), "--retail-rate", str(retail_rate)],
            capture_output=True, text=True, timeout=120, env=ENV
        )
        output = out.stdout + out.stderr
        for line in output.split('\n'):
            m = re.search(r'Edge:\s+([\d.-]+)', line)
            if m:
                val = float(m.group(1))
                if val > -500 and val < 1500:
                    if label:
                        print(f"  {label}: {val:.2f}")
                    return val
    except Exception as e:
        if label:
            print(f"  {label}: ERROR {e}")
    return None

print("\n" + "=" * 60)
print("EDGE ACROSS SPECIFIC REGIMES (20 sims each)")
print("=" * 60)

# Grid test at 5x5 sigma/lambda combinations
sigmas_test = [0.000882, 0.000913, 0.000945, 0.000976, 0.001008]
lambdas_test = [0.6, 0.7, 0.8, 0.9, 1.0]

results = {}
for sig in sigmas_test:
    for lam in lambdas_test:
        label = f"s={sig:.6f} l={lam:.1f}"
        edge = run_regime(sig, lam, n_sims=20, label=label)
        results[(sig, lam)] = edge

print("\n--- EDGE HEATMAP ---")
header = 'sigma/lambda'
print(f"{header:>15s}", end="")
for lam in lambdas_test:
    print(f"  {lam:>7.1f}", end="")
print()
for sig in sigmas_test:
    print(f"  {sig:.6f}", end="")
    for lam in lambdas_test:
        e = results.get((sig, lam))
        if e is not None:
            print(f"  {e:7.1f}", end="")
        else:
            print(f"  {'FAIL':>7s}", end="")
    print()

# Compute weighted average (approximation of 1000-sim score)
if all(v is not None for v in results.values()):
    total = sum(results.values())
    avg = total / len(results)
    print(f"\nSimple grid average: {avg:.2f}")

    # Weighted by actual seed density
    # Since both are uniform, the grid is equally weighted
    # The 25 grid points represent the full parameter space
    print(f"(This approximates the 1000-sim average)")
