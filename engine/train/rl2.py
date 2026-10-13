#!/usr/bin/env python3
"""Data-scaling RL loop for jqe (D090): two cooperating processes sharing engine/rl/state2.json.

  gen    self-play chunks forever with the current best net (re-read at each chunk start).
  train  whenever a chunk has been added since the last candidate: train FT-<--ft> (256) on the base files
         plus every chunk, validate on the fixed held-out file, gate vs the current best at
         300 ms, and promote when the gate's pentanomial Elo is > 0 and held-out loss improved.

State keys: best (net path), best_tag, best_val, base (always-included data files), chunks
(finished chunk files, in order), val_file, iter (last candidate number), trained (chunks used by
the last candidate), stop (set true to make both loops exit at the next check).
Training uses a sliding window: the newest files (chunks, then base) whose raw records total at most
--max-raw. train.py streams the window from disk (--stream, bounded RAM); epochs shrink as the window
grows so that epochs * raw records stays within --epoch-budget (at most --epochs).
Every candidate appends a line to engine/rl/log2.jsonl.

  .venv/bin/python engine/train/rl2.py init --best engine/nets/it009.jqn --tag it009 --iter 9 ...
  .venv/bin/python engine/train/rl2.py gen --binary engine/bin/jqe-v0.11f --threads 20
  .venv/bin/python engine/train/rl2.py train --binary engine/bin/jqe-v0.11f
"""
import argparse
import fcntl
import json
import shutil
import subprocess
import time
import zlib
from contextlib import contextmanager
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
ROOT = ENGINE.parent
PY = str(ROOT / ".venv/bin/python")
RL = ENGINE / "rl"
STATE = RL / "state2.json"
LOCK = RL / "state2.lock"
LOG = RL / "log2.jsonl"


@contextmanager
def locked_state():
    RL.mkdir(exist_ok=True)
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        st = json.loads(STATE.read_text()) if STATE.exists() else {}
        yield st
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2) + "\n")
        tmp.replace(STATE)


def read_state():
    with locked_state() as st:
        return dict(st)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def cmd_init(a):
    with locked_state() as st:
        if st and not a.force:
            raise SystemExit(f"{STATE} exists (use --force)")
        st.clear()
        st.update(best=str(Path(a.best).resolve()), best_tag=a.tag, best_val=a.best_val, base=[str(Path(p).resolve()) for p in a.base],
                  chunks=[str(Path(p).resolve()) for p in a.chunks], val_file=str(Path(a.val_file).resolve()), iter=a.iter,
                  trained=[str(Path(p).resolve()) for p in a.trained], stop=False)
    print(json.dumps(read_state(), indent=2))


