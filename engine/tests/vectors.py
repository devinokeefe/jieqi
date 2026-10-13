#!/usr/bin/env python3
"""Test vectors from the engine, for ports of it (the website's TypeScript port is checked against them).

Regenerate, from the repository root (Python 3 standard library and g++ only):

    python3 engine/tests/vectors.py [ENGINE] [--out DIR] [--quick]

ENGINE is the UCI binary (default engine/build/jqe, the Release build); the network is engine/nets/it014.jqn.
DIR defaults to engine/tests/vectors. The script lowers its own priority (nice 10), runs every engine with one
thread, and builds three probes into a temporary directory for what UCI does not print:
engine/tests/rules_probe.cpp (with position.cpp and tables.cpp; the facts of a position),
engine/tests/nnue_probe.cpp (nnue.cpp compiled in, with the engine's Release flags; the float an evaluation is
truncated from) and engine/tests/referee_probe.cpp (with the native referee, native/rules.cpp, repetition.cpp and
chase.cpp; how a game ends). All games are seeded, so a rerun with the same binary writes the same files.
--quick makes a small set for trying the script out. It prints a summary of what it wrote, and writes:

  rules.jsonl.gz   one line per game from seeded random play: {"start", "tokens", "pos": [...]} with, for every
                   prefix of the tokens (the position after i tokens), the FEN as `d` prints it, the legal moves
                   (`moves`), perft 1 and 2 (and 3 at every fifth position), and from the probe the key, check,
                   repetition status, no-capture count, last irreversible index, has_major for both sides, chase
                   threats of both sides, gives_check per legal move and the pseudo-legal and capture counts; from
                   the native referee its verdict "ref" (0 on, 1 draw, 2 side to move wins, 3 it loses: third
                   occurrence, no legal move, 80-ply count); at every fourth position also `see` of every legal move.
  eval.jsonl.gz    {"fen", "eval", "bits", "classical", "evalf"}: `eval` with the quantised network (the
                   default) and, from the probe, the bits of the float it truncates; the classical evaluation; and
                   `eval` with NNUEQuant false (the float network); for every distinct position of rules.jsonl.gz.
  libm.json        SHA-256 digests of glibc's exp on every argument the search gives it (-v / 430 for |v| <=
                   10000) and of its log on 120,063 arguments of the form e / (1 - e) and the integers 1 to 63,
                   in the order generated here (Python's math.exp and math.log call glibc), with samples.
  search.jsonl     one search per line, each from a fresh searcher ("setoption name Threads value 1" resets the
                   worker, "ucinewgame" clears the hash): {"start", "tokens", "hash", "go", "info", "bestmove"}
                   where info lists, per completed depth, [depth, seldepth, score, nodes, hashfull, pv].
  bench.json       the engine's `bench` (depth 7, Hash 64): per position FEN, move, score and nodes, and the total.

Games: uniform random legal moves from the start position and a few other starts, in four styles (plain; quiet,
which avoids captures so that the 80-ply no-capture count is reached; capture-hungry, for endgames; and shuffling,
which plays bursts of a move, a reply and both reversed, preferring checking moves, for repetitions, perpetual
checks and chases), then a few fixed lines (LINES) for the rarer repetition verdicts. A face-down mover's identity
is drawn from its urn as the FEN gives it (weighted by count); a captured face-down piece's identity is recorded,
drawn the same way from its side's urn, in half of the captures, and left unknown ('x' or nothing) in the others.
"""
import gzip
import json
import os
import queue
import random
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START = "xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/9/X1X1X1X1X/1X5X1/9/XXXXKXXXX w R2A2C2P5N2B2r2a2c2p5n2b2 0 1"
# The bench's fourth FEN (uci.cpp) has 17 Red pieces: c3 still shows a face-down piece after the soldier from c3
# reached c4. `position` refuses it; the bench does not check, so it searches what set_fen left (see bench.json).
# The games and the Hash 16 searches use it with c3 emptied.
BENCH4_FIXED = "2xakxxxx/4r4/1x5c1/x1x1x1x1p/9/2P6/X3X1X1X/1C5X1/9/XXXXKXXXX w R2A2C1P4N2B2r1a1c1p4n2b2 0 4"
OTHER_STARTS = [
    "xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/4P4/X1X3X1X/1X5X1/9/XXXXKXXXX b R2A2C2P4N2B2r2a2c2p5n2b2 1 1",
    "r1xxkxxxx/9/1x5c1/x1x1x1x1x/9/9/X1X1X1X1X/1C5X1/9/XXXXKXXXX w R2A2C1P5N2B2r1a2c1p5n2b2 2 2",
    BENCH4_FIXED,
    "4k4/9/9/9/9/9/9/9/4A4/3RK4 w - 0 1",
    "3ak4/4a4/9/9/9/9/9/9/9/3RK4 w - 0 1",
    "2bak4/4a4/4b4/p3p3p/2c6/6R2/P3P3P/4B4/4A4/2BAK4 w - 0 30",
    "3k5/4a4/4ba3/p1n1p3p/9/2N3B2/P3P3P/9/4A4/3AK4 b - 3 40",
]
BENCH4_NOTE = ("The fourth FEN has 17 Red pieces. set_fen stops at the 17th (i0) and returns false unchecked, so the "
               "bench searches: that board without i0's piece, Red to move, no-capture count 0, key 0, an empty "
               "history (lastIrrev 0), and urn and urnTotal as the previous bench position (the third FEN) set them, "
               "since they are not reset before the failure (checked with a debug copy of uci.cpp).")
