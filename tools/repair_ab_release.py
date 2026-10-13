#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This file quotes two lines of AB-JChess's src/position.h, which is GPL-3.0-or-later, and the two
# declarations the repair adds there, so it is under the GPL-3.0-or-later, not under this repository's MIT
# licence. It is the only such file (THIRD_PARTY.md). AB-JChess: https://github.com/lxsgx23/AB-JChess
"""Build AB-JChess v0.2b from source as the results used it, and put its net where match.py looks.

    python3 tools/repair_ab_release.py [--root DIR] [--zip PATH]

DIR is --root, else $JIEQI_OPPONENTS, else ~/jieqi-opponents, holding the checkout DIR/ab-jchess of
tools/fetch_opponents.py (commit cb0a48fe). At that commit src/position.h does not compile: a free function
calls Position::copy_for_chasing_from, which is declared private, and the method's body uses two members that
are never declared. The script copies src/ and LICENSE to DIR/ab-jchess-v02b-header-repair1, moves that
declaration to the public part of the class and declares the two members (an array of 128 StateInfo and a
count), checks the header's sha256 before and after, and builds with `make -j1 build ARCH=x86-64-bmi2
COMP=gcc` at nice 19. No function body changes. The binary in the formal manifest was built this way with GCC
13.3 (Ubuntu 24.04); another compiler gives another hash.

The net is not in the repository. It comes with the publisher's release v0.2b, in the asset 0.2b_bmi2.zip
(https://github.com/lxsgx23/AB-JChess/releases/tag/v0.2b), with no licence of its own that would allow passing it
on, so it is not part of this repository either. Download the asset yourself and give it as --zip: the script checks the
archive's sha256, extracts only abjchess-20260911.nnue to DIR/ab-jchess-v02b-source-build/, where
engine/tools/match.py expects it, and checks the net's sha256. The Windows executable in the archive is
never extracted or run.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

COMMIT = "cb0a48fe5820a401fd561016f378fac5041752f9"
HEADER_BEFORE = "09a66df9663d7325e3284a0131553dee9ba476094d12ef917a39f4b4d7e6c9b2"
HEADER_AFTER = "73e66cb04f4848ae63fac2a0cea84afc7fb22bca530b1f0323ab869ff7f7cc1d"
BINARY = "079db4d826ca5259b1a2d92c82b6c0d84cea1f5c247fc1212e4f0e2cf8716f65"  # sha256 in the formal manifest
ZIP = "6cb9cfe44946e5e4494643d32ae6352f7240c7e43d0ecbb4a437b04d7c388b03"  # 0.2b_bmi2.zip of release v0.2b
NET_NAME = "abjchess-20260911.nnue"
NET = "7a229d324e50d2b0acf3e5878a8f876b96a24b75d16c8492a3c3bf8e1418d944"
# The two lines of AB-JChess's src/position.h that the repair works on (GPL-3.0-or-later), and what it adds.
DECLARATION = "    void copy_for_chasing_from(const Position& src);"
ANCHOR = "    int idBoard[SQUARE_NB];"
ADDED = "\n    StateInfo chasingStateStorage[128];\n    int chasingStateCount;"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def build(root: Path) -> int:
    source, out = root / "ab-jchess", root / "ab-jchess-v02b-header-repair1"
    if git("rev-parse", "HEAD", cwd=source) != COMMIT or git("status", "--porcelain", cwd=source):
        raise SystemExit(f"{source}: not a clean checkout of {COMMIT} (tools/fetch_opponents.py)")
    if out.exists():
        raise SystemExit(f"{out} exists; remove it to build again")
    header = source / "src/position.h"
    before = header.read_text(encoding="utf-8")
    if sha(header) != HEADER_BEFORE or before.count(DECLARATION) != 1 or before.count("   private:") != 1 \
            or before.count(ANCHOR) != 1:
        raise SystemExit(f"{header}: not the expected header")
    out.mkdir(parents=True)
    shutil.copytree(source / "src", out / "src")
    shutil.copyfile(source / "LICENSE", out / "LICENSE")
    # Expose the existing rollback copier to its existing caller, and declare the storage its body uses.
    after = before.replace(DECLARATION + "\n", "")
    after = after.replace("   private:", DECLARATION + "\n\n   private:")
    after = after.replace(ANCHOR, ANCHOR + ADDED)
    (out / "src/position.h").write_text(after, encoding="utf-8")
    if sha(out / "src/position.h") != HEADER_AFTER:
        raise SystemExit("the repaired header is not the one the results used")
    cmd = ["nice", "-n", "19", "make", "-j1", "build", "ARCH=x86-64-bmi2", "COMP=gcc"]
    print(f"{out / 'src'}: {' '.join(cmd)}", flush=True)
    code = subprocess.run(cmd, cwd=out / "src", stdout=subprocess.DEVNULL).returncode
    binary = out / "src/AB-JChess"
    if code != 0 or not binary.is_file():
        print(f"build failed (exit {code})")
        return 1
    got = sha(binary)
    print(f"{binary}\n  sha256 {got}\n  {'the same as' if got == BINARY else 'differs from'} the formal manifest's {BINARY}")
    return 0


def extract_net(root: Path, archive: Path) -> int:
    if sha(archive) != ZIP:
        raise SystemExit(f"{archive}: sha256 is not that of 0.2b_bmi2.zip ({ZIP})")
    dest = root / "ab-jchess-v02b-source-build" / NET_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        members = [m for m in z.namelist() if m.endswith("/" + NET_NAME)]
        if len(members) != 1:
            raise SystemExit(f"{archive}: no single {NET_NAME}")
        with z.open(members[0]) as src, open(dest, "wb") as f:
            shutil.copyfileobj(src, f, 1 << 20)
    if sha(dest) != NET:
        dest.unlink()
        raise SystemExit(f"{NET_NAME}: unexpected sha256; removed")
    print(f"{dest}\n  sha256 {NET}, as in the formal manifest")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path,
                    default=Path(os.environ.get("JIEQI_OPPONENTS") or Path.home() / "jieqi-opponents"))
    ap.add_argument("--zip", type=Path, help="the downloaded 0.2b_bmi2.zip, to extract the net from")
    ap.add_argument("--net-only", action="store_true", help="only extract the net (with --zip)")
    a = ap.parse_args()
    code = 0 if a.net_only else build(a.root)
    if a.zip:
        code |= extract_net(a.root, a.zip)
    elif not a.net_only:
        print(f"no --zip: the net {NET_NAME} is still needed at {a.root / 'ab-jchess-v02b-source-build'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
