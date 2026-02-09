#!/usr/bin/env python3
"""Test critical hypotheses about the AMM strategy."""

import subprocess
import os
import re
import sys

SOL_PATH = "/home/user/amm-challenge/contracts/src/Sweep.sol"
N_SIMS = 20
ENV = {**os.environ, "N_WORKERS": "1"}

def run_sol(code, label):
    with open(SOL_PATH, 'w') as f:
        f.write(code)
    try:
        out = subprocess.run(
            ["amm-match", "run", SOL_PATH, "--simulations", str(N_SIMS)],
            capture_output=True, text=True, timeout=90, env=ENV
        )
        output = out.stdout + out.stderr
        for line in output.split('\n'):
            m = re.search(r'Edge:\s+([\d.-]+)', line)
            if m:
                val = float(m.group(1))
                if val > -500 and val < 1000:
                    print(f"  {label}: {val:.2f}")
                    return val
        print(f"  {label}: PARSE FAIL")
        print(f"  Output: {output[-300:]}")
    except Exception as e:
        print(f"  {label}: ERROR {e}")
    return None

# BASE TEMPLATE (StrategyFinal params)
BASE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {{
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {{
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad({init_bid}); slots[5] = bpsToWad({init_ask}); slots[6] = 0; slots[7] = 0;
        return (bpsToWad({init_bid}), bpsToWad({init_ask}));
    }}
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {{
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6]; uint256 lastDir = slots[7];
        if (lastBid == 0) lastBid = bpsToWad({init_bid});
        if (lastAsk == 0) lastAsk = bpsToWad({init_ask});
        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;
        bool confirming = false;
        if (lastDir == 1 && trade.isBuy) confirming = true;
        if (lastDir == 0 && !trade.isBuy) confirming = true;
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {{
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {{
                uint256 alpha = confirming ? {alpha_c}e16 : {alpha_t}e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            }} else {{
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - {alpha_s}e16) + wmul(pImplied, {alpha_s}e16);
            }}
        }} else if (dt == 0) {{ if (phase < 10) phase += 1; }}
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);
        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += {boost};
        if (adverseBps < {adv_floor}) adverseBps = {adv_floor};
        uint256 favorBps;
        if (devBps <= {threshold}) {{ favorBps = 20; }}
        else if (devBps >= 50) {{ favorBps = 1; }}
        else {{ favorBps = 20 - (devBps - {threshold}) * (20 - 1) / (50 - {threshold}); }}
        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        {direction_logic}
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }}
    function getName() external pure override returns (string memory) {{ return "Sweep"; }}
}}
"""

# Default params (StrategyFinal)
DEFAULTS = dict(
    init_bid=15, init_ask=95,
    alpha_c=30, alpha_t=22, alpha_s=2,
    boost=3, adv_floor=40, threshold=8,
)

# NORMAL direction (current)
NORMAL_DIR = """
        if (devBps < {threshold}) {{
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        }} else if (spot > pHat) {{
            askFee = favor; bidFee = adverse;
        }} else {{
            bidFee = favor; askFee = adverse;
        }}
""".format(**DEFAULTS)

# REVERSED direction
REVERSED_DIR = """
        if (devBps < {threshold}) {{
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        }} else if (spot > pHat) {{
            bidFee = favor; askFee = adverse;
        }} else {{
            askFee = favor; bidFee = adverse;
        }}
""".format(**DEFAULTS)

# ALWAYS symmetric 28 bps
SYM28 = """
        bidFee = bpsToWad(28); askFee = bpsToWad(28);
"""

# ALWAYS symmetric 40 bps
SYM40 = """
        bidFee = bpsToWad(40); askFee = bpsToWad(40);
"""

# ALWAYS symmetric 50 bps
SYM50 = """
        bidFee = bpsToWad(50); askFee = bpsToWad(50);
"""

# ALWAYS symmetric 60 bps
SYM60 = """
        bidFee = bpsToWad(60); askFee = bpsToWad(60);
"""

# Normal direction but with higher favorable fee (15-20 bps instead of 1-20)
HIGH_FAVOR_DIR = """
        uint256 hiAdverse = clampFee(bpsToWad(adverseBps));
        uint256 hiFavor;
        if (devBps <= 8) {{ hiFavor = bpsToWad(20); }}
        else if (devBps >= 50) {{ hiFavor = bpsToWad(15); }}
        else {{ hiFavor = bpsToWad(20 - (devBps - 8) * (20 - 15) / (50 - 8)); }}
        if (devBps < 8) {{
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        }} else if (spot > pHat) {{
            askFee = hiFavor; bidFee = hiAdverse;
        }} else {{
            bidFee = hiFavor; askFee = hiAdverse;
        }}
