#!/usr/bin/env python3
"""Multi-seed benchmark runner for AMM strategy iteration.

Why this script exists:
- `amm-match run` reports one aggregate from contiguous seeds (0..N-1).
- That can overfit local tuning to a single seed slice.
- This script runs repeated batches over spaced seed offsets and prints
  robust summary stats (mean/min/max/spread/stddev).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import amm_sim_rs
import numpy as np

from amm_competition.competition.config import (
    BASELINE_SETTINGS,
    BASELINE_VARIANCE,
    baseline_nominal_retail_rate,
    baseline_nominal_retail_size,
    baseline_nominal_sigma,
    resolve_n_workers,
)
from amm_competition.competition.match import HyperparameterVariance, MatchRunner
from amm_competition.evm.adapter import EVMStrategyAdapter
from amm_competition.evm.baseline import load_vanilla_strategy
from amm_competition.evm.compiler import SolidityCompiler
from amm_competition.evm.validator import SolidityValidator


def make_runner_with_seed_offset(
    *,
    n_simulations: int,
    config: amm_sim_rs.SimulationConfig,
    n_workers: int,
    variance: HyperparameterVariance,
    seed_offset: int,
) -> MatchRunner:
    """Create a MatchRunner with deterministic seed offset.

    We monkey-patch `_build_configs` so each batch can shift the seed range
    while preserving the same hyperparameter sampling logic.
    """
    runner = MatchRunner(
        n_simulations=n_simulations,
        config=config,
        n_workers=n_workers,
        variance=variance,
    )

    def patched_build_configs() -> list[amm_sim_rs.SimulationConfig]:
        configs: list[amm_sim_rs.SimulationConfig] = []
        for i in range(runner.n_simulations):
            seed = i + seed_offset
            rng = np.random.default_rng(seed=seed)

            retail_mean_size = (
                rng.uniform(variance.retail_mean_size_min, variance.retail_mean_size_max)
                if variance.vary_retail_mean_size
                else config.retail_mean_size
            )
            retail_arrival_rate = (
                rng.uniform(variance.retail_arrival_rate_min, variance.retail_arrival_rate_max)
                if variance.vary_retail_arrival_rate
                else config.retail_arrival_rate
            )
            gbm_sigma = (
                rng.uniform(variance.gbm_sigma_min, variance.gbm_sigma_max)
                if variance.vary_gbm_sigma
                else config.gbm_sigma
            )

            cfg = amm_sim_rs.SimulationConfig(
                n_steps=config.n_steps,
                initial_price=config.initial_price,
                initial_x=config.initial_x,
                initial_y=config.initial_y,
                gbm_mu=config.gbm_mu,
                gbm_sigma=gbm_sigma,
                gbm_dt=config.gbm_dt,
                retail_arrival_rate=retail_arrival_rate,
                retail_mean_size=retail_mean_size,
                retail_size_sigma=config.retail_size_sigma,
                retail_buy_prob=config.retail_buy_prob,
                seed=seed,
            )
            configs.append(cfg)
        return configs

    runner._build_configs = patched_build_configs
    return runner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Robust multi-seed benchmark for AMM strategy files."
    )
    parser.add_argument("strategy", help="Path to Solidity strategy file (.sol)")
    parser.add_argument(
        "--sims",
        type=int,
        default=100,
        help="Simulations per seed offset batch (default: 100)",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=5,
        help="Number of seed offsets to evaluate (default: 5)",
    )
    parser.add_argument(
        "--seed-spacing",
        type=int,
        default=10_000,
        help="Gap between consecutive seed offsets (default: 10000)",
    )
    parser.add_argument(
        "--seed-start",
        type=int,
        default=0,
        help="Starting seed offset (default: 0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker count override (defaults to resolve_n_workers())",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=BASELINE_SETTINGS.n_steps,
        help=f"Simulation steps per run (default: {BASELINE_SETTINGS.n_steps})",
    )
    parser.add_argument(
        "--target-edge",
        type=float,
        default=None,
        help="Optional pass/fail threshold for mean edge (default: disabled)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    strategy_path = Path(args.strategy)
    if not strategy_path.exists():
        print(f"Error: strategy file not found: {strategy_path}")
        return 1

    source = strategy_path.read_text()

    # Validate once (faster fail loop).
    validator = SolidityValidator()
    validation = validator.validate(source)
    if not validation.valid:
        print("Validation failed:")
        for err in validation.errors:
            print(f"  - {err}")
        return 1

    # Compile once (reuse bytecode for all benchmark batches).
    compiler = SolidityCompiler()
    compilation = compiler.compile(source)
    if not compilation.success:
        print("Compilation failed:")
        for err in (compilation.errors or []):
            print(f"  - {err}")
        return 1

    # Probe strategy name once.
    strategy = EVMStrategyAdapter(
        bytecode=compilation.bytecode,
        abi=compilation.abi,
    )
    strategy_name = strategy.get_name()

    n_workers = args.workers if args.workers is not None else resolve_n_workers()
    print(f"Strategy: {strategy_name}")
    print(
        "Benchmark config: "
        f"{args.seeds} offsets x {args.sims} sims, "
        f"steps={args.steps}, workers={n_workers}"
    )

    config = amm_sim_rs.SimulationConfig(
        n_steps=args.steps,
        initial_price=BASELINE_SETTINGS.initial_price,
        initial_x=BASELINE_SETTINGS.initial_x,
        initial_y=BASELINE_SETTINGS.initial_y,
        gbm_mu=BASELINE_SETTINGS.gbm_mu,
        gbm_sigma=baseline_nominal_sigma(),
        gbm_dt=BASELINE_SETTINGS.gbm_dt,
        retail_arrival_rate=baseline_nominal_retail_rate(),
        retail_mean_size=baseline_nominal_retail_size(),
        retail_size_sigma=BASELINE_SETTINGS.retail_size_sigma,
        retail_buy_prob=BASELINE_SETTINGS.retail_buy_prob,
        seed=None,
    )
    variance = HyperparameterVariance(
        retail_mean_size_min=BASELINE_VARIANCE.retail_mean_size_min,
        retail_mean_size_max=BASELINE_VARIANCE.retail_mean_size_max,
        vary_retail_mean_size=BASELINE_VARIANCE.vary_retail_mean_size,
        retail_arrival_rate_min=BASELINE_VARIANCE.retail_arrival_rate_min,
        retail_arrival_rate_max=BASELINE_VARIANCE.retail_arrival_rate_max,
        vary_retail_arrival_rate=BASELINE_VARIANCE.vary_retail_arrival_rate,
        gbm_sigma_min=BASELINE_VARIANCE.gbm_sigma_min,
        gbm_sigma_max=BASELINE_VARIANCE.gbm_sigma_max,
        vary_gbm_sigma=BASELINE_VARIANCE.vary_gbm_sigma,
    )

    seed_offsets = [args.seed_start + i * args.seed_spacing for i in range(args.seeds)]
    scores: list[float] = []
    print(f"Seed offsets: {seed_offsets}")
    print()

    for offset in seed_offsets:
        # Fresh adapters per batch to ensure clean EVM state.
        submission = EVMStrategyAdapter(
            bytecode=compilation.bytecode,
            abi=compilation.abi,
        )
        baseline = load_vanilla_strategy()
        runner = make_runner_with_seed_offset(
            n_simulations=args.sims,
            config=config,
            n_workers=n_workers,
            variance=variance,
            seed_offset=offset,
        )
        result = runner.run_match(submission, baseline)
        edge = float(result.total_edge_a) / args.sims
        scores.append(edge)
        print(f"offset {offset:>6}: edge {edge:>8.2f}")

    mean_edge = statistics.fmean(scores)
    min_edge = min(scores)
    max_edge = max(scores)
    spread = max_edge - min_edge
    stddev = statistics.pstdev(scores) if len(scores) > 1 else 0.0

    print("\n" + "=" * 56)
    print(f"scores: {', '.join(f'{s:.2f}' for s in scores)}")
    print(f"mean:   {mean_edge:.2f}")
    print(f"min:    {min_edge:.2f}")
    print(f"max:    {max_edge:.2f}")
    print(f"spread: {spread:.2f}")
    print(f"stddev: {stddev:.2f}")
    print("=" * 56)

    if args.target_edge is None:
        return 0

    if mean_edge < args.target_edge:
        print(
            f"\nTarget miss: mean edge {mean_edge:.2f} < target {args.target_edge:.2f}"
        )
        return 2

    print(f"\nTarget met: mean edge {mean_edge:.2f} >= target {args.target_edge:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
