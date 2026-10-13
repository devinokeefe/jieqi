#!/usr/bin/env python3
"""Lean refereed Jieqi match runner for jqe development.

Referee: the project's native rules library (legality, check, repetition/chase, 80-ply rule).
Truth: seeded hidden deals (jieqi.setup.Setup.from_seed). Each engine only receives its own
observation: reveals are public; a captured face-down identity is shown to the capturer only.
Games are played in duplicate pairs (same deal, colours swapped).

Usage example:
  python3 engine/tools/match.py --engine jqe=engine/build/jqe:EvalFile=$PWD/engine/nets/it014.jqn \
      --engine pika=pikafish-old --games 200 --movetime 200 --concurrency 4 --out engine/runs/test1

EvalFile must be an absolute path, because each engine runs in its own directory. Opponents named by a key of
KNOWN are found under $JIEQI_OPPONENTS (default ~/jieqi-opponents): THIRD_PARTY.md, tools/fetch_opponents.py.
"""
import argparse
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JIEQI_NATIVE_LIBRARY", str(ROOT / "build/release/lib/libjieqi_rules.so"))

from jieqi.native import GameStatus, NativeGame, NativeRules  # noqa: E402
from jieqi.setup import Color, Kind, Setup, coordinate, square  # noqa: E402

START_FEN = "xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/9/X1X1X1X1X/1X5X1/9/XXXXKXXXX w R2A2C2P5N2B2r2a2c2p5n2b2 0 1"
OPPONENTS = Path(os.environ.get("JIEQI_OPPONENTS") or Path.home() / "jieqi-opponents")
KNOWN = {
    "pikafish-old": dict(argv=[str(OPPONENTS / "pikafish-jieqi-old/src/PikaJieQi")], cwd=str(OPPONENTS / "pikafish-jieqi-old/src")),
    "mistboard": dict(argv=[str(OPPONENTS / "mistboard-pikajieqi/src/PikaJieQi")], cwd=str(OPPONENTS / "mistboard-pikajieqi/src")),
    # CoderYiXin/pikajieqi-enhanced 7d5ca267 (GPL, separate process): Mistboard PikaJieQi + sigmoid flip
    # aggregation, chance branch reduction and a flip-search mate fix; classical eval (USE_NNUEEVAL 0).
    # Only src/ is built (ARCH=x86-64-avx2); the repository's online bot script is never run.
    "pikaenh": dict(argv=[str(OPPONENTS / "pikajieqi-enhanced/src/PikaJieQi")], cwd=str(OPPONENTS / "pikajieqi-enhanced/src")),
    # AB-JChess (GPL, separate process). Its strict parser rejects the classical 'x' padding.
    "abjchess": dict(argv=[str(OPPONENTS / "ab-jchess-v02b-header-repair1/src/AB-JChess")],
                     cwd=str(OPPONENTS / "ab-jchess-v02b-header-repair1/src"), pad=False,
                     options={"EvalFile": str(OPPONENTS / "ab-jchess-v02b-source-build/abjchess-20260911.nnue")}),
    # universe-st/Jieqi PIMC AI (MIT, read-only checkout) via the original Node.js adapter in adapters/universe.
    "universe": dict(argv=[str(ROOT / "adapters/universe/run.sh")], cwd=str(ROOT / "adapters/universe"), pad=False,
                     options={"Difficulty": "hard"}),
    # musesfish (GPL, pinned Python checkout) via the timed worker package and the original observation
    # shim in adapters/musesfish_uci (single-threaded; Hash/Threads ignored).
    "musesfish": dict(argv=[str(ROOT / "adapters/musesfish_uci/run.sh")], cwd=str(ROOT / "adapters/musesfish_uci"),
                      pad=False),
}
MAX_PLIES = 1000


class EngineError(RuntimeError):
    pass


