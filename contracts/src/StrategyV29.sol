// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";

/// @title V29 - Pure symmetric strategy (no direction prediction)
/// @notice HYPOTHESIS: Asymmetric fees at ~50% direction accuracy are WORSE than
///         symmetric due to Jensen's inequality.
///         At 50% accuracy: E[arb_loss_asym] = 0.5*(d-f_lo)^2 + 0.5*(d-f_hi)^2
///         >= (d-(f_lo+f_hi)/2)^2 = E[arb_loss_sym] by Jensen.
///         Also: total spread 1+50=51 bps < 28+28=56 bps, so retail edge is higher symmetric.
///         This strategy uses ONLY symmetric fees, scaled with volatility.
///         If this scores higher than baseline, the entire direction apparatus is counter-productive.
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        uint256 initFee = bpsToWad(28);
        return (initFee, initFee);
    }

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2];

        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);

        // Base fee: 28 bps
        // Vol-scaled: add volBps * 0.5 (higher vol -> higher fees for arb protection)
        uint256 feeBps = 28 + (volBps * 5) / 10;
        if (feeBps > 60) feeBps = 60;
        if (feeBps < 25) feeBps = 25;

        uint256 fee = bpsToWad(feeBps);

        slots[1] = spot;
        slots[2] = emaAbsMove;
        slots[3] = trade.timestamp;

        bidFee = fee;
        askFee = fee;
        return (bidFee, askFee);
    }

    function getName() external pure override returns (string memory) { return "PureSym29"; }
}
