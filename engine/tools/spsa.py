#!/usr/bin/env python3
"""SPSA tuning of jqe search parameters with refereed duplicate pairs.

Each iteration draws a random sign vector D, plays one duplicate pair (same seeded deal,
colours swapped) between theta + c_k*D and theta - c_k*D, and moves theta along D by the
pair result. Schedules follow the usual SPSA form (alpha 0.602, gamma 0.101,
A = 10% of the iterations); c_end / r_end set the final perturbation and learning rate,
with a_end = r_end * c_end^2. Workers update theta asynchronously under a lock.

Example:
  python3 engine/tools/spsa.py --binary engine/bin/jqe-v0.7 --net engine/nets/v1.jqn \
      --iters 10000 --movetime 40 --concurrency 4 --out engine/runs/spsa-1
"""
import argparse
import json
import random
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import match as M  # noqa: E402

# name: c_end (final perturbation, in parameter units)
DEFAULT_PARAMS = {
    "ChanceK": 40, "RfpMargin": 10, "RfpDepth": 1, "NullDiv": 25, "FutBase": 15, "FutMul": 15,
    "LmpBase": 1, "LmrBase": 10, "LmrDiv": 20, "AspDelta": 5, "HistDiv": 1000,
    "DeltaMargin": 30, "BadCapMargin": 20,
}


def engine_spins(binary):
    """name -> (default, min, max) from the engine's UCI option list."""
    import subprocess
    out = subprocess.run([binary], input="uci\nquit\n", capture_output=True, text=True).stdout
    spins = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 10 and p[0] == "option" and p[3:5] == ["type", "spin"]:
            spins[p[2]] = (int(p[6]), int(p[8]), int(p[10]) if len(p) > 10 else int(p[9]))
    return spins


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True)
    ap.add_argument("--net", default="")
    ap.add_argument("--params", default="", help="comma list name[:c_end]; default: built-in set")
    ap.add_argument("--iters", type=int, default=10000)
    ap.add_argument("--movetime", type=int, default=40)
    ap.add_argument("--tc", default="", help="BASE+INC seconds: clock games instead of --movetime (with --fixed NodesTime=N "
                    "the clock runs on nodes and the run does not depend on host load)")
    ap.add_argument("--hash", type=int, default=16)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--r-end", type=float, default=0.002)
    ap.add_argument("--init", default="", help="starting values name=v,... (default: engine defaults)")
    ap.add_argument("--fixed", default="", help="extra fixed engine options name=v,... for both sides")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    binary = str(Path(args.binary).resolve())
    spins = engine_spins(binary)
    chosen = {}
    if args.params:
        for item in args.params.split(","):
            name, _, c = item.partition(":")
            chosen[name] = float(c) if c else DEFAULT_PARAMS[name]
    else:
        chosen = dict(DEFAULT_PARAMS)
    names = list(chosen)
    for n in names:
        if n not in spins:
            sys.exit(f"unknown parameter {n}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    N, alpha, gamma = args.iters, 0.602, 0.101
    A = 0.1 * N
    c_end = {n: float(chosen[n]) for n in names}
    a_end = {n: args.r_end * c_end[n] ** 2 for n in names}
    c0 = {n: c_end[n] * N ** gamma for n in names}
    a0 = {n: a_end[n] * (A + N) ** alpha for n in names}
    if state_path.exists():
        st = json.loads(state_path.read_text())
        theta, k_done = st["theta"], st["iter"]
    else:
        theta, k_done = {n: float(spins[n][0]) for n in names}, 0
        for kv in filter(None, args.init.split(",")):
            n, _, v = kv.partition("=")
            theta[n] = float(v)
    lo = {n: spins[n][1] for n in names}
    hi = {n: spins[n][2] for n in names}

    rules = M.NativeRules()
    lock = threading.Lock()
    counter = [k_done]
    log = (out / "log.jsonl").open("a")
    rng_master = random.Random(args.seed + k_done)
    t0 = time.time()
    go_args, timeout = f"movetime {args.movetime}", args.movetime / 1000 * 3 + 5
    tc = None
    if args.tc:
        b, _, i = args.tc.partition("+")
        tc = (float(b) * 1000, float(i or 0) * 1000)
    base_opts = {"EvalFile": str(Path(args.net).resolve())} if args.net else {}
    for kv in filter(None, args.fixed.split(",")):
        n, _, v = kv.partition("=")
        base_opts[n] = v
    totals = [0, 0]  # sum of results, pairs

    def spec(name, values):
        return dict(argv=[binary], cwd=str(Path(binary).parent), name=name,
                    options={**base_opts, **{n: str(int(round(v))) for n, v in values.items()}})

    def worker(wid):
        while True:
            with lock:
                k = counter[0]
                if k >= N:
                    return
                counter[0] += 1
                ck = {n: c0[n] / (k + 1) ** gamma for n in names}
                ak = {n: a0[n] / (A + k + 1) ** alpha for n in names}
                delta = {n: rng_master.choice((-1, 1)) for n in names}
                seed = rng_master.getrandbits(63)
                plus = {n: min(hi[n], max(lo[n], theta[n] + ck[n] * delta[n])) for n in names}
                minus = {n: min(hi[n], max(lo[n], theta[n] - ck[n] * delta[n])) for n in names}
            setup = M.Setup.from_seed(seed)
            P, Q = spec("plus", plus), spec("minus", minus)
            try:
                r1, _, _ = M.play_game(rules, setup, P, Q, go_args, args.hash, 1, timeout, tc=tc)
                r2, _, _ = M.play_game(rules, setup, Q, P, go_args, args.hash, 1, timeout, tc=tc)
            except Exception as e:  # harness trouble: the pair is skipped, the iteration counts as a draw
                print(f"pair {k} skipped: {e}", flush=True)
                r1 = r2 = 0.5
            result = (r1 - 0.5) + (0.5 - r2)  # plus-side wins minus losses over the pair, in [-1, 1]
            result *= 2  # pair result in units of games: [-2, 2]
            with lock:
                for n in names:
                    theta[n] = min(hi[n], max(lo[n], theta[n] + ak[n] * result * delta[n] / ck[n]))
                totals[0] += result
                totals[1] += 1
                done = totals[1] + k_done
                if done % 10 == 0 or done == N:  # a restart resumes from here
                    state_path.write_text(json.dumps(dict(iter=done, theta=theta), indent=1))
                if done % 50 == 0 or done == N:
                    rec = dict(iter=done, sec=round(time.time() - t0), theta={n: round(v, 2) for n, v in theta.items()})
                    log.write(json.dumps(rec) + "\n")
                    log.flush()
                    print(f"[{time.time()-t0:7.0f}s] iter {done}/{N} " +
                          " ".join(f"{n}={v:.1f}" for n, v in theta.items()), flush=True)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = {n: int(round(v)) for n, v in theta.items()}
    (out / "final.json").write_text(json.dumps(final, indent=1) + "\n")
    print("final", json.dumps(final))
    print("as engine options:", ",".join(f"{n}={v}" for n, v in final.items()))


if __name__ == "__main__":
    main()
