#!/usr/bin/env python3
"""Randomised cross-check of the universe adapter against the project's native referee.

Original code (jieqi project). Plays random legal games under the native rules with seeded hidden
deals, builds every player's observation tokens exactly as engine/tools/match.py does, and after each
ply asks the adapter (debug command `d`) to rebuild the side-to-move's view. Checks:

  * the reconstructed public board equals the referee's public board;
  * the universe move generator's legal set equals the native legal set (rule compatibility);
  * the observer pools equal ARMY - public reveals - identities this observer captured face down;
  * optionally (--go-every N) that the AI's bestmove is legal for the referee.

Usage: python3 adapters/universe/crosscheck.py --games 20 --seed 1 [--go-every 10 --movetime 50]
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JIEQI_NATIVE_LIBRARY", str(ROOT / "build/release/lib/libjieqi_rules.so"))

from jieqi.native import GameStatus, NativeGame, NativeRules  # noqa: E402
from jieqi.setup import Color, Setup, square  # noqa: E402

START_FEN = "xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/9/X1X1X1X1X/1X5X1/9/XXXXKXXXX w R2A2C2P5N2B2r2a2c2p5n2b2 0 1"
ARMY = Counter({"R": 2, "N": 2, "B": 2, "A": 2, "C": 2, "P": 5})


class Adapter:
    def __init__(self):
        self.proc = subprocess.Popen([str(Path(__file__).resolve().parent / "run.sh")], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1)
        self.send("uci")
        self.until("uciok")
        self.send("isready")
        self.until("readyok")

    def send(self, line):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def until(self, prefix):
        lines = []
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("adapter exited")
            line = line.rstrip("\n")
            lines.append(line)
            if line.startswith(prefix):
                return line, lines

    def close(self):
        self.send("quit")
        self.proc.wait(timeout=5)


def pool_string(counter, color):
    s = "".join(sorted(counter.elements()))
    return s if color is Color.RED else s.lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-plies", type=int, default=240)
    ap.add_argument("--go-every", type=int, default=0)
    ap.add_argument("--movetime", type=int, default=50)
    args = ap.parse_args()

    rules = NativeRules()
    rng = random.Random(args.seed)
    adapter = Adapter()
    stats = Counter()
    problems = []
    for g in range(args.games):
        setup = Setup.from_seed(rng.getrandbits(63))
        truth = list(setup.board)
        public = "".join("." if p is None else (("X" if p.color is Color.RED else "x") if p.hidden else p.code())
                         for p in truth)
        tokens = {Color.RED: [], Color.BLACK: []}
        revealed = {Color.RED: Counter(), Color.BLACK: Counter()}
        learned = {Color.RED: Counter(), Color.BLACK: Counter()}  # by capturer: victims' kinds
        with NativeGame(rules, public, Color.RED) as game:
            side = Color.RED
            for ply in range(args.max_plies):
                snap = game.snapshot()
                if snap.status is not GameStatus.ONGOING:
                    stats["ended_" + snap.status.name] += 1
                    break
                adapter.send("position fen " + START_FEN + (" moves " + " ".join(tokens[side]) if tokens[side] else ""))
                adapter.send("d")
                line, _ = adapter.until("debug ")
                d = json.loads(line[6:])
                stats["positions"] += 1
                where = f"game {g} ply {ply} ({side.value} to move)"
                if "error" in d:
                    problems.append(f"{where}: adapter error {d['error']}")
                    break
                if d["board"] != snap.board:
                    problems.append(f"{where}: board mismatch\n  native  {snap.board}\n  adapter {d['board']}")
                native_legal = sorted(rules.legal_moves(snap.board, side))
                if d["legal"] != native_legal:
                    extra = sorted(set(d["legal"]) - set(native_legal))
                    missing = sorted(set(native_legal) - set(d["legal"]))
                    problems.append(f"{where}: legal-set mismatch, universe-only {extra}, native-only {missing}, board {snap.board}")
                    stats["legal_mismatch"] += 1
                if d["selectable"] != d["legal"]:
                    stats["repetition_forbidden_positions"] += 1
                expected = {}
                for color in (Color.RED, Color.BLACK):
                    remaining = ARMY - revealed[color]
                    if color is not side:
                        remaining = remaining - learned[side]
                    expected[color.value] = pool_string(remaining, color)
                if d["pools"] != expected:
                    problems.append(f"{where}: pools {d['pools']} != expected {expected}")
                if d["ruleNotes"]:
                    problems.append(f"{where}: rule notes {d['ruleNotes']}")
                if d["inCheck"] != rules.in_check(snap.board, side):
                    problems.append(f"{where}: in-check disagreement")
                if args.go_every and ply % args.go_every == 0:
                    t0 = time.monotonic()
                    adapter.send(f"go movetime {args.movetime}")
                    line, _ = adapter.until("bestmove")
                    stats["go_calls"] += 1
                    ms = int((time.monotonic() - t0) * 1000)
                    stats["go_ms_total"] += ms
                    stats["go_ms_max"] = max(stats["go_ms_max"], ms)
                    mv = line.split()[1]
                    if mv not in native_legal:
                        problems.append(f"{where}: AI move {mv} not legal for the referee")

                # Random legal move; captures are favoured so face-down captures are common.
                caps = [m for m in native_legal if snap.board[square(m[2:])] != "."]
                mv = rng.choice(caps) if caps and rng.random() < 0.5 else rng.choice(native_legal)
                o, t = square(mv[:2]), square(mv[2:])
                mover, victim = truth[o], truth[t]
                reveal = mover.kind if mover.hidden else None
                game.advance(mv, reveal)
                own = opp = mv
                if reveal is not None:
                    letter = reveal.value if side is Color.RED else reveal.value.lower()
                    own += letter
                    opp += letter
                    revealed[side][reveal.value] += 1
                    stats["reveals"] += 1
                if victim is not None and victim.hidden:
                    own += victim.kind.value if victim.color is Color.RED else victim.kind.value.lower()
                    learned[side][victim.kind.value] += 1
                    stats["hidden_captures"] += 1
                tokens[side].append(own)
                tokens[side.opponent].append(opp)
                truth[t] = type(mover)(mover.color, mover.kind, False)
                truth[o] = None
                side = side.opponent
            else:
                stats["max_plies"] += 1
    adapter.close()
    print(json.dumps(dict(stats), indent=1))
    if stats["go_calls"]:
        print(f"go latency mean {stats['go_ms_total'] / stats['go_calls']:.1f} ms, max {stats['go_ms_max']} ms "
              f"at movetime {args.movetime}")
    for p in problems[:30]:
        print("PROBLEM", p)
    print(f"{len(problems)} problems in {stats['positions']} positions")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
