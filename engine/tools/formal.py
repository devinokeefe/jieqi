#!/usr/bin/env python3
"""Formal-profile match: one jqe build against one opponent on the held-out deal book, restart-safe.

  python3 engine/tools/formal.py NAME --jqe engine/bin/jqe-v0.15g --net engine/nets/it014.jqn --opp abjchess
      [--pairs 500] [--tc 60+0.6 | --movetime MS] [--threads 8] [--hash 1024] [--seed N] [--check]

The first start writes engine/runs/NAME/manifest.json (source commit, sha256 of both engines and their nets, deal
seed, settings, host) and then runs match.py; a later start with the same arguments checks the manifest and
continues the run (match.py --resume). Nothing is ever deleted. Progress lines also go to engine/runs/NAME/match.log.

The deal book: match.py draws one 63-bit deal seed per pair from random.Random(SEED). The default SEED is derived
from a fixed phrase and is used by no development match, so these deals are held out; every opponent gets the
same deals. One game at a time, no pondering, both engines the same clock, threads and hash.
"""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import match  # noqa: E402

BOOK_PHRASE = b"jqe formal deal book 1"
BOOK_SEED = int(hashlib.sha256(BOOK_PHRASE).hexdigest()[:12], 16)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()


def cpu_model():
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--jqe", required=True)
    ap.add_argument("--net", required=True)
    ap.add_argument("--opp", required=True, choices=sorted(match.KNOWN))
    ap.add_argument("--pairs", type=int, default=500)
    ap.add_argument("--tc", default="60+0.6")
    ap.add_argument("--movetime", type=int, default=0, help="fixed ms per move instead of a clock")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--hash", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=BOOK_SEED)
    ap.add_argument("--check", action="store_true", help="write or check the manifest, do not play")
    args = ap.parse_args()

    jqe = (ROOT / args.jqe).resolve()
    net = (ROOT / args.net).resolve()
    opp = match.KNOWN[args.opp]
    opp_files = {"binary": opp["argv"][0]}
    for k, v in opp.get("options", {}).items():
        if os.path.isfile(str(v)):
            opp_files[k] = str(v)
    out = ROOT / "engine/runs" / args.name
    clock = ["--movetime", str(args.movetime)] if args.movetime else ["--tc", args.tc]
    # run from the repository root, with the relative spelling the lane tools look for in the process list
    cmd = ["python3", "engine/tools/match.py",
           "--engine", f"jqe={jqe}:EvalFile={net}", "--engine", f"{args.opp}={args.opp}",
           "--games", str(2 * args.pairs), *clock, "--threads", str(args.threads), "--hash", str(args.hash),
           "--concurrency", "1", "--seed", str(args.seed), "--scores", "--resume",
           "--out", f"engine/runs/{args.name}"]
    fixed = dict(
        name=args.name,
        jqe=dict(path=str(jqe), sha256=sha256(jqe)),
        net=dict(path=str(net), sha256=sha256(net)),
        opponent=dict(key=args.opp, options={k: str(v) for k, v in opp.get("options", {}).items()},
                      files={k: dict(path=p, sha256=sha256(p)) for k, p in opp_files.items()}),
        pairs=args.pairs, clock=" ".join(clock), threads=args.threads, hash_mb=args.hash, concurrency=1,
        ponder=False, seed=args.seed, book="default: " + BOOK_PHRASE.decode() if args.seed == BOOK_SEED else "custom seed",
        command=cmd,
    )
    mpath = out / "manifest.json"
    if mpath.exists():
        old = json.loads(mpath.read_text())
        diff = [k for k in fixed if old.get(k) != fixed[k]]
        if diff:
            sys.exit(f"{mpath} does not match this start in: {', '.join(diff)}. Use another NAME for a different run.")
        print(f"manifest ok ({mpath}); continuing", flush=True)
    else:
        out.mkdir(parents=True, exist_ok=True)
        if (out / "games.jsonl").exists():
            sys.exit(f"{out} has games but no manifest: use a new NAME")
        manifest = dict(
            fixed,
            created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            source=dict(commit=git("rev-parse", "HEAD"), describe=git("describe", "--tags", "--always"),
                        engine_src_dirty=bool(git("status", "--porcelain", "--", "engine/src", "engine/CMakeLists.txt"))),
            host=dict(cpu=cpu_model(), logical_cpus=os.cpu_count(), kernel=platform.release(),
                      loadavg_at_start=list(os.getloadavg())),
            notes="Engine failures void a game (void.jsonl, replayed once); time forfeits count as losses.",
        )
        mpath.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"manifest written: {mpath}", flush=True)
    if args.check:
        return
    with (out / "match.log").open("a") as log:
        log.write(f"# start {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} load {os.getloadavg()[0]:.1f}\n")
        log.flush()
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        last = ""
        for line in proc.stdout:
            if line.startswith(("[", "resume", "void", "SPRT")):
                log.write(line)
                log.flush()
                last = line.rstrip()
        code = proc.wait()
        log.write(f"# exit {code} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    print(last)
    sys.exit(code)


if __name__ == "__main__":
    main()
