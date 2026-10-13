#!/usr/bin/env python3
"""Expert-iteration loop for jqe: self-play with the current best net -> train on a sliding
window of recent self-play data -> gated promotion by a refereed match.

State lives in engine/rl/state.json; each iteration appends to engine/rl/log.jsonl.
Resumable: re-running continues from the recorded state. Example:
  python3 engine/train/rl.py --iters 3 --games 100000 --nodes 5000 --threads 28
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
ROOT = ENGINE.parent
PY = str(ROOT / ".venv/bin/python")
RL = ENGINE / "rl"


def run(cmd, log, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    with open(log, "a") as f:
        r = subprocess.run(list(map(str, cmd)), stdout=f, stderr=subprocess.STDOUT, **kw)
    if r.returncode != 0:
        raise SystemExit(f"command failed ({r.returncode}); see {log}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=1)
    ap.add_argument("--binary", default=str(ENGINE / "bin/jqe-v0.5"))
    ap.add_argument("--games", type=int, default=100000)
    ap.add_argument("--nodes", type=int, default=5000)
    ap.add_argument("--threads", type=int, default=28)
    ap.add_argument("--random", type=int, default=8)
    ap.add_argument("--window", type=int, default=3, help="number of most recent data files to train on")
    ap.add_argument("--epochs", type=float, default=6)
    ap.add_argument("--lam", type=float, default=0.7)
    ap.add_argument("--gate-games", type=int, default=400)
    ap.add_argument("--gate-movetime", type=int, default=100)
    ap.add_argument("--gate-concurrency", type=int, default=14)
    ap.add_argument("--extra-data", nargs="*", default=[], help="data files always included (e.g. v0)")
    ap.add_argument("--warm", action="store_true", help="initialise training from the current best net")
    ap.add_argument("--anchor", default="", help="external engine to measure each candidate against (e.g. pikafish-old)")
    ap.add_argument("--anchor-games", type=int, default=200)
    args = ap.parse_args()
    RL.mkdir(exist_ok=True)
    state_path = RL / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else dict(iter=0, best=None, data=[])
    binary = Path(args.binary)
    for _ in range(args.iters):
        it = state["iter"] + 1
        tag = f"it{it:03d}"
        log = RL / f"{tag}.log"
        t0 = time.time()
        # 1. Self-play with the current best net (classical eval when none yet).
        data = ENGINE / "data" / f"rl-{tag}.bin"
        if not data.exists() or data.stat().st_size == 0:
            sp = f"selfplay games {args.games} nodes {args.nodes} threads {args.threads} seed {1000 + it} random {args.random}"
            if state["best"]:
                sp += f" evalfile {state['best']}"
            sp += f" out {data}.part"
            Path(f"{data}.part").unlink(missing_ok=True)  # selfplay appends; never resume a partial file
            run(["nice", "-n", "5", binary] + sp.split(), log)
            shutil.move(f"{data}.part", data)
        t_sp = time.time() - t0
        state["data"].append(str(data))
        # 2. Train on the recent window (+ fixed extra data).
        files = args.extra_data + state["data"][-args.window:]
        netdir = ENGINE / "nets" / tag
        warm = ["--init", Path(state["best"]).with_suffix("") / "best.pt"] if args.warm and state["best"] else []
        run([PY, ENGINE / "train/train.py", *files, "--out", netdir, "--epochs", args.epochs, "--lam", args.lam, *warm], log)
        cand = ENGINE / "nets" / f"{tag}.jqn"
        shutil.copy(netdir / "best.jqn", cand)
        t_tr = time.time() - t0 - t_sp
        # 3. Gate against the current best.
        gate_dir = ENGINE / "runs" / f"gate-{tag}"
        opp = f"best={binary}" + (f":EvalFile={state['best']}" if state["best"] else "")
        run([sys.executable, ENGINE / "tools/match.py", "--engine", f"cand={binary}:EvalFile={cand}", "--engine", opp,
             "--games", args.gate_games, "--movetime", args.gate_movetime, "--concurrency", args.gate_concurrency,
             "--out", gate_dir], log)
        summary = json.loads((gate_dir / "summary.json").read_text())
        promoted = summary["score"] > 0.5
        anchor = None
        if args.anchor:
            adir = ENGINE / "runs" / f"anchor-{tag}"
            run([sys.executable, ENGINE / "tools/match.py", "--engine", f"cand={binary}:EvalFile={cand}", "--engine",
                 f"{args.anchor}={args.anchor}", "--games", args.anchor_games, "--movetime", args.gate_movetime,
                 "--concurrency", args.gate_concurrency, "--out", adir], log)
            a = json.loads((adir / "summary.json").read_text())
            anchor = dict(opp=args.anchor, score=a["score"], elo=a["elo"], lo=a["elo_lo"], hi=a["elo_hi"])
        rec = dict(iter=it, data=str(data), train_files=files, candidate=str(cand), previous=state["best"],
                   gate=dict(score=summary["score"], elo=summary["elo"], lo=summary["elo_lo"], hi=summary["elo_hi"],
                             games=summary["games"], pent=summary.get("pent")),
                   anchor=anchor, promoted=promoted, sec_selfplay=round(t_sp), sec_train=round(t_tr), sec_total=round(time.time() - t0))
        if promoted:
            state["best"] = str(cand)
        state["iter"] = it
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        with open(RL / "log.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