# Fixed lines for the rarer repetition verdicts: a perpetual check (the checker loses), a perpetual chase of an
# undefended cannon by a rook (the chaser loses), a chase of a defended piece (a draw), and a third occurrence
# whose last cycle is all checks by one side but whose first is not (the search's test says the checker loses;
# the referee, judging from the first occurrence, draws).
LINES = [
    ("R8/4k4/9/9/9/9/9/9/9/3K5 w - 0 1", "d0d1 e8e7 d1d0 e7e8 a9a8 e8e9 a8a9 e9e8 a9a8"),
    ("R8/4k4/9/9/9/9/9/9/9/3K5 w - 0 1", "a9a8 e8e9 a8a9 e9e8 a9a8 e8e9 a8a9 e9e8 a9a8"),
    ("4k4/9/R1c6/9/9/9/9/9/9/3K5 b - 0 1", "c7c5 a7a5 c5c7 a5a7 c7c5 a7a5 c5c7 a5a7 c7c5"),
    ("2r1k4/9/R1c6/9/9/9/9/9/9/3K5 b - 0 1", "c7c8 a7a8 c8c7 a8a7 c7c8 a7a8 c8c7 a8a7"),
]
SLOTS = "RNBACP"
TIMEOUT = 600


class Proc:
    """A line-oriented child process with a reader thread (so reads can time out)."""

    def __init__(self, args):
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.q = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.q.put(line.rstrip("\n"))
        self.q.put(None)

    def send(self, *lines):
        self.p.stdin.write("".join(l + "\n" for l in lines))
        self.p.stdin.flush()

    def line(self, timeout=TIMEOUT):
        x = self.q.get(timeout=timeout)
        if x is None:
            raise RuntimeError("process ended")
        return x

    def until(self, pred, timeout=TIMEOUT):
        out = []
        while True:
            x = self.line(timeout)
            if pred(x):
                return out, x
            out.append(x)

    def close(self):
        try:
            self.send("quit")
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


class Engine(Proc):
    def __init__(self, path, net, quant=True, hash_mb=None):
        super().__init__([str(path)])
        self.send("uci")
        self.until(lambda x: x == "uciok")
        self.send("setoption name Threads value 1")
        if hash_mb:
            self.send(f"setoption name Hash value {hash_mb}")
        self.send(f"setoption name EvalFile value {net}")
        if not quant:
            self.send("setoption name NNUEQuant value false")
        out = self.ask()
        if not any("EvalFile loaded" in l for l in out):
            raise RuntimeError("network not loaded: " + " | ".join(out))

    def ask(self, *cmds):
        """Send commands and isready; return the lines before readyok."""
        self.send(*cmds, "isready")
        return self.until(lambda x: x == "readyok")[0]


def position_cmd(start, tokens):
    return f"position fen {start}" + (" moves " + " ".join(tokens) if tokens else "")


def parse_fen(fen):
    f = fen.split()
    board = [None] * 90
    rank, file = 9, 0
    for ch in f[0]:
        if ch == "/":
            rank -= 1
            file = 0
        elif ch.isdigit():
            file += int(ch)
        else:
            board[rank * 9 + file] = ch
            file += 1
    side = 0 if f[1] in ("w", "r") else 1
    urn = [{t: 0 for t in SLOTS}, {t: 0 for t in SLOTS}]
    if len(f) > 2 and f[2] != "-":
        i = 0
        while i < len(f[2]):
            ch = f[2][i]
            i += 1
            n = 0
            while i < len(f[2]) and f[2][i].isdigit():
                n = n * 10 + int(f[2][i])
                i += 1
            urn[0 if ch.isupper() else 1][ch.upper()] = n
    return board, side, urn


