#!/usr/bin/env python3
"""Build the three Pikafish-family opponents as the results used them: classical evaluation, no net.

    python3 tools/build_classical_opponents.py [--root DIR] [--jobs N] [NAME ...]

DIR is --root, else $JIEQI_OPPONENTS, else ~/jieqi-opponents, holding the checkouts of tools/fetch_opponents.py.
For each opponent the script checks the pinned commit, a clean tracked tree and `#define USE_NNUEEVAL 0` in
src/types.h (the classical evaluation, compiled without the NNUE evaluation), runs `make all` in src/ at nice 19,
checks that no tracked file changed, and prints the sha256 of src/PikaJieQi next to the one in the formal run's
manifest. The binaries in the manifests were built with GCC 13.3 (Ubuntu 24.04); another compiler gives
another hash.

The recorded builds were `make -j2 all ARCH=x86-64-bmi2 COMP=gcc` for Pikafish jieqi_old and Mistboard, and
`make ARCH=x86-64-avx2 build` for pikajieqi-enhanced. The Makefile's `build` target runs its net and
configuration checks and then the same `make ARCH=... COMP=... all`; `all` is used here for all three.
"""
import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

# name: (commit, ARCH, sha256 of src/PikaJieQi in the formal manifest)
BUILDS = {
    "pikafish-jieqi-old": ("23b9466c981f0f3a1133f92de1a6f86406c4eccc", "x86-64-bmi2",
                           "8393b90ed016451812b2b4084e804451b4d18b59886a9ad7a18e6961290e29aa"),
    "mistboard-pikajieqi": ("6398d4c191274a8f6ad43c9ce3b2d418a84da5c3", "x86-64-bmi2",
                            "d984d84cd57942d7e013e680bbf7fcefc9331455760649db0c2f1bea453144f9"),
    "pikajieqi-enhanced": ("7d5ca267f23c9c5cb57315607a18a55de17808b1", "x86-64-avx2",
                           "0c55297d990acf7de15c149a5f5bcf0504937832d4a1b8bdcc039aafac9cf224"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def build(root: Path, name: str, jobs: int) -> bool:
    pin, arch, recorded = BUILDS[name]
    src = root / name / "src"
    if git("rev-parse", "HEAD", cwd=src) != pin or git("diff", "HEAD", "--", cwd=src):
        raise SystemExit(f"{root / name}: not a clean checkout of {pin} (tools/fetch_opponents.py)")
    if "#define USE_NNUEEVAL 0" not in (src / "types.h").read_text(encoding="utf-8", errors="replace"):
        raise SystemExit(f"{src}/types.h: not the classical build (USE_NNUEEVAL 0)")
    tracked = git("ls-files", cwd=root / name).splitlines()
    before = {p: sha(root / name / p) for p in tracked if (root / name / p).is_file()}
    cmd = ["nice", "-n", "19", "make", f"-j{jobs}", "all", f"ARCH={arch}", "COMP=gcc"]
    print(f"{name}: {' '.join(cmd)}", flush=True)
    code = subprocess.run(cmd, cwd=src, stdout=subprocess.DEVNULL).returncode
    after = {p: sha(root / name / p) for p in before}
    if after != before:
        raise SystemExit(f"{name}: the build changed tracked files")
    binary = src / "PikaJieQi"
    if code != 0 or not binary.is_file():
        print(f"{name}: build failed (exit {code})")
        return False
    got = sha(binary)
    print(f"{name}: {binary}\n  sha256 {got}\n  {'the same as' if got == recorded else 'differs from'} "
          f"the formal manifest's {recorded}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", metavar="NAME", help=f"some of {', '.join(BUILDS)} (default: all)")
    ap.add_argument("--root", type=Path,
                    default=Path(os.environ.get("JIEQI_OPPONENTS") or Path.home() / "jieqi-opponents"))
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    unknown = [n for n in a.names if n not in BUILDS]
    if unknown:
        ap.error(f"unknown {', '.join(unknown)}; choose from {', '.join(BUILDS)}")
    ok = [build(a.root, n, a.jobs) for n in (a.names or BUILDS)]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
