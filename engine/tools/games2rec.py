#!/usr/bin/env python3
"""Training records from refereed games.

  python3 engine/tools/games2rec.py RUN [RUN ...] --out FILE.bin [--side NAME ...] [--jqe engine/build/jqe]

Replays the games of engine/runs/RUN/games.jsonl (played with match.py --scores) through the referee, rebuilds what
each mover had been told, and appends one 112-byte TrainRecord (engine/src/selfplay.cpp, engine/train/train.py) for
every position searched by the chosen engines (default: every engine with recorded scores): board and urns as that
engine saw them, its recorded score, the game result from its side. The observation is not re-implemented here: a
jqe process is given the same `position ... moves ...` line as in the game and its `d` output is parsed.
The record's move field is left 0 and the depth bits of flags are 0 (training uses neither).
"""
import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import match  # noqa: E402
from match import Color, NativeGame, NativeRules, Setup, START_FEN, square  # noqa: E402

CH = ".KRNBACPX"
URN_INIT = {"R": 2, "N": 2, "B": 2, "A": 2, "C": 2, "P": 5}


class Viewer:
    """A jqe process used as the observation model: tokens in, FEN of its internal position out."""

    def __init__(self, path):
        self.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.p.stdin.write("uci\n")
        self.p.stdin.flush()
        for line in self.p.stdout:
            if line.startswith("uciok"):
                break

    def fen(self, events):
        tokens = [t + "x" if rev and len(t) == 5 else t for t, rev in events]
        self.p.stdin.write("position fen " + START_FEN + (" moves " + " ".join(tokens) if tokens else "") + "\nd\n")
        self.p.stdin.flush()
        for line in self.p.stdout:
            if line.startswith("fen "):
                return line[4:].strip()
        raise RuntimeError("viewer exited")

    def close(self):
        try:
            self.p.stdin.write("quit\n")
            self.p.stdin.flush()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def record(fen, score, result, in_check, capture, reveal, ply):
    rows, stm, pools, nocap = fen.split()[:4]
    board = bytearray(90)
    dark = [0, 0]
    for i, row in enumerate(rows.split("/")):
        rank, f = 9 - i, 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
                continue
            colour = 0 if ch.isupper() else 1
            code = CH.index(ch.upper())
            if code == 8:
                dark[colour] += 1
            board[rank * 9 + f] = code | (colour << 4)
            f += 1
        if f != 9:
            raise ValueError("bad fen row " + row)
    urn = [[0] * 6, [0] * 6]
    if pools != "-":
        i = 0
        while i < len(pools):
            ch = pools[i]
            j = i + 1
            while j < len(pools) and pools[j].isdigit():
                j += 1
            urn[0 if ch.isupper() else 1][CH.index(ch.upper()) - 2] = int(pools[i + 1:j])
            i = j
    me = 0 if stm == "w" else 1
    # The mover knows the opponent's face-down pieces exactly; its own urn may also hold pieces it lost unseen.
    if sum(urn[1 - me]) != dark[1 - me] or sum(urn[me]) < dark[me]:
        raise ValueError(f"urn / board mismatch in {fen}")
    flags = (1 if in_check else 0) | (2 if capture else 0) | (4 if reveal else 0)
    return (bytes(board) + struct.pack("<B6b6bhbBHHB", me, *urn[0], *urn[1], max(-32000, min(32000, score)), result, flags,
                                       ply, 0, min(int(nocap), 255)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--side", action="append", help="engine name(s) whose positions are written (default: all with scores)")
    ap.add_argument("--jqe", default="")
    args = ap.parse_args()
    snapshots = sorted((ROOT / "engine/bin").glob("jqe-v*"), key=os.path.getmtime)
    jqe = args.jqe or str(snapshots[-1] if snapshots else ROOT / "engine/build/jqe")
    rules = NativeRules()
    viewer = Viewer(jqe if os.path.isabs(jqe) else str(ROOT / jqe))
    ngames = nrec = skipped = 0
    tally = {}
    with open(args.out, "ab") as out:
        for run in args.runs:
            for line in open(ROOT / "engine/runs" / run / "games.jsonl"):
                g = json.loads(line)
                if g["reason"].startswith(("engine failure", "illegal move", "TIME", "MAX_PLIES")):
                    skipped += 1
                    continue
                setup = Setup.from_seed(int(g["seed"]))
                truth = list(setup.board)
                public = "".join("." if p is None else (("X" if p.color is Color.RED else "x") if p.hidden else p.code())
                                 for p in truth)
                tokens = {Color.RED: [], Color.BLACK: []}
                names = {Color.RED: g["red"], Color.BLACK: g["black"]}
                recs = []
                with NativeGame(rules, public, Color.RED) as game:
                    side = Color.RED
                    for ply, m in enumerate(g["moves"]):
                        mv = m["m"]
                        o, d = square(mv[:2]), square(mv[2:4])
                        mover, victim = truth[o], truth[d]
                        reveal = mover.kind if mover.hidden else None
                        if (reveal.value if reveal else None) != m.get("r"):
                            raise RuntimeError(f"{run} pair {g['pair']} ply {ply}: reveal differs from the record")
                        if m.get("s") is not None and (not args.side or names[side] in args.side):
                            snap = game.snapshot()
                            res = g["result"] if side is Color.RED else 1 - g["result"]
                            recs.append(record(viewer.fen(tokens[side]), int(m["s"]), int(round(2 * res - 1)),
                                               rules.in_check(snap.board, snap.turn), victim is not None, reveal is not None, ply))
                            t = tally.setdefault(names[side], [0, 0.0])
                            t[0] += 1
                        game.advance(mv[:4], reveal)
                        own_tok = opp_tok = mv[:4]
                        if reveal is not None:
                            letter = reveal.value if side is Color.RED else reveal.value.lower()
                            own_tok += letter
                            opp_tok += letter
                        if victim is not None and victim.hidden:
                            own_tok += victim.kind.value if victim.color is Color.RED else victim.kind.value.lower()
                        tokens[side].append((own_tok, reveal is not None))
                        tokens[side.opponent].append((opp_tok, reveal is not None))
                        truth[d] = type(mover)(mover.color, mover.kind, False)
                        truth[o] = None
                        side = side.opponent
                for r in recs:
                    out.write(r)
                nrec += len(recs)
                ngames += 1
                for c in (Color.RED, Color.BLACK):
                    if names[c] in tally:
                        tally[names[c]][1] += g["result"] if c is Color.RED else 1 - g["result"]
    viewer.close()
    print(f"{ngames} games ({skipped} skipped: failures, forfeits), {nrec} records -> {args.out}")
    for name, (n, pts) in sorted(tally.items()):
        print(f"  {name}: {n} records, {pts:.1f} game points")


if __name__ == "__main__":
    main()
