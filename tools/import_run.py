#!/usr/bin/env python3
"""Copy a finished match record into results/, with the local paths taken out.

    python3 tools/import_run.py run SRC_RUN_DIR DEST_DIR [--only games,summary]
    python3 tools/import_run.py json SRC_FILE DEST_FILE

`run` copies games.jsonl (as games.jsonl.gz, written by `gzip -9 -n`), summary.json,
manifest.json, match.log and void.jsonl from a run directory written by engine/tools/match.py;
files missing from the source are skipped, and a match.log whose last line is not `# exit 0 ...`
is refused, so an unfinished run cannot be copied. `json` copies one JSON file the same way.

Paths under the working repository (by default the directory three levels above the run directory,
i.e. the one holding engine/runs/<run>) become repository-relative, and paths under the opponents
directory ($JIEQI_OPPONENTS, by default ~/jieqi-opponents) become `$JIEQI_OPPONENTS/...`. Nothing
else changes: hashes, commits, counts and the host's CPU model and thread count are kept. The copy
is refused if any absolute path, the home directory or the host's name is left. The source is only
read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

RUN_FILES = {
    "games": "games.jsonl",
    "summary": "summary.json",
    "manifest": "manifest.json",
    "log": "match.log",
    "void": "void.jsonl",
}
ABSOLUTE = re.compile(r'(?:^|[\s"=:,(\[])(/(?:home|mnt|root|tmp|usr|opt|media|srv|var|Users)/|[A-Za-z]:\\)')


class Scrubber:
    def __init__(self, repo: Path, opponents: Path):
        self.repl = sorted(
            [(str(repo.resolve()), ""), (str(opponents.expanduser()), "$JIEQI_OPPONENTS")],
            key=lambda kv: -len(kv[0]))
        self.forbidden = [str(Path.home()), socket.gethostname()]

    def text(self, s: str, where: str) -> str:
        for old, new in self.repl:
            # The root itself, or followed by "/", but not as the prefix of a longer name.
            s = re.sub(re.escape(old) + r"(?![\w.-])(/)?",
                       lambda m, new=new: (new + "/" if new else "") if m.group(1) else (new or "."), s)
        for bad in self.forbidden:
            if bad and bad in s:
                raise SystemExit(f"{where}: {bad!r} is left after scrubbing")
        m = ABSOLUTE.search(s)
        if m:
            raise SystemExit(f"{where}: absolute path left: ...{s[max(0, m.start() - 40):m.end() + 40]}...")
        return s

    def json_file(self, src: Path, dest: Path) -> None:
        raw = src.read_text(encoding="utf-8")
        new = self.text(raw, str(src))
        # The scrubbed text must still parse, and to the same structure as the original.
        a, b = json.loads(raw), json.loads(new)
        if shape(a) != shape(b):
            raise SystemExit(f"{src}: scrubbing changed the structure")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(new, encoding="utf-8")


def shape(o):
    if isinstance(o, dict):
        return {k: shape(v) for k, v in o.items()}
    if isinstance(o, list):
        return [shape(v) for v in o]
    return type(o).__name__ if isinstance(o, str) else o


def import_run(src: Path, dest: Path, only: list[str], sc: Scrubber) -> None:
    log = src / "match.log"
    if "log" in only and log.exists():
        last = log.read_text(encoding="utf-8").rstrip("\n").rsplit("\n", 1)[-1]
        if not last.startswith("# exit 0"):
            raise SystemExit(f"{log}: the run has not finished (last line {last!r})")
    dest.mkdir(parents=True, exist_ok=True)
    for key in only:
        name = RUN_FILES[key]
        f = src / name
        if not f.exists():
            print(f"  (no {name})")
            continue
        if key == "games":
            raw = f.read_text(encoding="utf-8")
            if sc.text(raw, str(f)) != raw:
                raise SystemExit(f"{f}: game records hold local paths; not handled")
            out = dest / "games.jsonl.gz"
            with open(out, "wb") as fh:
                subprocess.run(["gzip", "-9", "-n", "-c", str(f)], stdout=fh, check=True)
        elif name.endswith(".json"):
            sc.json_file(f, dest / name)
        else:
            (dest / name).write_text(sc.text(f.read_text(encoding="utf-8"), str(f)), encoding="utf-8")
        print(f"  {dest / ('games.jsonl.gz' if key == 'games' else name)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kind", choices=["run", "json"])
    ap.add_argument("src", type=Path)
    ap.add_argument("dest", type=Path)
    ap.add_argument("--only", default=",".join(RUN_FILES), help="files of a run to copy (default: all five)")
    ap.add_argument("--repo", type=Path, help="the working repository (default: inferred from SRC)")
    ap.add_argument("--opponents", type=Path,
                    default=Path(os.environ.get("JIEQI_OPPONENTS", Path.home() / "jieqi-opponents")))
    a = ap.parse_args()
    src = a.src.resolve()
    if a.kind == "run":
        repo = a.repo or src.parents[2]
        only = [k.strip() for k in a.only.split(",") if k.strip()]
        unknown = set(only) - set(RUN_FILES)
        if unknown:
            ap.error(f"unknown file keys {sorted(unknown)}; choose from {sorted(RUN_FILES)}")
        print(f"{a.src.name} -> {a.dest}")
        import_run(src, a.dest, only, Scrubber(repo, a.opponents))
    else:
        if not a.repo:
            ap.error("json needs --repo")
        Scrubber(a.repo, a.opponents).json_file(src, a.dest)
        print(f"{a.src.name} -> {a.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
