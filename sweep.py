"""Parameter sweep for AMM strategy optimization."""
import subprocess
import re
import os
import itertools

TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {{AMMStrategyBase}} from "./AMMStrategyBase.sol";
import {{TradeInfo}} from "./IAMMStrategy.sol";

contract Strategy is AMMStrategyBase {{
    function afterInitialize(uint256 initialX, uint256 initialY) external override returns (uint256, uint256) {{
        uint256 spot = initialX == 0 ? 0 : wdiv(initialY, initialX);
        slots[0] = spot; slots[1] = spot; slots[2] = 0; slots[3] = 0;
        slots[4] = bpsToWad(15); slots[5] = bpsToWad(95); slots[6] = 0;
        return (bpsToWad(15), bpsToWad(95));
    }}

    function afterSwap(TradeInfo calldata trade) external override returns (uint256 bidFee, uint256 askFee) {{
        uint256 spot = trade.reserveX == 0 ? 0 : wdiv(trade.reserveY, trade.reserveX);
        uint256 pHat = slots[0]; if (pHat == 0) pHat = spot;
        uint256 prevSpot = slots[1]; if (prevSpot == 0) prevSpot = spot;
        uint256 emaAbsMove = slots[2]; uint256 lastTs = slots[3];
        uint256 lastBid = slots[4]; uint256 lastAsk = slots[5];
        uint256 phase = slots[6];
        if (lastBid == 0) lastBid = bpsToWad(15);
        if (lastAsk == 0) lastAsk = bpsToWad(95);

        uint256 ts = trade.timestamp;
        uint256 dt = ts > lastTs ? (ts - lastTs) : 0;

        uint256 gamma = trade.isBuy ? (WAD - lastBid) : (WAD - lastAsk);
        if (gamma != 0) {{
            uint256 pImplied = trade.isBuy ? wmul(spot, gamma) : wdiv(spot, gamma);
            if (dt > 0) {{ pHat = wmul(pHat, WAD - {ema_new}e16) + wmul(pImplied, {ema_new}e16); phase = 0; }}
            else {{ if (phase < 10) phase += 1; pHat = wmul(pHat, WAD - {ema_same}e16) + wmul(pImplied, {ema_same}e16); }}
        }} else if (dt == 0) {{ if (phase < 10) phase += 1; }}

        uint256 absMove = prevSpot == 0 ? 0 : wdiv(absDiff(spot, prevSpot), prevSpot);
        emaAbsMove = wmul(emaAbsMove, WAD - 2e17) + wmul(absMove, 2e17);
        uint256 volBps = wadToBps(emaAbsMove);
        uint256 relDev = pHat == 0 ? 0 : wdiv(absDiff(spot, pHat), pHat);
        uint256 devBps = wadToBps(relDev);

        uint256 adverseBps = (devBps * {adv_dev}) / 10 + (volBps * {adv_vol}) / 10;
        if (dt > 0) adverseBps += {newstep_boost};
        if (adverseBps < {adv_floor}) adverseBps = {adv_floor};

        uint256 favorBps;
        if (devBps <= {sym_thresh}) {{ favorBps = {fav_high}; }}
        else if (devBps >= 50) {{ favorBps = {fav_low}; }}
        else {{ favorBps = {fav_high} - (devBps - {sym_thresh}) * ({fav_high} - {fav_low}) / (50 - {sym_thresh}); }}

        uint256 favor = bpsToWad(favorBps);
        uint256 adverse = clampFee(bpsToWad(adverseBps));

        if (devBps < {sym_thresh}) {{
            bidFee = bpsToWad({sym_fee});
            askFee = bpsToWad({sym_fee});
        }} else if (spot > pHat) {{
            askFee = favor;
            bidFee = adverse;
        }} else {{
            bidFee = favor;
            askFee = adverse;
        }}

        slots[0] = pHat; slots[1] = spot; slots[2] = emaAbsMove;
        slots[3] = ts; slots[4] = bidFee; slots[5] = askFee; slots[6] = phase;
        return (bidFee, askFee);
    }}

    function getName() external pure override returns (string memory) {{ return "Sweep"; }}
}}
'''

def run_strategy(params, n_sims=200):
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
    if match:
        return float(match.group(1))
    return None

# Parameter grid
configs = [
    # Baseline reference
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    # EMA variations
    {"ema_new": 22, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 2, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 3, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    # Adverse fee variations
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 5, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 36, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 40, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 8, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 13, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    # Symmetric zone variations
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 7, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 9, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 27},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 29},
    # Favorable fee variations
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 22, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 18, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 1, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 38, "fav_high": 20, "fav_low": 2, "sym_thresh": 8, "sym_fee": 28},
    # Promising combos
    {"ema_new": 25, "ema_same": 2, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 5, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 2, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 4, "adv_floor": 36, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 27},
    {"ema_new": 22, "ema_same": 2, "adv_dev": 7, "adv_vol": 12, "newstep_boost": 5, "adv_floor": 38, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 28},
    {"ema_new": 25, "ema_same": 2, "adv_dev": 7, "adv_vol": 13, "newstep_boost": 5, "adv_floor": 36, "fav_high": 20, "fav_low": 1, "sym_thresh": 8, "sym_fee": 27},
]

if __name__ == "__main__":
    results = []
    for i, cfg in enumerate(configs):
        score = run_strategy(cfg, n_sims=200)
        key_params = f"ema={cfg['ema_new']}/{cfg['ema_same']} adv={cfg['adv_floor']}+{cfg['newstep_boost']} dev*{cfg['adv_dev']}/10+vol*{cfg['adv_vol']}/10 fav={cfg['fav_low']}-{cfg['fav_high']} sym<{cfg['sym_thresh']}@{cfg['sym_fee']}"
        if score:
            results.append((score, key_params, cfg))
            print(f"[{i+1}/{len(configs)}] Edge: {score:.2f} | {key_params}")
        else:
            print(f"[{i+1}/{len(configs)}] FAILED | {key_params}")

    print("\n=== SORTED RESULTS ===")
    results.sort(key=lambda x: x[0], reverse=True)
    for score, params, cfg in results:
        print(f"  {score:.2f} | {params}")