class Engine:
    def __init__(self, name, argv, cwd=None, options=None, pad=True):
        self.name = name
        self.pad = pad
        self.proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("uci")
        self.wait_for("uciok", 60)  # start-up is not thinking time; the Node.js adapter needed over 10 s on a loaded host
        for k, v in (options or {}).items():
            self.send(f"setoption name {k} value {v}")
        self.send("isready")
        self.wait_for("readyok", 30)

    def _reader(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))
        self.lines.put(None)

    def send(self, text):
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise EngineError(f"{self.name}: write failed: {e}")

    def wait_for(self, prefix, timeout):
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise EngineError(f"{self.name}: timeout waiting for {prefix}")
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                raise EngineError(f"{self.name}: timeout waiting for {prefix}")
            if line is None:
                raise EngineError(f"{self.name}: process exited")
            if line.startswith(prefix):
                return line

    def new_game(self):
        self.send("ucinewgame")
        self.send("isready")
        self.wait_for("readyok", 30)

    def go(self, events, go_args, timeout):
        # events: (token, revealed). Classical parsers need an 'x' after a lone reveal letter.
        tokens = [t + "x" if self.pad and rev and len(t) == 5 else t for t, rev in events]
        self.t_start = time.monotonic()
        self.send("position fen " + START_FEN + (" moves " + " ".join(tokens) if tokens else ""))
        self.send("go " + go_args)
        deadline = time.monotonic() + timeout
        last_info = ""
        vtime = None  # jqe NodesTime: the engine reports the virtual (node-based) time it used
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise EngineError(f"{self.name}: no bestmove in time")
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                raise EngineError(f"{self.name}: no bestmove in time")
            if line is None:
                raise EngineError(f"{self.name}: process exited")
            if line.startswith("info") and " score " in line:
                last_info = line
            if line.startswith("info string vtime "):
                vtime = int(line.split()[3])
            if line.startswith("bestmove"):
                self.last_ms = vtime if vtime is not None else (time.monotonic() - self.t_start) * 1000
                parts = line.split()
                return (parts[1] if len(parts) > 1 else "(none)"), last_info

    def ponder(self, events):
        tokens = [t + "x" if self.pad and rev and len(t) == 5 else t for t, rev in events]
        self.send("position fen " + START_FEN + (" moves " + " ".join(tokens) if tokens else ""))
        self.send("go infinite")
        self.pondering = True

    def stop_ponder(self):
        if getattr(self, "pondering", False):
            self.pondering = False
            self.send("stop")
            self.wait_for("bestmove", 10)

    def close(self):
        try:
            self.send("quit")
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def parse_engine(spec):
    """name=path[:opt=val,opt=val] or name=known-key."""
    name, _, rest = spec.partition("=")
    path, _, opts = rest.partition(":")
    options = {}
    for kv in filter(None, opts.split(",")):
        k, _, v = kv.partition("=")
        options[k] = v
    if path in KNOWN:
        d = dict(KNOWN[path])
        options = {**d.get("options", {}), **options}
    else:
        p = Path(path)
        if not p.is_absolute():
            p = ROOT / p
        d = dict(argv=[str(p)], cwd=str(p.parent))
    # Options starting with '@' are harness settings, not UCI options (e.g. @movetime=500).
    d["harness"] = {k[1:]: v for k, v in options.items() if k.startswith("@")}
    d["options"] = {k: v for k, v in options.items() if not k.startswith("@")}
    d["name"] = name
    return d


def score_of(info):
    parts = info.split()
    if "score" not in parts:
        return None
    i = parts.index("score")
    kind, val = parts[i + 1], int(parts[i + 2])
    return val if kind == "cp" else (30000 - abs(val)) * (1 if val > 0 else -1)


