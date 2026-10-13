#!/usr/bin/env python3
"""Recompute every result in results/ from its game records, and check the deals the games were played on.

    python3 tools/check_results.py              # check every run and print the tables
    python3 tools/check_results.py --write      # also write the table of the formal runs into README.md
    python3 tools/check_results.py --check      # also fail if README.md's table or a stated sentence is out of date
    python3 tools/check_results.py --replay     # also replay every game through the native referee

Python 3.11 or later, standard library only (--replay also needs the native library, see docs/NATIVE.md).

For every run under results/ (formal/, longclock/, exploiter/) the script reads games.jsonl.gz and
recomputes the games, wins, draws and losses, the score, the counts of the five pair scores, the Elo
difference and its 95% intervals with the formulas of engine/tools/match.py: trinomial over games and
pentanomial over complete colour-swapped pairs, both with population variance, z = 1.96 and
elo(s) = -400 log10(1/s - 1). Where the run has a summary.json, the counts must agree exactly and the
intervals to 1e-6. It regenerates every deal with jieqi/setup.py from the pair seeds of the run's deal
book (random.Random(SEED).getrandbits(63), one per pair) and checks every recorded reveal and captured
identity against it, and checks that each result agrees with its reason. For the formal runs it also
checks the manifest (the held-out book, the engine and net hashes, the settings) and that match.log
ends with `# exit 0`; for the exploiter runs, the test's state file. --replay plays each game's moves
through the native referee and checks that it ends where the record says (JIEQI_NATIVE_LIBRARY, default
build/release/lib/libjieqi_rules.so).

The table of formal runs goes into README.md between `<!-- results:begin -->` and `<!-- results:end -->`,
and a shorter one into REPORT.md between `<!-- report-results:begin -->` and `<!-- report-results:end -->`.
stated() rebuilds, from the recomputed numbers, every sentence of README.md and REPORT.md that quotes
them; --check fails if either table is out of date or if any of those sentences is not found word for
word (spacing and line breaks aside) in one of the two files. The exit status is 1 if any check fails.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jieqi.setup import Color, Kind, Setup, square  # noqa: E402

RESULTS = ROOT / "results"
README = ROOT / "README.md"
REPORT = ROOT / "REPORT.md"
Z = 1.96


def book_seed(phrase: str) -> int:
    """The deal-book seed of engine/tools/formal.py and engine/train/exploit.py."""
    return int(hashlib.sha256(phrase.encode()).hexdigest()[:12], 16)


FORMAL_PHRASE = "jqe formal deal book 1"
FORMAL_SEED = 72335360501015
JQE_SHA256 = "d382bce0685847547ee8bda2ce9a257ca1cdfab6f0c60fa4ef8fd4bcbd95c03d"  # engine/bin/jqe-v0.15g, every run
NET = ROOT / "engine/nets/it014.jqn"
# Deals of jieqi/setup.py (generator sha256-fy32-v1), ranks 9 to 0 as in a FEN; the first is pair 0 of the formal book.
DEAL_VECTORS = {
    6289267212806859400: "npankppcr/9/1c5b1/b1p1r1p1a/9/9/P1P1P1B1B/1C5P1/9/CNRAKANPR",
    1503525060374698604: "ncrpkppbp/9/1a5b1/a1n1p1r1c/9/9/P1A1B1C1R/1P5B1/9/APPNKCRPN",
    8551791509432341759: "nrapkbcpp/9/1c5a1/p1b1r1n1p/9/9/R1A1C1N1P/1B5P1/9/BPPAKNCPR",
}
# Runs without a summary or manifest: the settings of their command (results/longclock/README.md).
LONGCLOCK = {
    "c300t8-v015g-abjchess": dict(a="v015g", b="abjchess", seed=7711, book_games=200, clock="300+3", threads=8),
}
NAMES = {
    "abjchess": "AB-JChess v0.2b",
    "mistboard": "Mistboard PikaJieQi",
    "pikafish-old": "Pikafish jieqi_old",
    "pikaenh": "pikajieqi-enhanced",
    "musesfish": "musesfish",
    "universe": "universe-st Jieqi (hard)",
}
FORMAL_FILES = ("games.jsonl.gz", "summary.json", "manifest.json", "match.log", "void.jsonl")
TERMINAL = {"RED_LOSES": 0.0, "BLACK_LOSES": 1.0, "DRAW": 0.5}
GAME_KEYS = {"pair", "seed", "red", "black", "result", "reason", "plies", "moves"}
MOVE_KEYS = {"m", "r", "c", "s", "t", "rand"}


class Failures(list):
    def add(self, where, what):
        self.append(f"{where}: {what}")


FAIL = Failures()


# ---- statistics, as engine/tools/match.py summarize() ------------------------------------------------------

def elo(s: float) -> float:
    s = min(max(s, 1e-6), 1 - 1e-6)
    return -400 * math.log10(1 / s - 1)


def stats(scores: list[tuple[int, float]]) -> dict:
    """scores: (pair, score of engine a) per game, in file order."""
    n = len(scores)
    w = sum(1 for _, x in scores if x == 1.0)
    d = sum(1 for _, x in scores if x == 0.5)
    l = n - w - d
    s = (w + 0.5 * d) / n
    var = (w * (1 - s) ** 2 + d * (0.5 - s) ** 2 + l * (0 - s) ** 2) / n
    se = math.sqrt(var / n) if n > 1 else 0.5
    pairs: dict[int, list[float]] = {}
    for p, x in scores:
        pairs.setdefault(p, []).append(x)
    ps = [sum(v) / 2 for v in pairs.values() if len(v) == 2]
    if len(ps) < 2:
        raise ValueError("fewer than two complete pairs")
    m = sum(ps) / len(ps)
    ss = sum((x - m) ** 2 for x in ps)
    pent = {}
    for label, pv in (("population", ss / len(ps)), ("n-1", ss / (len(ps) - 1))):
        pse = math.sqrt(pv / len(ps))
        pent[label] = (elo(m - Z * pse), elo(m + Z * pse))
    totals = Counter(2 * x for x in ps)
    return dict(games=n, w=w, d=d, l=l, score=s, elo=elo(s), elo_lo=elo(s - Z * se), elo_hi=elo(s + Z * se),
                pairs=len(ps), incomplete=len(pairs) - len(ps), pent_score=m, pent_elo=elo(m),
                pent=pent, pair_counts=[totals.get(k, 0) for k in (0, 0.5, 1, 1.5, 2)])


def close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol


# ---- deals and records -------------------------------------------------------------------------------------

def deal_fen(setup: Setup) -> str:
    rows = []
    for rank in range(9, -1, -1):
        row, empty = "", 0
        for f in range(9):
            p = setup.board[rank * 9 + f]
            if p is None:
                empty += 1
                continue
            row += (str(empty) if empty else "") + p.code(reveal=True)
            empty = 0
        rows.append(row + (str(empty) if empty else ""))
    return "/".join(rows)


def check_vectors():
    for seed, fen in DEAL_VECTORS.items():
        got = deal_fen(Setup.from_seed(seed))
        if got != fen:
            FAIL.add("jieqi/setup.py", f"deal of seed {seed} is {got}, expected {fen}")
    if book_seed(FORMAL_PHRASE) != FORMAL_SEED:
        FAIL.add("formal book", f"seed of {FORMAL_PHRASE!r} is {book_seed(FORMAL_PHRASE)}, expected {FORMAL_SEED}")


def pair_seeds(seed: int, games: int) -> list[int]:
    rng = random.Random(seed)
    return [rng.getrandbits(63) for _ in range((games + 1) // 2)]


def read_games(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def check_game(where: str, g: dict, deals: dict, rules=None) -> bool:
    """Deal, reveals, captures and result of one game; with rules, also its replay through the referee."""
    if set(g) != GAME_KEYS:
        FAIL.add(where, f"keys {sorted(g)}")
        return False
    moves = g["moves"]
    if g["plies"] != len(moves):
        FAIL.add(where, f"plies {g['plies']} but {len(moves)} moves")
        return False
    setup = deals.get(g["seed"])
    if setup is None:
        setup = deals[g["seed"]] = Setup.from_seed(int(g["seed"]))
    truth = list(setup.board)
    public = "".join("." if p is None else (("X" if p.color is Color.RED else "x") if p.hidden else p.code())
                     for p in truth)
    names, reveals = [], []
    for i, mv in enumerate(moves):
        if not set(mv) <= MOVE_KEYS:
            FAIL.add(where, f"ply {i}: keys {sorted(mv)}")
            return False
        side = Color.RED if i % 2 == 0 else Color.BLACK
        o, d = square(mv["m"][:2]), square(mv["m"][2:4])
        mover, victim = truth[o], truth[d]
        if mover is None or mover.color is not side or (victim is not None and victim.color is side):
            FAIL.add(where, f"ply {i} {mv['m']}: not a move of {side.value} on the deal")
            return False
        reveal = mover.kind.value if mover.hidden else None
        if mv["r"] != reveal:
            FAIL.add(where, f"ply {i} {mv['m']}: recorded reveal {mv['r']}, the deal has {reveal}")
            return False
        captured = victim.kind.value if victim is not None else None
        if mv["c"] != captured:
            FAIL.add(where, f"ply {i} {mv['m']}: recorded capture {mv['c']}, the deal has {captured}")
            return False
        truth[d] = type(mover)(mover.color, mover.kind, False)
        truth[o] = None
        names.append(mv["m"])
        reveals.append(Kind(reveal) if reveal else None)
    reason, result = g["reason"], g["result"]
    to_move_loses = 0.0 if len(moves) % 2 == 0 else 1.0  # Red is to move after an even number of plies
    expected = (TERMINAL[reason] if reason in TERMINAL else
                to_move_loses if reason == "TIME_FORFEIT" or reason.startswith("illegal move") else
                0.5 if reason == "MAX_PLIES" and len(moves) == 1000 else None)
    if expected is None or result != expected:
        FAIL.add(where, f"result {result} does not follow from reason {g['reason']!r}")
        return False
    if rules is not None:
        from jieqi.native import GameStatus, NativeError
        try:
            status = rules.game_replay(public, Color.RED, names, reveals)
        except (NativeError, ValueError) as e:
            FAIL.add(where, f"the referee rejects the moves: {e}")
            return False
        want = GameStatus[reason] if reason in TERMINAL else GameStatus.ONGOING
        if status is not want:
            FAIL.add(where, f"the referee ends the game {status.name}, the record says {g['reason']!r}")
            return False
    return True


def check_run(where: str, games: list[dict], a: str, b: str, seed: int, ngames: int, rules, deals) -> dict | None:
    seeds = pair_seeds(seed, ngames)
    seen, scores, reasons, ok = set(), [], Counter(), True
    red_results: dict[int, list[float]] = {}  # per pair, Red's result in each of its games
    as_red = 0.0
    for k, g in enumerate(games):
        w = f"{where} game {k + 1}"
        if {g.get("red"), g.get("black")} != {a, b}:
            FAIL.add(w, f"players {g.get('red')} and {g.get('black')}, expected {a} and {b}")
            ok = False
            continue
        p = g["pair"]
        if not (0 <= p < len(seeds)) or g["seed"] != str(seeds[p]):
            FAIL.add(w, f"pair {p} seed {g['seed']} is not in the deal book of seed {seed}")
            ok = False
            continue
        if (p, g["red"]) in seen:
            FAIL.add(w, f"pair {p} with {g['red']} as Red appears twice")
            ok = False
            continue
        seen.add((p, g["red"]))
        ok &= check_game(w, g, deals, rules)
        scores.append((p, g["result"] if g["red"] == a else 1 - g["result"]))
        reasons[g["reason"].split(":")[0]] += 1
        red_results.setdefault(p, []).append(g["result"])
        as_red += g["result"] if g["red"] == a else 0
    if not ok or not scores:
        return None
    s = stats(scores)
    s["reasons"] = dict(reasons)
    # a's points with each colour; a pair is split one game each exactly when Red's result is the same in both
    s["as_red"], s["as_black"] = as_red, s["w"] + s["d"] / 2 - as_red
    same = [v[0] for v in red_results.values() if len(v) == 2 and v[0] == v[1]]
    s["split"] = dict(red=same.count(1.0), black=same.count(0.0), draws=same.count(0.5))
    s["played"] = scores  # (pair, a's score) of each game, in the order played
    return s


def compare_summary(where: str, s: dict, summ: dict):
    for k in ("games", "w", "d", "l"):
        if summ.get(k) != s[k]:
            FAIL.add(where, f"summary {k} {summ.get(k)}, recomputed {s[k]}")
    for k in ("score", "elo", "elo_lo", "elo_hi"):
        if not close(summ.get(k), s[k]):
            FAIL.add(where, f"summary {k} {summ.get(k)}, recomputed {s[k]}")
    pe = summ.get("pent") or {}
    lo, hi = s["pent"]["population"]
    for k, v in (("pairs", s["pairs"]), ("score", s["pent_score"]), ("elo", s["pent_elo"]), ("elo_lo", lo), ("elo_hi", hi)):
        if not (pe.get(k) == v if k == "pairs" else close(pe.get(k), v)):
            FAIL.add(where, f"summary pent {k} {pe.get(k)}, recomputed {v}")
    if summ.get("reasons") != s["reasons"]:
        FAIL.add(where, f"summary reasons {summ.get('reasons')}, recomputed {s['reasons']}")
    if summ.get("a") is None or summ.get("b") is None:
        FAIL.add(where, "summary names no engines")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(where: str, d: Path, files) -> bool:
    missing = [f for f in files if not (d / f).is_file()]
    if missing:
        FAIL.add(where, f"missing {', '.join(missing)}")
    return not missing


# ---- the three kinds of run --------------------------------------------------------------------------------

def formal_runs(rules, deals) -> list[dict]:
    rows = []
    net_sha = sha256(NET)
    for d in sorted(p for p in (RESULTS / "formal").iterdir() if p.is_dir()):
        where = f"results/formal/{d.name}"
        if not need(where, d, FORMAL_FILES):
            continue
        man = json.loads((d / "manifest.json").read_text())
        summ = json.loads((d / "summary.json").read_text())
        opp = man["opponent"]["key"]
        checks = [
            (man.get("name") == d.name, f"manifest name {man.get('name')}"),
            (man.get("seed") == FORMAL_SEED, f"deal seed {man.get('seed')} is not the formal book's {FORMAL_SEED}"),
            (man.get("book") == "default: " + FORMAL_PHRASE, f"book {man.get('book')!r}"),
            (man["jqe"]["sha256"] == JQE_SHA256, f"jqe sha256 {man['jqe']['sha256']}"),
            (man["net"]["sha256"] == net_sha, f"net sha256 {man['net']['sha256']} is not engine/nets/it014.jqn's"),
            (man.get("concurrency") == 1 and man.get("ponder") is False, "not one game at a time without pondering"),
            (summ.get("a") == "jqe" and summ.get("b") == opp, f"summary engines {summ.get('a')}, {summ.get('b')}"),
            (summ["args"].get("seed") == man.get("seed"), "summary and manifest seeds differ"),
            (summ["args"].get("games") == 2 * man.get("pairs", 0), "summary games and manifest pairs differ"),
        ]
        for ok, what in checks:
            if not ok:
                FAIL.add(where, what)
        text = (d / "match.log").read_text()
        log = text.rstrip("\n").rsplit("\n", 1)[-1]
        if not log.startswith("# exit 0"):
            FAIL.add(where, f"match.log does not end with '# exit 0' ({log!r})")
        # each start of formal.py writes '# start'; each continuation of a stopped run, 'resume: N games kept'
        resumed = [int(n) for n in re.findall(r"^resume: (\d+) games kept$", text, re.M)]
        if len(re.findall(r"^# start ", text, re.M)) != 1 + len(resumed):
            FAIL.add(where, "match.log: the starts and the continuations do not agree")
        void = [line for line in (d / "void.jsonl").read_text().splitlines() if line.strip()]
        games = read_games(d / "games.jsonl.gz")
        if len(games) != 2 * man["pairs"]:
            FAIL.add(where, f"{len(games)} games, the manifest has {man['pairs']} pairs")
        s = check_run(where, games, "jqe", opp, man["seed"], 2 * man["pairs"], rules, deals)
        if s is None:
            continue
        compare_summary(where, s, summ)
        clock = man["clock"].split()
        s.update(run=d.name, opp=opp, threads=man["threads"], void=len(void), resumed=resumed,
                 clock=clock[1] if clock[0] == "--tc" else f"{int(clock[1]) / 1000:g} s a move")
        rows.append(s)
    return rows


def longclock_runs(rules, deals) -> list[dict]:
    rows = []
    for d in sorted(p for p in (RESULTS / "longclock").iterdir() if p.is_dir()):
        where = f"results/longclock/{d.name}"
        cfg = LONGCLOCK.get(d.name)
        if cfg is None:
            FAIL.add(where, "no settings for this run in LONGCLOCK")
            continue
        if not need(where, d, ["games.jsonl.gz"]):
            continue
        s = check_run(where, read_games(d / "games.jsonl.gz"), cfg["a"], cfg["b"], cfg["seed"], cfg["book_games"],
                      rules, deals)
        if s is not None:
            s.update(run=d.name, a=cfg["a"], b=cfg["b"], seed=cfg["seed"], clock=cfg["clock"], threads=cfg["threads"])
            rows.append(s)
    return rows


def exploiter_runs(rules, deals) -> list[dict]:
    rows = []
    base = RESULTS / "exploiter"
    state = json.loads((base / "xpl1-state.json").read_text())
    evals = {e["run"]: e for e in state["evals"]}
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        where = f"results/exploiter/{d.name}"
        if not need(where, d, ["games.jsonl.gz", "summary.json"]):
            continue
        summ = json.loads((d / "summary.json").read_text())
        args = summ["args"]
        s = check_run(where, read_games(d / "games.jsonl.gz"), summ["a"], summ["b"], args["seed"], args["games"],
                      rules, deals)
        if s is None:
            continue
        compare_summary(where, s, summ)
        e = evals.get(d.name)
        if e is None:
            FAIL.add(where, "not among the evaluations of results/exploiter/xpl1-state.json")
        else:
            lo, hi = s["pent"]["population"]
            if book_seed(e["phrase"]) != args["seed"] or e["seed"] != args["seed"]:
                FAIL.add(where, f"deal seed {args['seed']} is not that of the book {e['phrase']!r}")
            for k, v in (("games", s["games"]), ("wins", s["w"]), ("draws", s["d"]), ("losses", s["l"]),
                         ("reasons", s["reasons"])):
                if e.get(k) != v:
                    FAIL.add(where, f"state {k} {e.get(k)}, recomputed {v}")
            for k, v in (("score", s["score"]), ("elo", s["elo"]), ("lo", lo), ("hi", hi)):
                if not close(e.get(k), v):
                    FAIL.add(where, f"state {k} {e.get(k)}, recomputed {v}")
            nt = re.search(r"NodesTime=(\d+)", args["engine"][0])
            s.update(book=e["phrase"], label=e["label"], round=e["round"],
                     budget=(f"{args['tc']}, NodesTime {nt.group(1)}" if args["tc"] else f"{args['nodes']} nodes per move"))
        s.update(run=d.name)
        rows.append(s)
    return rows


# ---- tables ------------------------------------------------------------------------------------------------

def ival(lo, hi):
    return f"[{lo:+.0f}, {hi:+.0f}]"


def formal_table(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: ("s a move" in r["clock"], -r["threads"], r["run"]))
    out = ["| Opponent | Clock | Threads each | Games | W-D-L for jqe | Score | Elo, pentanomial 95% | Elo, trinomial 95% "
           "| Pair scores 0 / ½ / 1 / 1½ / 2 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        out.append(f"| {NAMES.get(r['opp'], r['opp'])} | {r['clock']} | {r['threads']} | {r['games']} "
                   f"| {r['w']}-{r['d']}-{r['l']} | {r['score']:.3f} "
                   f"| {r['pent_elo']:+.0f} {ival(*r['pent']['population'])} "
                   f"| {r['elo']:+.0f} {ival(r['elo_lo'], r['elo_hi'])} "
                   f"| {' / '.join(str(c) for c in r['pair_counts'])} |")
    return "\n".join(out)


def other_tables(longclock: list[dict], exploiter: list[dict]) -> str:
    out = []
    for r in longclock:
        out += [f"Long clock, {r['run']} (development run, not on the formal book): {r['a']} against {r['b']}, "
                f"{r['clock']}, {r['threads']} threads each, deal seed {r['seed']}",
                f"  {r['games']} games ({r['pairs']} complete pairs) {r['w']}-{r['d']}-{r['l']}, score {r['score']:.3f}, "
                f"Elo {r['elo']:+.0f}, trinomial 95% {ival(r['elo_lo'], r['elo_hi'])}",
                f"  pentanomial 95%: {ival(*r['pent']['population'])} with population variance (as match.py), "
                f"{ival(*r['pent']['n-1'])} with n-1 variance (as formal_report.py)",
                f"  pair scores 0 / ½ / 1 / 1½ / 2: {' / '.join(str(c) for c in r['pair_counts'])}", ""]
    if exploiter:
        out += ["Exploiter test xpl1 (exploiter x against the champion; score and Elo are the exploiter's):", "",
                "| Run | Deal book | Budget | Games | W-D-L | Score | Elo, pentanomial 95% |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in exploiter:
            out.append(f"| {r['run']} | {r.get('book', '')} | {r.get('budget', '')} | {r['games']} "
                       f"| {r['w']}-{r['d']}-{r['l']} | {r['score']:.4f} "
                       f"| {r['pent_elo']:+.0f} {ival(*r['pent']['population'])} |")
    return "\n".join(out)


def sg(x: float) -> str:
    """A signed whole number with a true minus sign, as the prose writes it."""
    return f"{x:+.0f}".replace("-", "−")


def points(x: float) -> str:
    return f"{int(x)}{'½' if x % 1 else ''}"


def report_table(rows: list[dict]) -> str:
    out = ["| Opponent | Clock | Points for jqe | W-D-L for jqe | Elo for jqe, 95% |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: ("s a move" in r["clock"], -r["threads"], r["run"])):
        clock = (f"{r['clock']}, jqe on {r['threads']} thread{'s' * (r['threads'] > 1)}" if "s a move" in r["clock"]
                 else f"{r['clock']}, {r['threads']} threads each")
        out.append(f"| {NAMES.get(r['opp'], r['opp'])} | {clock} | {points(r['w'] + r['d'] / 2)} of {r['games']} "
                   f"| {r['w']}-{r['d']}-{r['l']} | **{sg(r['pent_elo'])} [{sg(r['pent']['population'][0])}, "
                   f"{sg(r['pent']['population'][1])}]** |")
    return "\n".join(out)


NUMBER = dict(enumerate("none one two three four five six seven eight nine ten".split()))


def halves(r: dict, games: int) -> tuple:
    """jqe's mean pair score over the pairs begun in the first `games` games and over the rest, and the two-sided
    p-value of their difference (Welch's z on the pair scores)."""
    first = {p for p, _ in r["played"][:games]}
    tot: dict[int, list[float]] = {}
    for p, x in r["played"]:
        tot.setdefault(p, []).append(x)
    a = [sum(v) / 2 for p, v in tot.items() if p in first]
    b = [sum(v) / 2 for p, v in tot.items() if p not in first]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va, vb = (sum((x - m) ** 2 for x in v) / (len(v) - 1) for v, m in ((a, ma), (b, mb)))
    z = (ma - mb) / math.sqrt(va / len(a) + vb / len(b))
    return len(a), ma, len(b), mb, math.erfc(abs(z) / math.sqrt(2))


def stated(formal: list[dict], longclock: list[dict], exploiter: list[dict]) -> list[str]:
    """The sentences of README.md and REPORT.md that quote the records, rebuilt from the recomputed rows.
    --check fails unless each is found word for word; what the sentences take for granted is checked here."""
    out: list[str] = []
    f = {r["opp"]: r for r in formal}
    ab = f.get("abjchess")
    if ab is None:
        FAIL.add("stated", "no formal run against AB-JChess")
        return out
    lo, hi = ab["pent"]["population"]
    if min(formal, key=lambda r: r["pent_elo"]) is not ab:
        FAIL.add("stated", "AB-JChess is no longer the opponent against which jqe's margin is smallest")
    pairs = {r["pairs"] for r in formal}
    if len(pairs) != 1:
        FAIL.add("stated", f"the formal runs have different numbers of pairs: {sorted(pairs)}")
    (npairs,) = pairs or {0}
    timed = [r for r in formal if "s a move" not in r["clock"]]
    per_move = [r for r in formal if "s a move" in r["clock"]]
    if {(r["clock"], r["threads"]) for r in timed} != {("60+0.6", 8)} or \
            {(r["opp"], r["clock"], r["threads"]) for r in per_move} != {("musesfish", "2 s a move", 1), ("universe", "2 s a move", 1)}:
        FAIL.add("stated", "the clocks and threads of the formal runs are not the ones the documents describe")
    if sum(ab["split"].values()) != ab["pair_counts"][2]:
        FAIL.add("stated", "the pairs in which jqe scored one point are not all Red's, Black's or two draws")
    if any(r["void"] or set(r["reasons"]) - set(TERMINAL) for r in formal):
        FAIL.add("stated", "a formal game was void, forfeited or stopped at the move cap")
    out += [
        # README.md
        f"It was measured in {npairs} duplicate pairs of games against each of the {NUMBER.get(len(formal))} other "
        f"Jieqi engines that could be run",
        f"jqe scored {100 * ab['score']:.1f}% against the strongest of them, AB-JChess, a margin of {sg(ab['pent_elo'])} "
        f"Elo with a 95% interval of {sg(lo)} to {sg(hi)}, and more against the other {NUMBER.get(len(formal) - 1)}.",
        f"Each opponent played {npairs} pairs of games against jqe-v0.15g with it014.",
        "No game was void, lost on time or lost by an illegal move.",
        f"Against the {NUMBER.get(len(timed))} engines that can use threads the clock was 60 s a game plus 0.6 s a move, "
        f"with 8 threads each; musesfish and universe take a time per move, so they had 2 s a move, and jqe one thread.",
        # REPORT.md
        f"**Met against all {NUMBER.get(len(formal))} engines that could be run**",
        f"No game was void, lost on time, lost by an illegal move or stopped at the move cap.",
        f"**Against AB-JChess**, jqe won both games of a pair {ab['pair_counts'][4]} times and lost both "
        f"{ab['pair_counts'][0]} times. Of the {ab['pair_counts'][2]} pairs in which jqe scored one point, Red won both "
        f"games in {ab['split']['red']} and Black in {ab['split']['black']}; "
        f"{'one pair was two draws' if ab['split']['draws'] == 1 else str(ab['split']['draws']) + ' pairs were two draws'}. "
        f"jqe scored {points(ab['as_red'])} of {npairs} as Red and {points(ab['as_black'])} as Black.",
        f"The formal figure, {sg(ab['pent_elo'])}, is lower.",
    ]
    resumed = sorted((r for r in formal if r["resumed"]), key=lambda r: r["run"])
    if resumed:
        times = {1: "once", 2: "twice", 3: "three times"}
        after = lambda ns: " and ".join(map(str, ns)) + (" game" if ns == [1] else " games")
        out.append(f"{NUMBER.get(len(resumed)).capitalize()} runs were stopped and continued: "
                   + "; ".join(f"{NAMES[r['opp']]} {times[len(r['resumed'])]}, after {after(r['resumed'])}" for r in resumed) + ".")
    for opp, cut, name in (("mistboard", 430, "Mistboard run the first"), ("pikafish-old", 420, "first")):
        if opp in f:
            n1, m1, n2, m2, p = halves(f[opp], cut)
            out.append(f"jqe scored {m1:.3f} over the {n1} pairs before and {m2:.3f} over the {n2} after")
            out.append(f"p = {p:.2f}")
            out.append(f"{name} {cut} games")
    for r in longclock:
        plo, phi = r["pent"]["population"]
        out += [f"{r['clock']}, against AB-JChess gave {sg(r['pent_elo'])} [{sg(plo)}, {sg(phi)}] over {r['pairs']} pairs",
                f"jqe scored {points(r['w'] + r['d'] / 2)} of {r['games']} ({r['w']}-{r['d']}-{r['l']}), "
                f"**{sg(r['pent_elo'])} [{sg(plo)}, {sg(phi)}]** over {r['pairs']} pairs",
                "(An earlier version of this report gave [{}, {}], computed with n − 1".format(
                    *(sg(x) for x in r["pent"]["n-1"]))]
    e = {r.get("label"): r for r in exploiter}
    if "e1" in e and "e2" in e:
        sel = [r for r in exploiter if r.get("label") == "sel"]
        if max(sel, key=lambda r: (r["score"], r["round"]))["round"] != e["e1"]["round"] or e["e1"]["round"] != e["e2"]["round"]:
            FAIL.add("stated", "the evaluated exploiter is not the network that scored best in selection")
        # the selected network was trained on the records of its own round and every round before it
        state = json.loads((RESULTS / "exploiter/xpl1-state.json").read_text())
        rounds = {r["round"]: r for r in state["rounds"]}
        files = set(rounds[e["e1"]["round"]]["train"]["files"])
        trained = sum(r["arms"]["base"]["games"] for r in rounds.values() if Path(r["data"]).name in files)
        out += [f"fine-tuned on {trained:,} games against jqe",
                f"that of round {e['e1']['round']} and so trained on {trained:,} games against jqe"]
        out.append(f"won {100 * e['e1']['w'] / e['e1']['games']:.1f}% and {100 * e['e2']['w'] / e['e2']['games']:.1f}% "
                   f"of its games at two search budgets")
        for k, budget in (("e1", "E1: 5,000 nodes a move"), ("e2", "E2: 10+0.1 on the node clock, NodesTime 900")):
            r = e[k]
            plo, phi = r["pent"]["population"]
            out.append(f"| {budget}")
            out.append(f"| {r['w']} / {r['d']} / {r['l']} | {r['w'] / r['games']:.3f} | {r['score']:.4f} "
                       f"| {sg(r['pent_elo'])} [{sg(plo)}, {sg(phi)}] |")
    # the generation rounds, from the test's state file (their games are not in the repository)
    state = json.loads((RESULTS / "exploiter/xpl1-state.json").read_text())
    rounds = state["rounds"]
    per_round = {r["arms"]["base"]["games"] for r in rounds}
    tuned = [r["arms"]["base"]["elo"] for r in rounds if r["net"] != NET.relative_to(ROOT).as_posix()]
    if len(per_round) != 1 or len(tuned) != len(rounds) - 1 or max(tuned) >= 0:
        FAIL.add("stated", "the exploiter's generation rounds are not as the report describes them")
    out += [f"{NUMBER.get(len(rounds))} rounds of {min(per_round):,} games at 5,000 nodes a move, "
            f"{sum(r['arms']['base']['games'] for r in rounds):,} in all",
            f"every fine-tuned network scored below the champion ({sg(max(tuned))} to {sg(min(tuned))} Elo over "
            f"{min(per_round):,} games each)",
            f"The budget was {state['core_seconds'] / 3600:.1f} core-hours and {state['gpu_seconds'] / 3600:.2f} GPU-hours."]
    # the engine's rules against the referee's, with the measured source (engine/tests/difftest.cpp)
    dt = (RESULTS / "difftest/v0.15g.txt").read_text()
    m = re.search(r"^games (\d+) positions (\d+) .* failures (\d+)$", dt, re.M)
    rep = re.search(r"^repetition cycles \d+: .* failures (\d+)$", dt, re.M)
    if not m or not rep or int(m[3]) or int(rep[1]):
        FAIL.add("stated", "results/difftest/v0.15g.txt is incomplete or records a failure")
    else:
        out.append(f"every position of {int(m[1]):,} random games ({int(m[2]):,} positions; `results/difftest/v0.15g.txt`")
    net = NET.read_bytes()
    train = json.loads((RESULTS / "training/it014-train.json").read_text())
    out += [f"`engine/nets/it014.jqn`\n  ({len(net) / 1e6:.1f} MB)",
            f"({len(net):,} bytes, SHA-256 {hashlib.sha256(net).hexdigest()})",
            f"trained on {train['records'] / 1e6:.0f} million positions"]
    return out


def block(text: str, name: str) -> str | None:
    begin, end = f"<!-- {name}:begin -->", f"<!-- {name}:end -->"
    if begin not in text or end not in text:
        return None
    return text.split(begin, 1)[1].split(end, 1)[0].strip("\n")


def put(text: str, name: str, body: str) -> str:
    begin, end = f"<!-- {name}:begin -->", f"<!-- {name}:end -->"
    head, rest = text.split(begin, 1)
    return head + begin + "\n" + body + "\n" + end + rest.split(end, 1)[1]


def norm(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write the formal table into README.md")
    ap.add_argument("--check", action="store_true", help="fail if README.md or a stated sentence is out of date")
    ap.add_argument("--replay", action="store_true", help="replay every game through the native referee")
    a = ap.parse_args()
    t0 = time.monotonic()
    rules = None
    if a.replay:
        os.environ.setdefault("JIEQI_NATIVE_LIBRARY", str(ROOT / "build/release/lib/libjieqi_rules.so"))
        from jieqi.native import NativeRules
        rules = NativeRules()
    check_vectors()
    deals: dict[str, Setup] = {}
    formal = formal_runs(rules, deals)
    longclock = longclock_runs(rules, deals)
    exploiter = exploiter_runs(rules, deals)
    table = formal_table(formal)
    print(table)
    print()
    print(other_tables(longclock, exploiter))
    ngames = sum(r["games"] for r in formal + longclock + exploiter)
    print(f"\n{len(formal) + len(longclock) + len(exploiter)} runs, {ngames} games, {len(deals)} deals regenerated"
          f"{', every game replayed through the referee' if rules else ''} ({time.monotonic() - t0:.0f} s)")

    tables = ((README, "results", table), (REPORT, "report-results", report_table(formal)))
    if a.write:
        for path, name, body in tables:
            text = path.read_text(encoding="utf-8")
            if block(text, name) is None:
                FAIL.add(path.name, f"no <!-- {name}:begin --> ... <!-- {name}:end --> block")
            else:
                path.write_text(put(text, name, body), encoding="utf-8")
                print(f"{path.name}: table written")
    if a.check:
        for path, name, body in tables:
            if block(path.read_text(encoding="utf-8"), name) != body:
                FAIL.add(path.name, f"the table {name} differs from the records (run with --write)")
        docs = "\n".join(norm(p.read_text(encoding="utf-8")) for p in (README, REPORT))
        for sentence in stated(formal, longclock, exploiter):
            if norm(sentence) not in docs:
                FAIL.add("stated", f"not found in README.md or REPORT.md: {sentence!r}")
    if FAIL:
        print(f"\n{len(FAIL)} check(s) failed:")
        for f in FAIL[:50]:
            print("  " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
