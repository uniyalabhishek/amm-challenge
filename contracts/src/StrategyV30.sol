// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V30 - Pure symmetric 30 bps (constant)
/// @notice Simplest possible strategy: always charge 30 bps symmetric.
///         Same as Vanilla competitor. If the baseline can't beat this baseline test,
///         the direction prediction is actually harmful.
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 fee = bpsToWad(30);
        return (fee, fee);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 fee = bpsToWad(30);
        return (fee, fee);
    }

    function getName() external pure override returns (string memory) { return "ConstSym30"; }
}