def sq(name):
    return (ord(name[1]) - 48) * 9 + ord(name[0]) - 97


def draw(rng, urn_side):
    pool = [t for t in SLOTS for _ in range(urn_side[t])]
    return rng.choice(pool) if pool else None


def make_token(rng, mv, board, side, urn):
    frm, to = sq(mv[:2]), sq(mv[2:4])
    tok = mv
    mover, victim = board[frm], board[to]
    if mover in ("X", "x"):
        t = draw(rng, urn[side])
        tok += t if side == 0 else t.lower()
    if victim in ("X", "x"):
        r = rng.random()
        if r < 0.5:
            t = draw(rng, urn[1 - side])
            if t:
                tok += t if side == 1 else t.lower()
        elif r < 0.75:
            tok += "x"
    return tok


def reverse(mv):
    return mv[2:4] + mv[:2]


def build_probe(tmp, name, flags):
    exe = Path(tmp) / name
    src = ROOT / "engine/src"
    cmd = ["g++", *flags, "-std=c++20", f"-I{src}", str(ROOT / f"engine/tests/{name}.cpp"),
           str(src / "position.cpp"), str(src / "tables.cpp"), "-o", str(exe)]
    subprocess.run(cmd, check=True)
    return exe


def build_referee(tmp):
    exe = Path(tmp) / "referee_probe"
    nat = ROOT / "native"
    cmd = ["g++", "-O2", "-std=c++20", f"-I{nat / 'include'}", str(ROOT / "engine/tests/referee_probe.cpp"),
           str(nat / "rules.cpp"), str(nat / "repetition.cpp"), str(nat / "chase.cpp"), "-o", str(exe)]
    subprocess.run(cmd, check=True)
    return exe


