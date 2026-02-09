#!/usr/bin/env python3
"""Test volatility-adaptive threshold and other novel approaches."""

import subprocess, os, re

SOL_PATH = "/home/user/amm-challenge/contracts/src/Sweep.sol"
ENV = {**os.environ, "N_WORKERS": "1"}

def run_sol(code, label, n_sims=20, extra_args=None):
    with open(SOL_PATH, 'w') as f:
        f.write(code)
    cmd = ["amm-match", "run", SOL_PATH, "--simulations", str(n_sims)]
    if extra_args:
        cmd.extend(extra_args)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=ENV)
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

# V70: Volatility-adaptive threshold
# In high vol: larger EMA lag → larger deviations → need higher threshold to avoid false signals
# threshold = 8 + volBps / 4 (capped at 15)
V70_VOLTHR = """// SPDX-License-Identifier: MIT
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

        // Vol-adaptive threshold: higher vol → higher threshold for going directional
        uint256 dynThresh = 8 + volBps / 4;
        if (dynThresh > 15) dynThresh = 15;

        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 3;
        if (adverseBps < 40) adverseBps = 40;
        uint256 favorBps;
        if (devBps <= dynThresh) { favorBps = 18; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 18 - (devBps - dynThresh) * (18 - 1) / (50 - dynThresh); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < dynThresh) {
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

# V71: Vol-adaptive alpha AND threshold
# Higher vol → lower alpha (more lag, stronger signal needed)
# Higher vol → higher threshold
V71_VOLADAPT = """// SPDX-License-Identifier: MIT
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

        // Vol-adaptive alpha: volBps ≈ 5-15 typically
        // Base: confirm 28, contra 22, same 2
        // Adjust: lower alpha when vol is high (more lag for stronger signal)
        uint256 volBps = wadToBps(emaAbsMove);

        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                // Alpha decreases with vol: 28 - volBps/3 for confirm
                uint256 alphaC = 28;
                if (volBps > 9) {
                    uint256 adj = (volBps - 9) / 2;
                    if (adj > 6) adj = 6;
                    alphaC = 28 - adj;
                }
                uint256 alphaX = alphaC > 6 ? alphaC - 6 : alphaC;
                uint256 alpha = confirming ? alphaC * 1e16 : alphaX * 1e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        } else if (dt == 0) { if (phase < 10) phase += 1; }

        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        volBps = wadToBps(emaAbsMove);
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

# V72: Symmetric fee = favored + higher for "unsure" zone
# When devBps is 8-12 (edge of threshold), use moderate asymmetry instead of full
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

        // GRADUAL transition: blend between symmetric and directional
        if (devBps < 5) {
            // Deep symmetric zone: fully symmetric
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        } else if (devBps < 12) {
            // Transition zone: partial asymmetry
            // At dev=5: 100% symmetric. At dev=12: 100% directional.
            // weight = (devBps - 5) / 7
            uint256 symFee = bpsToWad(28);
            uint256 dirFavor = favor;
            uint256 dirAdverse = adverse;
            // Linear blend: fee = sym * (1 - w) + dir * w, where w = (devBps-5)/7
            uint256 w = (devBps - 5) * WAD / 7;
            uint256 oneMinusW = WAD - w;
            if (spot > pHat) {
                askFee = wmul(symFee, oneMinusW) + wmul(dirFavor, w);
                bidFee = wmul(symFee, oneMinusW) + wmul(dirAdverse, w);
            } else {
                bidFee = wmul(symFee, oneMinusW) + wmul(dirFavor, w);
                askFee = wmul(symFee, oneMinusW) + wmul(dirAdverse, w);
            }
        } else {
            // Full directional
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
print("VOL-ADAPTIVE THRESHOLD & GRADUAL TRANSITION TESTS")
print("=" * 60)

# Test at both default and specific regimes
tests = [
    ("CURRENT", CURRENT),
    ("V70-VolThr", V70_VOLTHR),
    ("V71-VolAdapt", V71_VOLADAPT),
    ("V72-Gradual", V72_GRADUAL),
]

results = {}
print("\n--- Default (20 sims) ---")
for name, code in tests:
    results[f"{name}/default"] = run_sol(code, f"{name}/default")

print("\n--- High Vol, Low Retail ---")
for name, code in tests:
    results[f"{name}/hvlr"] = run_sol(code, f"{name}/hvlr",
        extra_args=["--volatility", "0.001008", "--retail-rate", "0.6"])

print("\n--- Low Vol, High Retail ---")
for name, code in tests:
    results[f"{name}/lvhr"] = run_sol(code, f"{name}/lvhr",
        extra_args=["--volatility", "0.000882", "--retail-rate", "1.0"])

print(f"\n{'='*60}")
ref_d = results.get("CURRENT/default", 0) or 0
ref_h = results.get("CURRENT/hvlr", 0) or 0
ref_l = results.get("CURRENT/lvhr", 0) or 0
print(f"SUMMARY (default ref={ref_d:.1f}, hvlr ref={ref_h:.1f}, lvhr ref={ref_l:.1f})")
print(f"{'='*60}")
for name, code in tests:
    d = results.get(f"{name}/default", 0) or 0
    h = results.get(f"{name}/hvlr", 0) or 0
    l = results.get(f"{name}/lvhr", 0) or 0
    dd = d - ref_d
    dh = h - ref_h
    dl = l - ref_l
    avg_diff = (dd + dh + dl) / 3
    print(f"  {name:20s}: def={d:7.1f}({dd:+.1f}) hvlr={h:7.1f}({dh:+.1f}) lvhr={l:7.1f}({dl:+.1f}) avg={avg_diff:+.1f}")