def cmd_gen(a):
    data = ENGINE / "data"
    while True:
        st = read_state()
        if st.get("stop"):
            print("stop set; generator exits", flush=True)
            return
        tag = st["best_tag"]
        k = 0
        while (data / f"big-{tag}-{k}.bin").exists() or (data / f"big-{tag}-{k}.bin.part").exists():
            k += 1
        out = data / f"big-{tag}-{k}.bin"
        seed = zlib.crc32(f"{tag}-{k}".encode()) & 0x7FFFFFFF
        log = ENGINE / "runs" / f"gen_{tag}_{k}.log"
        cmd = ["nice", "-n", "5", a.binary, "selfplay", "games", a.games, "nodes", a.nodes, "threads", a.threads, "seed", seed,
               "random", a.random, "evalfile", st["best"], "out", str(out) + ".part"]
        print(now(), "+", " ".join(map(str, cmd)), flush=True)
        with open(log, "w") as f:
            r = subprocess.run(list(map(str, cmd)), stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
        if r.returncode != 0 or "selfplay done" not in log.read_text():
            raise SystemExit(f"self-play failed; see {log}")
        Path(str(out) + ".part").replace(out)
        with locked_state() as s2:
            s2["chunks"].append(str(out))
        print(now(), "chunk done", out, flush=True)


def best_val(log_path):
    log = [json.loads(l) for l in open(log_path) if l.startswith("{")]
    b = min(log, key=lambda r: r["val"])
    return b["val"], b["epoch"], len(log)


def window(files, max_raw):
    """Newest files whose raw record count (112-byte records) totals at most max_raw (always >= 1 file)."""
    out, total = [], 0
    for f in reversed(files):
        n = Path(f).stat().st_size // 112
        if out and total + n > max_raw:
            break
        out.append(f)
        total += n
    return out[::-1]


def cmd_train(a):
    while True:
        st = read_state()
        if st.get("stop"):
            print("stop set; trainer exits", flush=True)
            return
        new = [c for c in st["chunks"] if c not in st["trained"]]
        if not new:
            time.sleep(60)
            continue
        it = st["iter"] + 1
        name = f"cand-it{it:03d}"
        data = window(st["base"] + st["chunks"], a.max_raw)
        raw = sum(Path(f).stat().st_size // 112 for f in data)
        epochs = round(min(a.epochs, max(1.0, a.epoch_budget / raw)), 2)
        tlog = ENGINE / "runs" / f"train_{name}.log"
        cmd = [PY, ENGINE / "train/train.py", *data, "--val-file", st["val_file"], "--out", ENGINE / "nets" / name,
               "--ft", a.ft, "--epochs", epochs, "--lam", a.lam, "--stream", a.stream]
        print(now(), "+", " ".join(map(str, cmd)), flush=True)
        for attempt in range(2):  # one retry: a crashed run (e.g. a transient CUDA error) is restarted from scratch
            with open(tlog, "w") as f:
                r = subprocess.run(list(map(str, cmd)), stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
            if r.returncode == 0:
                break
            print(now(), f"training attempt {attempt + 1} failed (exit {r.returncode})", flush=True)
        if r.returncode != 0:
            raise SystemExit(f"training failed; see {tlog}")
        cand = ENGINE / "nets" / f"{name}.jqn"
        shutil.copy(ENGINE / "nets" / name / "best.jqn", cand)
        val, ep, eps = best_val(tlog)
        print(now(), f"{name}: val {val:.6f} (epoch {ep}/{eps}); best_val {st['best_val']}", flush=True)
        gdir = ENGINE / "runs" / f"{name}-gate-{a.gate_movetime}"
        if gdir.exists():
            shutil.rmtree(gdir)
        gcmd = ["python3", ENGINE / "tools/match.py", "--engine", f"{name}={a.binary}:EvalFile={cand}",
                "--engine", f"{st['best_tag']}={a.binary}:EvalFile={st['best']}", "--games", a.gate_games,
                "--movetime", a.gate_movetime, "--concurrency", a.gate_concurrency, "--seed", 10000 + it, "--out", gdir]
        print(now(), "+", " ".join(map(str, gcmd)), flush=True)
        with open(ENGINE / "runs" / f"gate_{name}.log", "w") as f:
            r = subprocess.run(list(map(str, gcmd)), stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
        if r.returncode != 0:
            raise SystemExit(f"gate failed; see runs/gate_{name}.log")
        s = json.loads((gdir / "summary.json").read_text())
        pent = s["pent"]
        better_val = st["best_val"] is None or val < st["best_val"]
        promote = pent["elo"] > 0 and better_val
        rec = dict(time=now(), iter=it, cand=str(cand), data=len(data), raw=raw, epochs=epochs, files=[Path(f).name for f in data], chunks=len(st["chunks"]), val=val, val_epoch=ep,
                   prev_best=st["best"], prev_val=st["best_val"], gate=dict(games=s["games"], elo=s["elo"], lo=s["elo_lo"], hi=s["elo_hi"],
                   pent=pent["elo"], pent_lo=pent["elo_lo"], pent_hi=pent["elo_hi"]), promoted=promote)
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(now(), json.dumps(rec), flush=True)
        with locked_state() as s2:
            s2["iter"] = it
            s2["trained"] = list(st["chunks"])
            if promote:
                tag = f"it{it:03d}"
                dst = ENGINE / "nets" / f"{tag}.jqn"
                shutil.copy(cand, dst)
                s2.update(best=str(dst), best_tag=tag, best_val=val)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--best", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--best-val", type=float, default=None)
    p.add_argument("--base", nargs="*", default=[])
    p.add_argument("--chunks", nargs="*", default=[])
    p.add_argument("--trained", nargs="*", default=[])
    p.add_argument("--val-file", required=True)
    p.add_argument("--iter", type=int, required=True)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("gen")
    p.add_argument("--binary", required=True)
    p.add_argument("--games", type=int, default=200000)
    p.add_argument("--nodes", type=int, default=5000)
    p.add_argument("--threads", type=int, default=20)
    p.add_argument("--random", type=int, default=8)
    p = sub.add_parser("train")
    p.add_argument("--binary", required=True)
    p.add_argument("--epochs", type=float, default=6)
    p.add_argument("--ft", type=int, default=256, help="feature-transformer width of candidates")
    p.add_argument("--lam", type=float, default=0.7)
    p.add_argument("--gate-games", type=int, default=400)
    p.add_argument("--gate-movetime", type=int, default=300)
    p.add_argument("--gate-concurrency", type=int, default=6)
    p.add_argument("--max-raw", type=int, default=400_000_000, help="training window in raw records")
    p.add_argument("--epoch-budget", type=float, default=600e6, help="max epochs * raw records per candidate")
    p.add_argument("--stream", type=int, default=30_000_000, help="train.py --stream group size (raw records)")
    a = ap.parse_args()
    a.binary = str(Path(a.binary).resolve()) if hasattr(a, "binary") else None
    {"init": cmd_init, "gen": cmd_gen, "train": cmd_train}[a.cmd](a)


if __name__ == "__main__":
    main()