def play_game(rules, setup, red_spec, black_spec, go_args, hash_mb, threads, move_timeout, record_scores=False, tc=None,
              ponder=False, random_plies=0, random_seed=0):
    """tc: (base_ms, inc_ms) for real clocks; go_args/move_timeout are then ignored.
    random_plies: the first 0..random_plies plies (drawn from random_seed) are uniformly random legal moves chosen by
    the harness, not by the engines: opening diversity for data generation. Not for rated matches."""
    rnd = random.Random(random_seed)
    nrand = rnd.randint(0, random_plies) if random_plies > 0 else 0
    truth = list(setup.board)  # Piece(color, kind, hidden) or None
    public = "".join("." if p is None else (("X" if p.color is Color.RED else "x") if p.hidden else p.code()) for p in truth)
    engines = {}
    own_go, own_timeout = {}, {}
    tokens = {Color.RED: [], Color.BLACK: []}
    moves = []
    result, reason = None, None
    clock = {Color.RED: tc[0], Color.BLACK: tc[0]} if tc else None
    ponders = {}
    spec_of = {Color.RED: red_spec, Color.BLACK: black_spec}
    try:
        for color, spec in ((Color.RED, red_spec), (Color.BLACK, black_spec)):
            opts = {"Hash": hash_mb, "Threads": threads}
            opts.update(spec["options"])
            engines[color] = Engine(spec["name"], spec["argv"], spec.get("cwd"), opts, spec.get("pad", True))
            engines[color].new_game()
            mt = spec.get("harness", {}).get("movetime")
            own_go[color] = f"movetime {mt}" if mt else go_args
            own_timeout[color] = max(move_timeout, int(mt) / 1000 * 3 + 5) if mt else move_timeout
            hp = spec.get("harness", {}).get("ponder")
            ponders[color] = bool(int(hp)) if hp is not None else ponder
        with NativeGame(rules, public, Color.RED) as game:
            side = Color.RED
            while True:
                snap = game.snapshot()
                if snap.status is not GameStatus.ONGOING:
                    result = {GameStatus.DRAW: 0.5, GameStatus.RED_LOSES: 0.0, GameStatus.BLACK_LOSES: 1.0}[snap.status]
                    reason = snap.status.name
                    break
                if len(moves) >= MAX_PLIES:
                    result, reason = 0.5, "MAX_PLIES"
                    break
                eng = engines[side]
                randomised = len(moves) < nrand
                if clock:
                    ga = (f"wtime {int(clock[Color.RED])} btime {int(clock[Color.BLACK])} "
                          f"winc {tc[1]} binc {tc[1]}")
                    to = max(clock[side], 0) / 1000 + 5
                    if int(spec_of[side]["options"].get("NodesTime", 0) or 0) > 0:
                        to = to * 20 + 60  # virtual clock: wall time depends on host load
                else:
                    ga, to = own_go[side], own_timeout[side]
                try:
                    eng.stop_ponder()
                    if randomised:
                        mv, info = rnd.choice(sorted(rules.legal_moves(snap.board, snap.turn))), ""
                    else:
                        mv, info = eng.go(tokens[side], ga, to)
                except EngineError as e:
                    result, reason = (0.0 if side is Color.RED else 1.0), f"engine failure: {e}"
                    break
                if clock and not randomised:
                    clock[side] -= eng.last_ms
                    if clock[side] < 0:
                        result, reason = (0.0 if side is Color.RED else 1.0), "TIME_FORFEIT"
                        break
                    clock[side] += tc[1]
                try:
                    o, d = square(mv[:2]), square(mv[2:4])
                    mover = truth[o]
                    if mover is None or mover.color is not side:
                        raise ValueError("not own piece")
                    reveal = mover.kind if mover.hidden else None
                    game.advance(mv[:4], reveal)
                except Exception as e:  # illegal move forfeits
                    result, reason = (0.0 if side is Color.RED else 1.0), f"illegal move {mv} by {eng.name}: {e}"
                    break
                victim = truth[d]
                base = mv[:4]
                own_tok = base
                opp_tok = base
                if reveal is not None:
                    letter = reveal.value if side is Color.RED else reveal.value.lower()
                    own_tok += letter
                    opp_tok += letter
                if victim is not None and victim.hidden:
                    vletter = victim.kind.value if victim.color is Color.RED else victim.kind.value.lower()
                    own_tok += vletter  # capturer sees the identity; victim's owner does not
                tokens[side].append((own_tok, reveal is not None))
                tokens[side.opponent].append((opp_tok, reveal is not None))
                truth[d] = type(mover)(mover.color, mover.kind, False)
                truth[o] = None
                entry = {"m": base, "r": reveal.value if reveal else None,
                         "c": victim.kind.value if victim is not None else None}
                if randomised:
                    entry["rand"] = 1
                if record_scores and not randomised:
                    entry["s"] = score_of(info)
                if clock and not randomised:
                    entry["t"] = round(eng.last_ms)
                moves.append(entry)
                if ponders[side]:
                    try:
                        eng.ponder(tokens[side])
                    except EngineError:
                        pass  # a failed ponder start surfaces at the engine's next go
                side = side.opponent
    finally:
        for e in engines.values():
            e.close()
    return result, reason, moves


def elo_from_score(s):
    s = min(max(s, 1e-6), 1 - 1e-6)
    return -400 * math.log10(1 / s - 1)


