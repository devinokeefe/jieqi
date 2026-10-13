#!/usr/bin/env python3
"""Re-label self-play records with another engine's search score (separate UCI process).

Reads jqe TrainRecords (112 bytes), rebuilds each position as a FEN from the side to move's
view (board, pools as that side knows them, no-capture clock), asks the labeller for
"go <limit>" and stores its final score (side-to-move perspective) in place of ours.
Game results and every other field are kept. Mate scores map to +-(32000 - plies).

Example:
  python3 engine/tools/label.py --in engine/data/rl-it008.bin --out engine/data/ab-it008.bin \
      --engine abjchess --go "nodes 400" --workers 20 --stride 2
"""
import argparse
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import match as M  # noqa: E402

REC = np.dtype([("board", "u1", 90), ("stm", "u1"), ("urn", "i1", (2, 6)), ("score", "<i2"), ("result", "i1"),
                ("flags", "u1"), ("ply", "<u2"), ("move", "<u2"), ("nocap", "u1")])
assert REC.itemsize == 112
CHARS = ".KRNBACPX"
POOL_ORDER = [0, 3, 4, 5, 1, 2]  # slots R N B A C P -> FEN order R A C P N B
POOL_CH = "RNBACP"


def to_fen(r):
    rows = []
    b = r["board"]
    for rank in range(9, -1, -1):
        out, empty = "", 0
        for f in range(9):
            p = int(b[rank * 9 + f])
            if not p:
                empty += 1
                continue
            if empty:
                out += str(empty)
                empty = 0
            c = CHARS[p & 15]
            out += c if (p >> 4) == 0 else c.lower()
        if empty:
            out += str(empty)
        rows.append(out)
    pools = ""
    for c in range(2):
        for sl in POOL_ORDER:
            n = int(r["urn"][c][sl])
            if n > 0:
                ch = POOL_CH[sl]
                pools += (ch if c == 0 else ch.lower()) + str(n)
    return "/".join(rows) + (" w " if r["stm"] == 0 else " b ") + (pools or "-") + f" {int(r['nocap'])} 1"


def parse_score(info):
    p = info.split()
    if "score" not in p:
        return None
    i = p.index("score")
    kind, v = p[i + 1], int(p[i + 2])
    if kind == "cp":
        return max(-20000, min(20000, v))
    if kind == "mate":
        return 32000 - (2 * v - 1) if v > 0 else -32000 + 2 * (-v)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", default="abjchess")
    ap.add_argument("--go", default="nodes 400")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--stride", type=int, default=1, help="label every k-th record (others dropped)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=30)
    args = ap.parse_args()

    recs = np.fromfile(args.inp, dtype=REC)[:: args.stride]
    if args.limit:
        recs = recs[: args.limit]
    recs = recs.copy()
    n = len(recs)
    ok = np.zeros(n, dtype=bool)
    spec = M.parse_engine(f"lab={args.engine}")
    next_i = [0]
    lock = threading.Lock()
    t0 = time.time()
    errors = [0]

    def worker():
        eng = M.Engine(spec["name"], spec["argv"], spec.get("cwd"), spec.get("options"), spec.get("pad", True))
        while True:
            with lock:
                i = next_i[0]
                if i >= n:
                    break
                next_i[0] += 1
                if i % 20000 == 0:
                    el = time.time() - t0
                    print(f"[{el:7.0f}s] {i}/{n} ({i / max(el, 1e-9):.0f}/s) errors {errors[0]}", flush=True)
            try:
                eng.send("position fen " + to_fen(recs[i]))
                eng.send("go " + args.go)
                deadline = time.monotonic() + args.timeout
                last = ""
                while True:
                    line = eng.lines.get(timeout=max(0.01, deadline - time.monotonic()))
                    if line is None:
                        raise M.EngineError("exited")
                    if line.startswith("info") and " score " in line:
                        last = line
                    if line.startswith("bestmove"):
                        break
                s = parse_score(last)
                if s is not None:
                    recs["score"][i] = s
                    ok[i] = True
            except Exception:
                with lock:
                    errors[0] += 1
                try:
                    eng.close()
                except Exception:
                    pass
                eng = M.Engine(spec["name"], spec["argv"], spec.get("cwd"), spec.get("options"), spec.get("pad", True))
        eng.close()

    threads = [threading.Thread(target=worker) for _ in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = recs[ok]
    out.tofile(args.out)
    print(f"done: {ok.sum()}/{n} labelled in {time.time() - t0:.0f}s, errors {errors[0]} -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