"""

# Normal direction with VERY low favorable (always 1 bps)
LOW_FAVOR_DIR = """
        if (devBps < {threshold}) {{
            bidFee = bpsToWad(28); askFee = bpsToWad(28);
        }} else if (spot > pHat) {{
            askFee = bpsToWad(1); bidFee = adverse;
        }} else {{
            bidFee = bpsToWad(1); askFee = adverse;
        }}
""".format(**DEFAULTS)

results = {}
print("=" * 60)
print("CRITICAL HYPOTHESIS TESTS (20 sims)")
print("=" * 60)

# Test 1: Normal direction (reference)
print("\n--- Direction Tests ---")
p = dict(DEFAULTS, direction_logic=NORMAL_DIR)
results["01-Normal"] = run_sol(BASE.format(**p), "01-NormalDir")

# Test 2: REVERSED direction
p = dict(DEFAULTS, direction_logic=REVERSED_DIR)
results["02-Reversed"] = run_sol(BASE.format(**p), "02-ReversedDir")

# Test 3-6: Symmetric fees (no direction)
print("\n--- Symmetric Fee Tests ---")
for name, logic in [("03-Sym28", SYM28), ("04-Sym40", SYM40), ("05-Sym50", SYM50), ("06-Sym60", SYM60)]:
    p = dict(DEFAULTS, direction_logic=logic)
    results[name] = run_sol(BASE.format(**p), name)

# Test 7: Higher favorable fee
print("\n--- Favorable Fee Tests ---")
p = dict(DEFAULTS, direction_logic=HIGH_FAVOR_DIR)
results["07-HighFavor15"] = run_sol(BASE.format(**p), "07-HighFavor15")

# Test 8: Very low favorable
p = dict(DEFAULTS, direction_logic=LOW_FAVOR_DIR)
results["08-LowFavor1"] = run_sol(BASE.format(**p), "08-LowFavor1")

# Test 9: Very high alpha (50% confirming, 35% contra)
print("\n--- Alpha Tests ---")
p = dict(DEFAULTS, alpha_c=50, alpha_t=35, alpha_s=2, direction_logic=NORMAL_DIR)
results["09-HighAlpha"] = run_sol(BASE.format(**p), "09-HighAlpha50/35")

# Test 10: Very aggressive alpha (70/50)
p = dict(DEFAULTS, alpha_c=70, alpha_t=50, alpha_s=2, direction_logic=NORMAL_DIR)
results["10-VeryHighAlpha"] = run_sol(BASE.format(**p), "10-VeryHighAlpha70/50")

# Test 11: Alpha same = 0 (no retail pHat update)
print("\n--- Alpha Same Tests ---")
NOSAME_DIR = NORMAL_DIR
p = dict(DEFAULTS, alpha_s=0, direction_logic=NOSAME_DIR)
# Can't use alpha_s=0 because it would mean no update. Need to handle this differently.
# Actually with alpha_s=0, the pHat update for same-step would be: pHat = pHat*1 + pImplied*0 = pHat. Fine.
# But in solidity 0e16 = 0, and wmul(pHat, WAD - 0) = pHat. wmul(pImplied, 0) = 0. OK.
results["11-NoSameAlpha"] = run_sol(BASE.format(**p), "11-NoSameAlpha")

# Test 12: Alpha same = 5 (more retail pHat update)
p = dict(DEFAULTS, alpha_s=5, direction_logic=NORMAL_DIR)
results["12-HighSameAlpha5"] = run_sol(BASE.format(**p), "12-HighSameAlpha5")

# Test 13: Symmetric 28 init (instead of 15/95)
print("\n--- Init Tests ---")
p = dict(DEFAULTS, init_bid=28, init_ask=28, direction_logic=NORMAL_DIR)
results["13-SymInit28"] = run_sol(BASE.format(**p), "13-SymInit28/28")

# Test 14: Symmetric 40 init
p = dict(DEFAULTS, init_bid=40, init_ask=40, direction_logic=NORMAL_DIR)
results["14-SymInit40"] = run_sol(BASE.format(**p), "14-SymInit40/40")

# Test 15: Adverse direction init (95/15 instead of 15/95)
p = dict(DEFAULTS, init_bid=95, init_ask=15, direction_logic=NORMAL_DIR)
results["15-FlipInit95/15"] = run_sol(BASE.format(**p), "15-FlipInit95/15")

print(f"\n{'='*60}")
print("RESULTS SUMMARY (reference: 01-Normal ~ 557.00)")
print(f"{'='*60}")
ref = results.get("01-Normal", 557.00)
for name, edge in sorted(results.items()):
    if edge is not None:
        diff = edge - ref if ref else 0
        print(f"  {name:25s}: {edge:8.2f}  ({diff:+.2f})")
    else:
        print(f"  {name:25s}: FAILED")