def summarize(results, a, b):
    """results: list of (pair_index, a_is_red, score_for_a)."""
    n = len(results)
    if not n:
        return {}
    w = sum(1 for r in results if r[2] == 1.0)
    d = sum(1 for r in results if r[2] == 0.5)
    l = n - w - d
    s = (w + 0.5 * d) / n
    var = (w * (1 - s) ** 2 + d * (0.5 - s) ** 2 + l * (0 - s) ** 2) / n
    se = math.sqrt(var / n) if n > 1 else 0.5
    # Pentanomial over complete pairs.
    pairs = {}
    for pi, red, sc in results:
        pairs.setdefault(pi, []).append(sc)
    ps = [sum(v) / 2 for v in pairs.values() if len(v) == 2]
    pent = None
    if len(ps) > 1:
        m = sum(ps) / len(ps)
        pv = sum((x - m) ** 2 for x in ps) / len(ps)
        pse = math.sqrt(pv / len(ps))
        pent = dict(pairs=len(ps), score=m, elo=elo_from_score(m), elo_lo=elo_from_score(m - 1.96 * pse),
                    elo_hi=elo_from_score(m + 1.96 * pse))
    return dict(a=a, b=b, games=n, w=w, d=d, l=l, score=s, elo=elo_from_score(s),
                elo_lo=elo_from_score(s - 1.96 * se), elo_hi=elo_from_score(s + 1.96 * se), pent=pent)


