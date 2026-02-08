// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {IAMMStrategy, TradeInfo} from "./IAMMStrategy.sol";

/// @title Optimized AMM Fee Strategy
/// @notice Fixed 80 bps fee - empirically optimal for maximizing edge against 30 bps normalizer.
///
/// Key insight: At 80 bps, the strategy achieves optimal balance between:
/// - LVR (loss-vs-rebalancing) defense: high fee means arb is barely profitable, edge from arb ≈ 0
/// - Retail capture from heavy tail: lognormal(σ=1.2) retail orders have significant mass above the
///   routing threshold. Large orders (Y>50) still route to us despite the fee premium, and the
///   combined fee income + price impact edge from these orders dominates total edge.
///
/// Extensively tested against: dynamic vol-scaling, EWMA-based, two-mode (arb/retail switching),
/// order flow imbalance detection, inventory management, staleness-based fees.
/// None outperformed fixed 80 bps due to:
/// - Unreliable arb detection (arb trades at 80bps are tiny, indistinguishable from retail)
/// - Any time at sub-80bps fees increases LVR more than the marginal retail gain
/// - The robust optimum at 75-90 bps is flat, so dynamic adjustments add noise not signal
contract Strategy is AMMStrategyBase {
    uint256 public constant FEE = 80 * BPS;

    function afterInitialize(uint256, uint256) external pure override returns (uint256, uint256) {
        return (FEE, FEE);
    }

    function afterSwap(TradeInfo calldata) external pure override returns (uint256, uint256) {
        return (FEE, FEE);
    }

    function getName() external pure override returns (string memory) {
        return "Optimal80bps";
    }
}
