#!/usr/bin/env python3
"""Final comparison: current vs V72-Gradual vs phase-escalating fees."""

import subprocess, os, re

SOL_PATH = "/home/user/amm-challenge/contracts/src/Sweep.sol"
ENV = {**os.environ, "N_WORKERS": "1"}

def run_sol(code, label, n_sims=30):
    with open(SOL_PATH, 'w') as f:
        f.write(code)
    try:
        out = subprocess.run(
            ["amm-match", "run", SOL_PATH, "--simulations", str(n_sims)],
            capture_output=True, text=True, timeout=180, env=ENV
        )
        output = out.stdout + out.stderr
        for line in output.split('\n'):
            m = re.search(r'Edge:\s+([\d.-]+)', line)
            if m:
                val = float(m.group(1))
                if val > -500 and val < 1500:
                    print(f"  {label}: {val:.2f}")
                    return val
        print(f"  {label}: PARSE FAIL")
    except Exception as e:
        print(f"  {label}: ERROR {e}")
    return None

CURRENT = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0; slots[7] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
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
        bool confirming = (lastDir == 1 && trade.isBuy) || (lastDir == 0 && !trade.isBuy);
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                uint256 alpha = confirming ? 28e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) { if (phase < 10) phase += 1; }
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < 40) adverseBps = 40;
        uint256 favorBps;
        if (devBps <= 8) { favorBps = 18; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 18 - (devBps - 8) * (18 - 1) / (50 - 8); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < 8) {
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        } else if (spot > pHat) {
            askFee = favor; bidFee = adverse;
        } else {
            bidFee = favor; askFee = adverse;
        }
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }
    function getName() external pure override returns (string memory) { return "Sweep"; }
}
"""

# V72-Gradual: smooth transition between symmetric and directional
V72_GRADUAL = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0; slots[7] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
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
        bool confirming = (lastDir == 1 && trade.isBuy) || (lastDir == 0 && !trade.isBuy);
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                uint256 alpha = confirming ? 28e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) { if (phase < 10) phase += 1; }
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < 40) adverseBps = 40;
        uint256 favorBps;
        if (devBps <= 8) { favorBps = 18; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 18 - (devBps - 8) * (18 - 1) / (50 - 8); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < 5) {
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        } else if (devBps < 12) {
            uint256 symFee = bpsToWad(28);
            uint256 w = (devBps - 5) * WAD / 7;
            uint256 oneMinusW = WAD - w;
            if (spot > pHat) {
                askFee = wmul(symFee, oneMinusW) + wmul(favor, w);
                bidFee = wmul(symFee, oneMinusW) + wmul(adverse, w);
            } else {
                bidFee = wmul(symFee, oneMinusW) + wmul(favor, w);
                askFee = wmul(symFee, oneMinusW) + wmul(adverse, w);
            }
        } else {
            if (spot > pHat) {
                askFee = favor; bidFee = adverse;
            } else {
                bidFee = favor; askFee = adverse;
            }
        }
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }
    function getName() external pure override returns (string memory) { return "Sweep"; }
}
"""

# V73: Phase-escalating favorable fee
# After arb (phase=0): set normal directional fees
# After each retail trade: slightly increase favorable fee toward symmetric
# This provides better arb protection if the next trade is next step's arb
V73_PHASE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0; slots[7] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
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
        bool confirming = (lastDir == 1 && trade.isBuy) || (lastDir == 0 && !trade.isBuy);
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                uint256 alpha = confirming ? 28e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) { if (phase < 10) phase += 1; }
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < 40) adverseBps = 40;
        uint256 favorBps;
        if (devBps <= 8) { favorBps = 18; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 18 - (devBps - 8) * (18 - 1) / (50 - 8); }
        // Phase escalation: after each retail trade, move favor toward sym fee
        // This provides better arb protection for the NEXT step's arb
        // phase 0 (after arb): normal favor
        // phase 1+: blend toward symmetric
        if (phase > 0 && favorBps < 28) {
            // Move favor 3 bps per phase toward 28
            uint256 escalation = phase * 3;
            if (favorBps + escalation > 28) {
                favorBps = 28;
            } else {
                favorBps = favorBps + escalation;
            }
        }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < 8) {
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        } else if (spot > pHat) {
            askFee = favor; bidFee = adverse;
        } else {
            bidFee = favor; askFee = adverse;
        }
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }
    function getName() external pure override returns (string memory) { return "Sweep"; }
}
"""

# V74: Combine gradual + phase escalation
V74_COMBO = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0; slots[7] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
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
        bool confirming = (lastDir == 1 && trade.isBuy) || (lastDir == 0 && !trade.isBuy);
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                uint256 alpha = confirming ? 28e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) { if (phase < 10) phase += 1; }
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < 40) adverseBps = 40;
        uint256 favorBps;
        if (devBps <= 8) { favorBps = 18; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 18 - (devBps - 8) * (18 - 1) / (50 - 8); }
        // Phase escalation: after retail trades, nudge favor toward symmetric
        if (phase > 0 && favorBps < 28) {
            uint256 escalation = phase * 2;
            if (favorBps + escalation > 28) favorBps = 28;
            else favorBps = favorBps + escalation;
        }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        // Gradual transition
        if (devBps < 5) {
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        } else if (devBps < 12) {
            uint256 symFee = bpsToWad(28);
            uint256 w = (devBps - 5) * WAD / 7;
            uint256 oneMinusW = WAD - w;
            if (spot > pHat) {
                askFee = wmul(symFee, oneMinusW) + wmul(favor, w);
                bidFee = wmul(symFee, oneMinusW) + wmul(adverse, w);
            } else {
                bidFee = wmul(symFee, oneMinusW) + wmul(favor, w);
                askFee = wmul(symFee, oneMinusW) + wmul(adverse, w);
            }
        } else {
            if (spot > pHat) {
                askFee = favor; bidFee = adverse;
            } else {
                bidFee = favor; askFee = adverse;
            }
        }
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }
    function getName() external pure override returns (string memory) { return "Sweep"; }
}
"""

print("=" * 60)
print("FINAL COMPARISON (30 sims, 3 trials each)")
print("=" * 60)

tests = [
    ("CURRENT", CURRENT),
    ("V72-Gradual", V72_GRADUAL),
    ("V73-Phase", V73_PHASE),
    ("V74-Combo", V74_COMBO),
]

all_results = {name: [] for name, _ in tests}
for trial in range(3):
    print(f"\n--- Trial {trial+1} ---")
    for name, code in tests:
        edge = run_sol(code, f"{name}/t{trial+1}", n_sims=30)
        if edge:
            all_results[name].append(edge)

print(f"\n{'='*60}")
print("AVERAGE RESULTS")
print(f"{'='*60}")
ref_avg = sum(all_results["CURRENT"]) / len(all_results["CURRENT"]) if all_results["CURRENT"] else 0
for name, edges in all_results.items():
    if edges:
        avg = sum(edges) / len(edges)
        diff = avg - ref_avg
        print(f"  {name:20s}: {avg:8.2f}  ({diff:+.2f})  [{', '.join(f'{e:.1f}' for e in edges)}]")
