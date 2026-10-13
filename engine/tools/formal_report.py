#!/usr/bin/env python3
"""The reporting facts of a formal.py run (read-only).

  python3 engine/tools/formal_report.py NAME [--name jqe] [--split 2026-10-08T22:00Z]

Prints the manifest settings, the start and stop lines of match.log, the result with its reasons, the distribution
of pair scores, the final summary, the score by colour and by fifth of the run, clock use per side, and with
--split the score before and after a UTC time (for a change in host load during the run; the game count at that
time comes from the progress lines of match.log).

Only results, reasons, game lengths and move times are read. No position or move is examined, so running this on
a formal run does not break the rule that formal games must not steer development (docs/DECISIONS.md, D093).
"""
import argparse
import calendar
import json
import math
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def elo(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -400 * math.log10(1 / p - 1)


def pair_stats(games, sc):
    """Mean and standard error of the per-pair score over complete pairs."""
    pairs = {}
    for g in games:
        pairs.setdefault(g["pair"], []).append(sc(g))
    full = [sum(v) / 2 for v in pairs.values() if len(v) == 2]
    n = len(full)
    m = sum(full) / n
    se = math.sqrt(sum((x - m) ** 2 for x in full) / (n - 1) / n) if n > 1 else 0.0
    return full, m, se


def wdl(games, sc):
    return sum(sc(g) == 1 for g in games), sum(sc(g) == 0.5 for g in games), sum(sc(g) == 0 for g in games)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--name", default="jqe", help="the engine whose score is reported (default jqe)")
    ap.add_argument("--split", metavar="ISO_UTC", help="also report the score before and after this time, e.g. 2026-10-08T22:00Z")
    args = ap.parse_args()
    d = ROOT / "engine/runs" / args.run
    me = args.name

    man = json.load(open(d / "manifest.json")) if (d / "manifest.json").exists() else {}
    print("manifest:", {k: v for k, v in man.items() if not isinstance(v, (dict, list)) and k not in ("notes", "command")})
    start = None
    prog = []
    if (d / "match.log").exists():
        for line in open(d / "match.log"):
            if line.startswith("#"):
                print("  ", line.strip()[:160])
            m = re.match(r"# start (\S+)Z", line)
            if m:
                start = calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
                prog = []
            m = re.match(r"\[\s*(\d+)s\] .*?: (\d+) games", line)
            if m and start is not None:
                prog.append((start + int(m.group(1)), int(m.group(2))))

    games = [json.loads(line) for line in open(d / "games.jsonl")]
    n = len(games)
    opp = [x for x in (games[0]["red"], games[0]["black"]) if x != me][0]

    def sc(g):
        return g["result"] if g["red"] == me else 1 - g["result"]

    w, dr, lo = wdl(games, sc)
    by = {}
    for g in games:
        side = me if sc(g) == 1 else (opp if sc(g) == 0 else "nobody")
        key = f"{g['reason'].split(':')[0]} won by {side}"
        by[key] = by.get(key, 0) + 1
    print(f"games {n}: {me} +{w} ={dr} -{lo}, points {w + dr / 2:g}, score {(w + dr / 2) / n:.4f}")
    print("reasons:", dict(sorted(by.items())))
    print("time forfeits:", sum(v for k, v in by.items() if "TIME" in k or "FORFEIT" in k),
          "| void games:", sum(1 for _ in open(d / "void.jsonl")) if (d / "void.jsonl").exists() else 0)
    full, m, se = pair_stats(games, sc)
    print(f"complete pairs {len(full)}; pair scores 2 / 1.5 / 1 / 0.5 / 0:",
          " / ".join(str(sum(1 for x in full if x * 2 == t)) for t in (2, 1.5, 1, 0.5, 0)))
    if (d / "summary.json").exists():
        s = json.load(open(d / "summary.json"))
        p = s["pent"]
        print(f"FINAL summary.json: games {s['games']} score {s['score']:.4f} trinomial {s['elo']:+.1f} [{s['elo_lo']:+.1f},{s['elo_hi']:+.1f}] "
              f"pentanomial {p['elo']:+.1f} [{p['elo_lo']:+.1f},{p['elo_hi']:+.1f}] pairs {p['pairs']}; seed {s['args']['seed']}")
    else:
        print(f"no summary.json yet (interim): pair-based {elo(m):+.0f} [{elo(m - 1.96 * se):+.0f},{elo(m + 1.96 * se):+.0f}]")

    for col in ("red", "black"):
        gs = [g for g in games if g[col] == me]
        print(f"{me} as {col}: {sum(sc(g) for g in gs):g} of {len(gs)}")
    k = n // 5
    for i in range(5):
        gs = games[i * k:(i + 1) * k]
        if gs:
            p = sum(sc(g) for g in gs) / len(gs)
            print(f"games {i * k + 1}-{(i + 1) * k}: score {p:.3f} (+-{1.96 * math.sqrt(p * (1 - p) / len(gs)):.3f})")
    pl = sorted(g["plies"] for g in games)
    print("plies: mean", round(sum(pl) / n, 1), "median", pl[n // 2], "max", pl[-1])

    ck = man.get("clock", "")
    if "--tc" in ck:
        base, inc = (float(x) for x in ck.split()[-1].split("+"))
        left = {me: [], opp: []}
        used = {me: [], opp: []}
        early = {me: [], opp: []}
        for g in games:
            names = [g["red"], g["black"]]
            clock = {x: base * 1000 for x in names}
            low = dict(clock)
            cnt = {x: 0 for x in names}
            tot = {x: 0 for x in names}
            for j, mv in enumerate(g["moves"]):
                nm = names[j % 2]
                t = mv.get("t")
                if t is None:
                    continue
                clock[nm] -= t
                low[nm] = min(low[nm], clock[nm])
                clock[nm] += inc * 1000
                tot[nm] += t
                if cnt[nm] < 6:
                    early[nm].append(t)
                cnt[nm] += 1
            for nm in names:
                left[nm].append(low[nm] / 1000)
                used[nm].append(tot[nm] / 1000)
        for nm in (me, opp):
            u = sorted(used[nm])
            lw = sorted(left[nm])
            print(f"{nm}: clock used per game mean {sum(u) / len(u):.1f} s (median {u[len(u) // 2]:.1f}); lowest clock reached: "
                  f"min {lw[0]:.2f} s, 1st percentile {lw[len(lw) // 100]:.2f} s, median {lw[len(lw) // 2]:.1f} s; "
                  f"mean of own moves 1-6: {sum(early[nm]) / len(early[nm]) / 1000:.2f} s")

    if args.split:
        cut_t = calendar.timegm(time.strptime(args.split, "%Y-%m-%dT%H:%MZ"))
        before = [c for t, c in prog if t <= cut_t]
        ncut = (before[-1] if before else 0) // 2 * 2
        print(f"split at {args.split}: {ncut} games on record by then (progress lines after the last start)")
        if 0 < ncut < n:
            res = []
            for gs, label in ((games[:ncut], f"games 1-{ncut} (before)"), (games[ncut:], f"games {ncut + 1}-{n} (after)")):
                full, m, se = pair_stats(gs, sc)
                a, b, c = wdl(gs, sc)
                print(f"{label}: +{a} ={b} -{c}, score {m:.4f} over {len(full)} pairs (se {se:.4f}), "
                      f"elo {elo(m):+.0f} [{elo(m - 1.96 * se):+.0f},{elo(m + 1.96 * se):+.0f}]")
                res.append((m, se))
            z = (res[0][0] - res[1][0]) / math.sqrt(res[0][1] ** 2 + res[1][1] ** 2)
            print(f"difference in score {res[0][0] - res[1][0]:+.4f}, z {z:+.2f}, two-sided p {math.erfc(abs(z) / math.sqrt(2)):.2f}")


if __name__ == "__main__":
    main()