def sprt_llr(results, elo0, elo1):
    """Generalized SPRT log-likelihood ratio on complete pairs (pentanomial, normal approximation)."""
    pairs = {}
    for pi, red, sc in results:
        pairs.setdefault(pi, []).append(sc)
    ps = [sum(v) / 2 for v in pairs.values() if len(v) == 2]
    n = len(ps)
    if n < 50:  # small samples give degenerate variance estimates and spurious early stops
        return 0.0, n
    m = sum(ps) / n
    var = sum((x - m) ** 2 for x in ps) / n
    var = (n * var + 10 * 0.1) / (n + 10)  # weak prior: 10 pseudo-pairs at a typical pair variance
    s0 = 1 / (1 + 10 ** (-elo0 / 400))
    s1 = 1 / (1 + 10 ** (-elo1 / 400))
    return n * (s1 - s0) * (2 * m - s0 - s1) / (2 * var), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", action="append", required=True, help="name=path[:Opt=val,...] (exactly two)")
    ap.add_argument("--games", type=int, default=100, help="total games (rounded up to pairs)")
    ap.add_argument("--movetime", type=int, default=0)
    ap.add_argument("--tc", default="", help="base+inc in seconds, e.g. 10+0.1")
    ap.add_argument("--depth", type=int, default=0)
    ap.add_argument("--nodes", type=int, default=0)
    ap.add_argument("--hash", type=int, default=64)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scores", action="store_true", help="record engine scores per move")
    ap.add_argument("--resume", action="store_true", help="continue OUT/games.jsonl (same seed and engines)")
    ap.add_argument("--ponder", action="store_true", help="both engines think on the opponent's time (go infinite)")
    ap.add_argument("--random-plies", type=int, default=0,
                    help="data generation: up to this many random opening plies per deal (same for both games of a pair)")
    ap.add_argument("--sprt", nargs=2, type=float, metavar=("ELO0", "ELO1"),
                    help="stop early when the GSPRT (alpha=beta=0.05) accepts H0 or H1")
    args = ap.parse_args()
    if len(args.engine) != 2:
        sys.exit("need exactly two --engine")
    A, B = (parse_engine(s) for s in args.engine)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    rules = NativeRules()
    npairs = (args.games + 1) // 2
    rng = random.Random(args.seed)
    seeds = [rng.getrandbits(63) for _ in range(npairs)]
    tc = None
    if args.tc:
        b, _, i = args.tc.partition("+")
        tc = (round(float(b) * 1000), round(float(i or 0) * 1000))
        go_args, timeout = "", 0
    elif args.movetime:
        go_args, timeout = f"movetime {args.movetime}", args.movetime / 1000 * 3 + 5
    elif args.depth:
        go_args, timeout = f"depth {args.depth}", 600
    elif args.nodes:
        go_args, timeout = f"nodes {args.nodes}", 600
    else:
        sys.exit("one of --tc/--movetime/--depth/--nodes is required")
    results, lock = [], threading.Lock()
    done = set()
    gpath = out / "games.jsonl"
    if args.resume and gpath.exists():
        keep = []
        for line in gpath.read_text().splitlines():
            try:
                g = json.loads(line)
            except json.JSONDecodeError:
                continue
            i, a_red = g["pair"], g["red"] == A["name"]
            if i >= npairs or str(seeds[i]) != g["seed"] or (i, a_red) in done:
                continue
            done.add((i, a_red))
            results.append((i, a_red, g["result"] if a_red else 1 - g["result"]))
            keep.append(line)
        gpath.write_text("".join(l + "\n" for l in keep))
        print(f"resume: {len(keep)} games kept", flush=True)
    jobs = queue.Queue()
    for i, sd in enumerate(seeds):
        for a_red in (True, False):
            if (i, a_red) not in done:
                jobs.put((i, sd, a_red))
    games_file = gpath.open("a")
    void_file = (out / "void.jsonl").open("a")
    retries = {}
    t0 = time.time()

    stop = threading.Event()
    bounds = (math.log(0.05 / 0.95), math.log(0.95 / 0.05))

    def worker():
        while not stop.is_set():
            try:
                i, sd, a_red = jobs.get_nowait()
            except queue.Empty:
                return
            setup = Setup.from_seed(sd)
            red, black = (A, B) if a_red else (B, A)
            try:
                res, reason, moves = play_game(rules, setup, red, black, go_args, args.hash, args.threads, timeout,
                                               args.scores, tc, args.ponder, args.random_plies, sd)
            except Exception as e:  # harness/engine start-up failure
                res, reason, moves = None, f"harness error: {e}", []
            if res is None or reason.startswith("engine failure"):
                with lock:
                    void_file.write(json.dumps(dict(pair=i, seed=str(sd), red=red["name"], black=black["name"],
                                                    reason=reason, plies=len(moves), moves=moves)) + "\n")
                    void_file.flush()
                    retry = retries.get((i, a_red), 0) < 1
                    retries[(i, a_red)] = retries.get((i, a_red), 0) + 1
                    print(f"void game pair {i} ({reason}){'; replaying' if retry else ''}", flush=True)
                if retry:
                    jobs.put((i, sd, a_red))
                continue
            sa = res if a_red else 1 - res
            with lock:
                results.append((i, a_red, sa))
                games_file.write(json.dumps(dict(pair=i, seed=str(sd), red=red["name"], black=black["name"],
                                                 result=res, reason=reason, plies=len(moves), moves=moves)) + "\n")
                games_file.flush()
                n = len(results)
                if args.sprt and not stop.is_set():
                    llr, npr = sprt_llr(results, *args.sprt)
                    if llr <= bounds[0] or llr >= bounds[1]:
                        stop.set()
                        print(f"SPRT {'H1 accepted' if llr >= bounds[1] else 'H0 accepted'}: LLR {llr:.2f} after {npr} pairs", flush=True)
                if n % 10 == 0 or n == 2 * npairs:
                    s = summarize(results, A["name"], B["name"])
                    pe = s["pent"]
                    extra = f" pent {pe['elo']:+.0f} [{pe['elo_lo']:+.0f},{pe['elo_hi']:+.0f}] ({pe['pairs']} pairs)" if pe else ""
                    print(f"[{time.time()-t0:7.0f}s] {A['name']} vs {B['name']}: {n} games +{s['w']}={s['d']}-{s['l']} "
                          f"score {s['score']:.3f} elo {s['elo']:+.0f} [{s['elo_lo']:+.0f},{s['elo_hi']:+.0f}]{extra}", flush=True)

    threads = [threading.Thread(target=worker) for _ in range(args.concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    games_file.close()
    s = summarize(results, A["name"], B["name"])
    reasons = {}
    for line in (out / "games.jsonl").open():
        g = json.loads(line)
        key = g["reason"].split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
    s["reasons"] = reasons
    if args.sprt:
        llr, npr = sprt_llr(results, *args.sprt)
        s["sprt"] = dict(elo0=args.sprt[0], elo1=args.sprt[1], llr=llr, pairs=npr,
                         result="H1" if llr >= bounds[1] else "H0" if llr <= bounds[0] else "inconclusive")
    s["args"] = vars(args)
    (out / "summary.json").write_text(json.dumps(s, indent=2) + "\n")
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
