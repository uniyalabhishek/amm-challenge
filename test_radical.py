#!/usr/bin/env python3
"""Test radical structural changes and extreme parameter regimes."""

import subprocess
import os
import re

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

# StrategyFinal code
STRATEGYFINAL = """// SPDX-License-Identifier: MIT
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
        bool confirming = false;
        if (lastDir == 1 && trade.isBuy) confirming = true;
        if (lastDir == 0 && !trade.isBuy) confirming = true;
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                uint256 alpha = confirming ? 30e16 : 22e16;
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
        if (devBps <= 8) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8); }
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

# V40: Max aggressive direction - 95 bps adverse, 1 bps favorable, always asymmetric
V40_MAXASYM = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(28); slots[5] = bpsToWad(28); slots[6] = 0; slots[7] = 0;
        return (bpsToWad(28), bpsToWad(28));
    }
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 lastDir = slots[7];
        if (lastBid == 0) lastBid = bpsToWad(28);
        if (lastAsk == 0) lastAsk = bpsToWad(28);
        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;
        bool confirming = (lastDir == 1 && trade.isBuy) || (lastDir == 0 && !trade.isBuy);
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                uint256 alpha = confirming ? 30e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
            } else {
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }
        }
        uint256 newDir = spot > pHat ? 1 : 0;
        // ALWAYS asymmetric: 95 bps adverse, 1 bps favorable
        if (spot > pHat) {
            askFee = bpsToWad(1); bidFee = bpsToWad(95);
        } else {
            bidFee = bpsToWad(1); askFee = bpsToWad(95);
        }
        slots[0] = pHat; slots[3] = ts; slots[4] = bidFee; slots[5] = askFee; slots[7] = newDir;
        return (bidFee, askFee);
    }
    function getName() external pure override returns (string memory) { return "Sweep"; }
}
"""

# V41: Alpha-beta filter (Kalman-like) with drift for direction
V41_KALMAN = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {AMMStrategyBase} from "./AMMStrategyBase.sol";
import {TradeInfo} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0; slots[7] = 0;
        slots[8] = WAD; // drift estimate (1.0 = neutral, >1 = up, <1 = down)
        return (bpsToWad(15), bpsToWad(95));
    }
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6]; uint256 lastDir = slots[7];
        uint256 drift = slots[8]; if (drift == 0) drift = WAD;
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);
        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;
        bool confirming = (lastDir == 1 && trade.isBuy) || (lastDir == 0 && !trade.isBuy);
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {
                // Predict: pPred = pHat * drift
                uint256 pPred = wmul(pHat, drift);
                // Innovation: how far off we were
                // K1 = 30% (level), K2 = 5% (drift)
                uint256 alpha = confirming ? 30e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                // Update drift: if pImplied > pPred, drift should increase
                if (pImplied > pPred && pPred > 0) {
                    uint256 ratio = wdiv(pImplied, pPred);
                    drift = wmul(drift, WAD - 5e16) + wmul(ratio, 5e16);
                } else if (pPred > 0) {
                    uint256 ratio = wdiv(pImplied, pPred);
                    drift = wmul(drift, WAD - 5e16) + wmul(ratio, 5e16);
                }
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
        if (devBps <= 8) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8); }
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        // Use drift for direction instead of spot vs pHat
        uint256 newDir = drift > WAD ? 1 : 0;
        if (devBps < 8) {
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        } else if (drift > WAD) {
            askFee = favor; bidFee = adverse;
        } else {
            bidFee = favor; askFee = adverse;
        }
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir; slots[8] = drift;
        return (bidFee, askFee);
    }
    function getName() external pure override returns (string memory) { return "Sweep"; }
}
"""

# V42: Lower alpha (20/15) for more stale pHat
V42_LOWALPHA = """// SPDX-License-Identifier: MIT
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
                uint256 alpha = confirming ? 20e16 : 15e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 1e16) + wmul(pImplied, 1e16);
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
        if (devBps <= 8) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8); }
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

# V43: Very low alpha (12/8) - extremely stale pHat
V43_VLOWALPHA = V42_LOWALPHA.replace("20e16 : 15e16", "12e16 : 8e16").replace("1e16) + wmul(pImplied, 1e16", "1e16) + wmul(pImplied, 1e16")
# Fix: create properly
V43_VLOWALPHA = """// SPDX-License-Identifier: MIT
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
                uint256 alpha = confirming ? 12e16 : 8e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            } else {
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 1e16) + wmul(pImplied, 1e16);
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
        if (devBps <= 8) { favorBps = 20; }
        else if (devBps >= 50) { favorBps = 1; }
        else { favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8); }
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

results = {}
print("=" * 60)
print("RADICAL TESTS (20 sims)")
print("=" * 60)

# Reference
print("\n--- Reference ---")
results["00-StratFinal"] = run_sol(STRATEGYFINAL, "00-StratFinal")

# V40: Max asymmetric
print("\n--- Radical Directions ---")
results["V40-MaxAsym"] = run_sol(V40_MAXASYM, "V40-MaxAsym95/1")

# V41: Kalman filter
results["V41-Kalman"] = run_sol(V41_KALMAN, "V41-KalmanDrift")

# V42: Low alpha
print("\n--- Lower Alpha ---")
results["V42-LowAlpha20/15"] = run_sol(V42_LOWALPHA, "V42-Alpha20/15")
results["V43-VLowAlpha12/8"] = run_sol(V43_VLOWALPHA, "V43-Alpha12/8")

# Test with different parameter regimes
print("\n--- Regime Tests (StrategyFinal) ---")
# High vol, low retail
results["HighVol-LowRetail"] = run_sol(STRATEGYFINAL, "HighVol-LowRetail",
    extra_args=["--volatility", "0.001008", "--retail-rate", "0.6"])
# Low vol, high retail
results["LowVol-HighRetail"] = run_sol(STRATEGYFINAL, "LowVol-HighRetail",
    extra_args=["--volatility", "0.000882", "--retail-rate", "1.0"])
# Nominal
results["Nominal"] = run_sol(STRATEGYFINAL, "Nominal",
    extra_args=["--volatility", "0.000945", "--retail-rate", "0.8"])

# Also test at 30 sims (seeds 0-29 for more signal)
print("\n--- 30-sim validation ---")
results["30sim-Final"] = run_sol(STRATEGYFINAL, "30sim-Final", n_sims=30)

# 40 sims
results["40sim-Final"] = run_sol(STRATEGYFINAL, "40sim-Final", n_sims=40)

print(f"\n{'='*60}")
print("RESULTS SUMMARY")
print(f"{'='*60}")
ref = results.get("00-StratFinal", 557.00)
for name, edge in sorted(results.items(), key=lambda x: -(x[1] or 0)):
    if edge is not None:
        diff = edge - ref if ref else 0
        print(f"  {name:25s}: {edge:8.2f}  ({diff:+.2f})")
