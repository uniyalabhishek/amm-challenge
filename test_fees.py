#!/usr/bin/env python3
"""Test higher fee levels and curve shapes."""

import subprocess
import os
import re

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
    except Exception as e:
        print(f"  {label}: ERROR {e}")
    return None

TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";
contract Strategy is AMMStrategyBase {{
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {{
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(28); slots[5] = bpsToWad(28); slots[6] = 0; slots[7] = 0;
        return (bpsToWad(28), bpsToWad(28));
    }}
    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {{
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6]; uint256 lastDir = slots[7];
        if (lastBid == 0) lastBid = bpsToWad(28);
        if (lastAsk == 0) lastAsk = bpsToWad(28);
        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;
        bool confirming = false;
        if (lastDir == 1 && trade.isBuy) confirming = true;
        if (lastDir == 0 && !trade.isBuy) confirming = true;
        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {{
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {{
                uint256 alpha = confirming ? 30e16 : 22e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            }} else {{
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - 2e16) + wmul(pImplied, 2e16);
            }}
        }} else if (dt == 0) {{ if (phase < 10) phase += 1; }}
        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        // Adverse fee calculation
        uint256 adverseBps = (devBps * {dev_coeff}) / 10 + (volBps * {vol_coeff}) / 10;
        if (dt > 0) adverseBps += {boost};
        if (adverseBps < {adv_floor}) adverseBps = {adv_floor};

        // Favorable fee calculation
        uint256 favorBps;
        if (devBps <= {threshold}) {{ favorBps = {fav_top}; }}
        else if (devBps >= 50) {{ favorBps = {fav_bottom}; }}
        else {{ favorBps = {fav_top} - (devBps - {threshold}) * ({fav_top} - {fav_bottom}) / (50 - {threshold}); }}

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;
        if (devBps < {threshold}) {{
            bidFee = bpsToWad({sym_fee}); askFee = bpsToWad({sym_fee});
        }} else if (spot > pHat) {{
            askFee = favor; bidFee = adverse;
        }} else {{
            bidFee = favor; askFee = adverse;
        }}
        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }}
    function getName() external pure override returns (string memory) {{ return "Sweep"; }}
}}
"""

DEFAULTS = dict(
    dev_coeff=7, vol_coeff=12, boost=3, adv_floor=40,
    threshold=8, sym_fee=28, fav_top=20, fav_bottom=1,
)

def run_params(label, **kwargs):
    p = dict(DEFAULTS, **kwargs)
    return run_sol(TEMPLATE.format(**p), label)

results = {}
print("=" * 60)
print("FEE LEVEL OPTIMIZATION (20 sims)")
print("=" * 60)

# Reference
print("\n--- Reference ---")
results["00-Current"] = run_params("00-Current")

# Test higher adverse floors
print("\n--- Higher Adverse Floor ---")
for floor in [45, 50, 55, 60, 70, 80]:
    results[f"AF-{floor}"] = run_params(f"AdvFloor={floor}", adv_floor=floor)

# Test higher symmetric fee
print("\n--- Higher Symmetric Fee ---")
for sf in [30, 32, 35, 40, 45]:
    results[f"SF-{sf}"] = run_params(f"SymFee={sf}", sym_fee=sf)

# Test higher adverse + higher symmetric together
print("\n--- Combined Higher Fees ---")
for af, sf in [(50, 32), (50, 35), (55, 35), (60, 35), (60, 40), (50, 40)]:
    results[f"AF{af}-SF{sf}"] = run_params(f"AF{af}+SF{sf}", adv_floor=af, sym_fee=sf)

# Test different favorable ranges
print("\n--- Favorable Fee Ranges ---")
for ft, fb in [(25, 1), (25, 3), (15, 1), (20, 3), (20, 5), (20, 10)]:
    results[f"FT{ft}-FB{fb}"] = run_params(f"Fav{ft}to{fb}", fav_top=ft, fav_bottom=fb)

# Test different adverse scaling
print("\n--- Adverse Scaling ---")
for dc, vc in [(5, 12), (7, 15), (9, 12), (7, 8), (10, 12), (7, 18)]:
    results[f"DC{dc}-VC{vc}"] = run_params(f"DevC{dc}+VolC{vc}", dev_coeff=dc, vol_coeff=vc)

# Test higher boost
print("\n--- Boost ---")
for b in [0, 2, 5, 8, 10]:
    results[f"B-{b}"] = run_params(f"Boost={b}", boost=b)

# Test thresholds
print("\n--- Threshold ---")
for t in [4, 6, 10, 12, 15]:
    results[f"T-{t}"] = run_params(f"Thresh={t}", threshold=t)

print(f"\n{'='*60}")
print("RESULTS SUMMARY (reference: 00-Current = 557.00)")
print(f"{'='*60}")
ref = results.get("00-Current", 557.00)
for name, edge in sorted(results.items(), key=lambda x: -(x[1] or 0)):
    if edge is not None:
        diff = edge - ref if ref else 0
        marker = " ***" if diff > 0.5 else ""
        print(f"  {name:20s}: {edge:8.2f}  ({diff:+.2f}){marker}")
    else:
        print(f"  {name:20s}: FAILED")
