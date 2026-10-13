#!/usr/bin/env python3
"""Fetch the source of the six opponents at the commits the results were played with.

    python3 tools/fetch_opponents.py [--root DIR] [NAME ...]

Each repository is fetched into DIR/NAME (DIR: --root, else $JIEQI_OPPONENTS, else ~/jieqi-opponents) at its
pinned commit and checked; a directory that is already there at that commit is left alone, and one at any other
commit is an error. Only git runs: nothing fetched is built or executed here. The builds are
tools/build_classical_opponents.py (Pikafish jieqi_old, Mistboard, pikajieqi-enhanced) and
tools/repair_ab_release.py (AB-JChess); musesfish and universe-st/Jieqi run from source through adapters/.
The AB-JChess net is not in its repository: see tools/repair_ab_release.py. Licences and uses: THIRD_PARTY.md.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

# name: (GitHub repository, branch the commit was taken from, commit)
PINS = {
    "pikafish-jieqi-old": ("official-pikafish/Pikafish", "jieqi_old", "23b9466c981f0f3a1133f92de1a6f86406c4eccc"),
    "mistboard-pikajieqi": ("brianhliou/pikafish-jieqi-wasm", "jieqi_old-mistboard",
                            "6398d4c191274a8f6ad43c9ce3b2d418a84da5c3"),
    "pikajieqi-enhanced": ("CoderYiXin/pikajieqi-enhanced", "main", "7d5ca267f23c9c5cb57315607a18a55de17808b1"),
    "ab-jchess": ("lxsgx23/AB-JChess", "main", "cb0a48fe5820a401fd561016f378fac5041752f9"),
    "musesfish": ("miaosiSari/Jieqi", "main", "3de6c17ae6dafa035b5eea5ec7d6b7f39118aab6"),
    "universe-jieqi": ("universe-st/Jieqi", "main", "3579f28e5fd1f1ccb67f9b368ca89a12a755324c"),
}


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def fetch(root: Path, name: str) -> str:
    repo, branch, pin = PINS[name]
    target = root / name
    if target.exists():
        head = git("rev-parse", "HEAD", cwd=target)
        if head != pin:
            raise SystemExit(f"{target} is at {head}, not {pin}; move it away or check out the pin")
        return "present"
    target.mkdir(parents=True)
    git("init", "-q", cwd=target)
    git("remote", "add", "origin", f"https://github.com/{repo}.git", cwd=target)
    try:  # the commit alone
        git("fetch", "-q", "--depth", "1", "origin", pin, cwd=target)
    except subprocess.CalledProcessError:  # servers that refuse a fetch by hash: the branch, then the commit in it
        git("fetch", "-q", "origin", branch, cwd=target)
    git("-c", "advice.detachedHead=false", "checkout", "-q", pin, cwd=target)
    if git("rev-parse", "HEAD", cwd=target) != pin or git("status", "--porcelain", cwd=target):
        raise SystemExit(f"{target}: checkout of {pin} failed")
    return "fetched"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", metavar="NAME", help=f"some of {', '.join(PINS)} (default: all)")
    ap.add_argument("--root", type=Path,
                    default=Path(os.environ.get("JIEQI_OPPONENTS") or Path.home() / "jieqi-opponents"))
    a = ap.parse_args()
    unknown = [n for n in a.names if n not in PINS]
    if unknown:
        ap.error(f"unknown {', '.join(unknown)}; choose from {', '.join(PINS)}")
    a.root.mkdir(parents=True, exist_ok=True)
    for name in a.names or PINS:
        print(f"{name:20s} {PINS[name][2][:12]} {fetch(a.root, name)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
