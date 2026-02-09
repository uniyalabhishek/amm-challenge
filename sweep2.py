"""Focused sweep on direction-adaptive alpha and same-step EMA."""
import subprocess
import re
import os

TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {{
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0;
        slots[7] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {{
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6];
        uint256 lastDir = slots[7];
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        bool confirming = false;
        if (lastDir == 1 && trade.isBuy) confirming = true;
        if (lastDir == 0 && !trade.isBuy) confirming = true;

        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {{
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {{
                uint256 alpha = confirming ? {alpha_confirm}e16 : {alpha_contra}e16;
                pHat = wmul(pHat, WAD - alpha) + wmul(pImplied, alpha);
                phase = 0;
            }} else {{
                if (phase < 10) phase += 1;
                pHat = wmul(pHat, WAD - {alpha_same}e16) + wmul(pImplied, {alpha_same}e16);
            }}
        }} else if (dt == 0) {{ if (phase < 10) phase += 1; }}

        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        uint256 adverseBps = (devBps * 7) / 10 + (volBps * 12) / 10;
        if (dt > 0) adverseBps += 4;
        if (adverseBps < 38) adverseBps = 38;

        uint256 favorBps;
        if (devBps <= 8) {{ favorBps = 20; }}
        else if (devBps >= 50) {{ favorBps = 1; }}
        else {{ favorBps = 20 - (devBps - 8) * (20 - 1) / (50 - 8); }}

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));
        uint256 newDir = spot > pHat ? 1 : 0;

        if (devBps < 8) {{ bidFee = bpsToWad(28); askFee = bpsToWad(28); }}
        else if (spot > pHat) {{ askFee = favor; bidFee = adverse; }}
        else {{ bidFee = favor; askFee = adverse; }}

        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee;
        slots[6] = phase; slots[7] = newDir;
        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{ return "Sweep2"; }}
}}
'''

def run_strategy(params, n_sims=500):
    source = TEMPLATE.format(**params)
    path = "/home/user/amm-challenge/contracts/src/Sweep.sol"
    with open(path, "w") as f:
        f.write(source)

    env = os.environ.copy()
    env["N_WORKERS"] = "1"
    result = subprocess.run(
        ["amm-match", "run", path, "--simulations", str(n_sims)],
        capture_output=True, text=True, timeout=600, env=env
    )
    output = result.stdout + result.stderr
    match = re.search(r"Edge:\s+([\d.]+)", output)
    return float(match.group(1)) if match else None

configs = [
    # Baseline (no direction-adaptive)
    {"alpha_confirm": 25, "alpha_contra": 25, "alpha_same": 1},
    # V13 original
    {"alpha_confirm": 28, "alpha_contra": 22, "alpha_same": 1},
    {"alpha_confirm": 28, "alpha_contra": 22, "alpha_same": 2},
    # Wider spread
    {"alpha_confirm": 30, "alpha_contra": 20, "alpha_same": 1},
    {"alpha_confirm": 30, "alpha_contra": 20, "alpha_same": 2},
    # Even wider
    {"alpha_confirm": 32, "alpha_contra": 18, "alpha_same": 1},
    {"alpha_confirm": 32, "alpha_contra": 18, "alpha_same": 2},
    # Moderate
    {"alpha_confirm": 27, "alpha_contra": 23, "alpha_same": 1},
    {"alpha_confirm": 27, "alpha_contra": 23, "alpha_same": 2},
    # Asymmetric: much stronger on confirm
    {"alpha_confirm": 35, "alpha_contra": 20, "alpha_same": 1},
    # Confirm only (no change on contra)
    {"alpha_confirm": 30, "alpha_contra": 25, "alpha_same": 1},
    {"alpha_confirm": 28, "alpha_contra": 25, "alpha_same": 2},
]

if __name__ == "__main__":
    results = []
    for i, cfg in enumerate(configs):
        score = run_strategy(cfg)
        desc = f"confirm={cfg['alpha_confirm']} contra={cfg['alpha_contra']} same={cfg['alpha_same']}"
        if score:
            results.append((score, desc))
            print(f"[{i+1}/{len(configs)}] Edge: {score:.2f} | {desc}")
        else:
            print(f"[{i+1}/{len(configs)}] FAILED | {desc}")
    print("\n=== SORTED ===")
    for s, d in sorted(results, reverse=True):
        print(f"  {s:.2f} | {d}")