def libm_vectors():
    """Digests of glibc's exp and log over the arguments the port is checked on."""
    import hashlib
    import math
    import struct
    mask = (1 << 64) - 1
    state = [0x12345678ABCDEF]

    def rnd():
        state[0] = (state[0] + 0x9E3779B97F4A7C15) & mask
        z = state[0]
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
        return z ^ (z >> 31)

    hexd = lambda d: struct.pack(">d", d).hex()
    exp_args = [-float(v) / 430.0 for v in range(-10000, 10001)]
    log_args = []
    for _ in range(100000):
        e = 1e-11 + (rnd() >> 11) / 9007199254740992.0 * (1 - 2e-11)
        log_args.append(e / (1.0 - e))
    for _ in range(20000):
        e = 0.5 + ((rnd() >> 11) / 9007199254740992.0 - 0.5) * 0.06
        log_args.append(e / (1.0 - e))
    log_args += [float(d) for d in range(1, 64)]
    out = {}
    for name, fn, args, desc in (
            ("exp", math.exp, exp_args, "-v / 430.0 for v = -10000 .. 10000"),
            ("log", math.log, log_args, "e / (1 - e) for e = 1e-11 + u (1 - 2e-11), 100,000 times, then "
             "e = 0.5 + (u - 0.5) 0.06, 20,000 times, with u = (splitmix64() >> 11) / 2^53 from state "
             "0x12345678abcdef; then the integers 1 to 63")):
        h = hashlib.sha256()
        res = [fn(x) for x in args]
        for r in res:
            h.update(struct.pack("<d", r))
        out[name] = {"args": desc, "count": len(args), "sha256": h.hexdigest(),
                     "samples": [[hexd(args[i]), hexd(res[i])] for i in range(0, len(args), max(1, len(args) // 50))]}
    return out


def observe(eng, rep, ref, start, tokens, k, stats):
    """The record of the position after `tokens`, from the engine and the probes' replies; k is its index."""
    if rep.startswith("error") or ref.startswith("error"):
        raise RuntimeError(f"probe: {rep} / {ref} after {tokens}")
    cmds = [position_cmd(start, tokens), "d", "moves", "perft 1", "perft 2"]
    if k % 5 == 0:
        cmds.append("perft 3")
    out = eng.ask(*cmds)
    fen = next(l[4:] for l in out if l.startswith("fen "))
    legal = next(l for l in out if l.startswith("moves")).split()[1:]
    perft = [int(l.split()[2]) for l in out if l.startswith("perft ")]
    f = rep.split()
    rec = {"fen": fen, "moves": " ".join(legal), "perft": perft, "key": f[0], "check": int(f[1]), "rep": int(f[2]),
           "nc": int(f[3]), "irr": int(f[4]), "major": [int(f[5]), int(f[6])], "chase": [f[7], f[8]], "gives": f[9],
           "pseudo": int(f[10]), "caps": int(f[11]), "ref": int(ref)}
    if k % 4 == 0 and legal:
        sees = eng.ask(*[f"see {m}" for m in legal])
        rec["see"] = [int(l.split()[2]) for l in sees if l.startswith("see ")]
    stats["rep"][rec["rep"]] += 1
    stats["ref"][rec["ref"]] += 1
    stats["check"] += rec["check"]
    stats["nc80"] += rec["nc"] >= 80
    return rec


def ask_probes(probes, cmd):
    for p in probes:
        p.send(cmd)
    return [p.line() for p in probes]


def play_line(eng, probes, start, tokens, stats):
    """Records every prefix of a fixed line."""
    recs = [observe(eng, *ask_probes(probes, f"fen {start}"), start, [], 0, stats)]
    for i, tok in enumerate(tokens):
        recs.append(observe(eng, *ask_probes(probes, f"move {tok}"), start, tokens[:i + 1], i + 1, stats))
    return {"start": start, "tokens": list(tokens), "pos": recs}


def play_game(eng, probes, rng, start, style, max_plies, stats):
    """Plays one seeded game; returns the game record."""
    tokens, recs = [], []
    burst = None
    rep, ref = ask_probes(probes, f"fen {start}")
    for ply in range(max_plies + 1):
        rec = observe(eng, rep, ref, start, tokens, len(recs), stats)
        recs.append(rec)
        fen, legal, gives = rec["fen"], rec["moves"].split(), rec["gives"]
        if not legal or ply == max_plies:
            stats["mates"] += not legal
            break
        board, side, urn = parse_fen(fen)
        caps = [m for m in legal if board[sq(m[2:4])]]
        quiet = [m for m in legal if not board[sq(m[2:4])]]
        faceup_quiet = [m for m in quiet if board[sq(m[:2])] not in ("X", "x")]
        mv = None
        if burst:
            phase = burst["step"] % 4
            if phase == 1 and burst["m2"] is None and faceup_quiet:
                checking = [m for m in faceup_quiet if gives[legal.index(m)] == "1"]
                burst["m2"] = rng.choice(checking if checking and rng.random() < 0.5 else faceup_quiet)
            want = [burst["m1"], burst["m2"], reverse(burst["m1"]), reverse(burst["m2"] or "")][phase]
            if want in legal and not board[sq(want[2:4])]:
                mv = want
                burst["step"] += 1
                if burst["step"] == 4 * burst["reps"]:
                    burst = None
            else:
                burst = None
        if mv is None and style == "shuffle" and ply >= 6 and rng.random() < 0.15 and faceup_quiet:
            checking = [m for m in faceup_quiet if gives[legal.index(m)] == "1"]
            m1 = rng.choice(checking if checking and rng.random() < 0.7 else faceup_quiet)
            burst = {"m1": m1, "m2": None, "step": 1, "reps": rng.choice([1, 2, 2, 3])}
            mv = m1
        if mv is None:
            if style == "quiet" and quiet and rng.random() < 0.95:
                mv = rng.choice(quiet)
            elif style == "captures" and caps and rng.random() < 0.7:
                mv = rng.choice(caps)
            else:
                mv = rng.choice(legal)
        tok = make_token(rng, mv, board, side, urn)
        tokens.append(tok)
        rep, ref = ask_probes(probes, f"move {tok}")
    return {"start": start, "tokens": tokens, "pos": recs}


def parse_info(line):
    w = line.split()
    d = {}
    i = 1
    while i < len(w):
        k = w[i]
        if k == "score":
            d["score"] = w[i + 1] + " " + w[i + 2]
            i += 3
            if i < len(w) and w[i] in ("lowerbound", "upperbound"):
                d["bound"] = w[i]
                i += 1
        elif k == "pv":
            d["pv"] = " ".join(w[i + 1:])
            break
        elif k == "string":
            break
        else:
            d[k] = w[i + 1] if i + 1 < len(w) else ""
            i += 2
    return d


def run_search(eng, start, tokens, go):
    eng.ask("setoption name Threads value 1", "ucinewgame", position_cmd(start, tokens))
    eng.send("go " + go)
    lines, last = eng.until(lambda x: x.startswith("bestmove"))
    info = []
    for l in lines:
        if not l.startswith("info depth"):
            continue
        d = parse_info(l)
        if "bound" in d or "score" not in d:
            continue
        info.append([int(d["depth"]), int(d["seldepth"]), d["score"], int(d["nodes"]), int(d["hashfull"]), d.get("pv", "")])
    return info, last.split()[1]


def main():
    args = sys.argv[1:]
    quick = "--quick" in args
    out_dir = ROOT / "engine/tests/vectors"
    if "--out" in args:
        out_dir = Path(args[args.index("--out") + 1]).resolve()
        args = [a for i, a in enumerate(args) if a != "--out" and (i == 0 or args[i - 1] != "--out")]
    pos_args = [a for a in args if not a.startswith("--")]
    engine = Path(pos_args[0]).resolve() if pos_args else ROOT / "engine/build/jqe"
    net = (ROOT / "engine/nets/it014.jqn").resolve()
    os.nice(max(0, 10 - os.nice(0)))
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        probes = [Proc([str(build_probe(tmp, "rules_probe", ["-O2"]))]), Proc([str(build_referee(tmp))])]
        nprobe = Proc([str(build_probe(tmp, "nnue_probe", ["-O3", "-DNDEBUG", "-march=native"])), str(net)])
        eng = Engine(engine, net)
        with open(out_dir / "libm.json", "w") as f:
            json.dump(libm_vectors(), f, indent=1)
            f.write("\n")

        # 1. rules
        rng = random.Random(20261012)
        stats = {"rep": [0, 0, 0, 0], "ref": [0, 0, 0, 0], "check": 0, "nc80": 0, "mates": 0}
        games = []
        plan = []
        n_games = 12 if quick else 130
        for g in range(n_games):
            style = ["plain", "quiet", "captures", "shuffle"][g % 4]
            start = START if g % 5 else OTHER_STARTS[(g // 5) % len(OTHER_STARTS)]
            max_plies = {"plain": 160, "quiet": 220, "captures": 140, "shuffle": 160}[style]
            plan.append((start, style, max_plies))
        n_pos = 0
        for g, (start, style, max_plies) in enumerate(plan):
            games.append(play_game(eng, probes, rng, start, style, max_plies, stats))
            n_pos += len(games[-1]["pos"])
            if (g + 1) % 20 == 0:
                print(f"  rules: {g + 1} games, {n_pos} positions, {time.time() - t0:.0f} s", flush=True)
        for start, line in LINES:
            games.append(play_line(eng, probes, start, line.split(), stats))
            n_pos += len(games[-1]["pos"])
        with gzip.open(out_dir / "rules.jsonl.gz", "wt", compresslevel=9) as f:
            for gm in games:
                f.write(json.dumps(gm, separators=(",", ":")) + "\n")
        for p in probes:
            p.close()

        # 2. evaluations of every distinct position
        fens = []
        seen = set()
        for gm in games:
            for r in gm["pos"]:
                if r["fen"] not in seen:
                    seen.add(r["fen"])
                    fens.append(r["fen"])
        evals = []
        engf = Engine(engine, net, quant=False)
        for i in range(0, len(fens), 200):
            chunk = fens[i:i + 200]
            q = eng.ask(*[c for fen in chunk for c in (f"position fen {fen}", "eval")])
            fl = engf.ask(*[c for fen in chunk for c in (f"position fen {fen}", "eval")])
            q = [l.split() for l in q if l.startswith("classical ")]
            fl = [l.split() for l in fl if l.startswith("classical ")]
            nprobe.send(*[f"fen {fen}" for fen in chunk])
            nb = [nprobe.line().split() for _ in chunk]
            assert len(q) == len(chunk) == len(fl)
            for fen, a, b, c in zip(chunk, q, fl, nb):
                if c[0] == "error" or int(c[0]) != int(a[3]):
                    raise RuntimeError(f"nnue probe disagrees with the engine on {fen}: {c} vs {a}")
                evals.append({"fen": fen, "eval": int(a[3]), "bits": c[1], "classical": int(a[1]), "evalf": int(b[3])})
        engf.close()
        nprobe.close()
        with gzip.open(out_dir / "eval.jsonl.gz", "wt", compresslevel=9) as f:
            for e in evals:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")
        print(f"  eval: {len(evals)} positions, {time.time() - t0:.0f} s", flush=True)
        eng.close()

        # 3. searches: positions from the games (with their history), all phases
        srng = random.Random(777)
        eng = Engine(engine, net, hash_mb=16)
        cands = []
        for gm in games:
            for i, r in enumerate(gm["pos"]):
                if r["moves"]:
                    dark = sum(ch in "Xx" for ch in r["fen"].split()[0])
                    men = sum(ch.isalpha() for ch in r["fen"].split()[0])
                    phase = "opening" if dark >= 24 else "middle" if dark >= 6 or men >= 18 else "endgame"
                    cands.append((phase, gm["start"], gm["tokens"][:i], r))
        picks = []
        per_phase = 4 if quick else 100
        for phase in ("opening", "middle", "endgame"):
            pool = [c for c in cands if c[0] == phase]
            picks += srng.sample(pool, min(per_phase, len(pool)))
        # positions that repeat an earlier one, so that the search meets repetitions of the game history
        reps = [c for c in cands if c[3]["rep"]]
        picks += srng.sample(reps, min(4 if quick else 30, len(reps)))
        searches = []
        for k, (phase, start, tokens, r) in enumerate(picks):
            depths = [5, 7] + ([9] if k % 6 == 0 and not quick else [])
            for d in depths:
                info, best = run_search(eng, start, tokens, f"depth {d}")
                searches.append({"phase": phase, "start": start, "tokens": tokens, "hash": 16, "go": f"depth {d}",
                                 "info": info, "bestmove": best})
            if k % 10 == 0:
                legal = r["moves"].split()
                sm = srng.sample(legal, min(len(legal), srng.choice([1, 1, 2, 3])))
                info, best = run_search(eng, start, tokens, "depth 6 searchmoves " + " ".join(sm))
                searches.append({"phase": phase, "start": start, "tokens": tokens, "hash": 16,
                                 "go": "depth 6 searchmoves " + " ".join(sm), "info": info, "bestmove": best})
            if k % 10 == 5:
                n = srng.choice([3000, 10000, 30000])
                info, best = run_search(eng, start, tokens, f"nodes {n}")
                searches.append({"phase": phase, "start": start, "tokens": tokens, "hash": 16, "go": f"nodes {n}",
                                 "info": info, "bestmove": best})
            if (k + 1) % 50 == 0:
                print(f"  search: {k + 1} of {len(picks)} positions, {time.time() - t0:.0f} s", flush=True)
        # the bench positions (the fourth with c3 emptied) at Hash 16 as well
        for fen in [START] + OTHER_STARTS[:5]:
            for d in (5, 7, 9):
                info, best = run_search(eng, fen, [], f"depth {d}")
                searches.append({"phase": "bench", "start": fen, "tokens": [], "hash": 16, "go": f"depth {d}",
                                 "info": info, "bestmove": best})
        with open(out_dir / "search.jsonl", "w") as f:
            for s in searches:
                f.write(json.dumps(s, separators=(",", ":")) + "\n")
        eng.close()

        # 4. the bench (Hash 64 as the engine starts; depth 7)
        eng = Engine(engine, net)
        eng.send("bench")
        lines, last = eng.until(lambda x: x.startswith("Nodes searched"))
        bench = []
        for l in lines:
            if l.startswith("bench "):
                fen, rest = l[6:].split(" -> ")
                w = rest.split()
                bench.append({"fen": fen, "move": w[0], "score": int(w[2]), "nodes": int(w[4])})
        eng.ask()
        eng.close()
        total = int(last.split()[2])
        with open(out_dir / "bench.json", "w") as f:
            json.dump({"depth": 7, "hash": 64, "positions": bench, "nodes": total, "note": BENCH4_NOTE}, f, indent=1)
            f.write("\n")

    sizes = {p.name: p.stat().st_size for p in sorted(out_dir.iterdir())}
    print(f"rules: {len(games)} games, {n_pos} positions; repetition status 0/1/2/3: {stats['rep']}; "
          f"referee 0/1/2/3: {stats['ref']}; "
          f"in check {stats['check']}; no-capture count >= 80: {stats['nc80']}; games ending without a legal move: "
          f"{stats['mates']}")
    print(f"eval: {len(evals)} positions")
    print(f"search: {len(searches)} searches from {len(picks) + 6} positions")
    print(f"bench: {total} nodes ({', '.join(str(b['nodes']) for b in bench)})")
    print("files: " + ", ".join(f"{k} {v:,} bytes" for k, v in sizes.items()))
    print(f"time {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
