#!/usr/bin/env python3
"""UCI-like shim that lets engine/tools/match.py play the pinned musesfish timed worker.

match.py speaks `position fen <start> moves <tokens>` + `go movetime N`, where each token is
`from to [reveal] [victim]` as seen by this player (victim letter only on its own captures of a
face-down piece). The worker (build/actors/musesfish-timed-v1.pyz) instead takes one
`observation <jieqi-observation-v1 json>` per move. This shim replays the player's own tokens into
that observation and relays the worker's bestmove. It receives no hidden truth beyond those tokens.

Original code; the GPL musesfish sources stay in their checkout ($MUSESFISH_DIR, by default
$JIEQI_OPPONENTS/musesfish, with JIEQI_OPPONENTS defaulting to ~/jieqi-opponents) and run only inside the
separate worker process. Build the worker with `python3 tools/package_musesfish.py`.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jieqi.observation_wire import decode_observation, public_start_board  # noqa: E402
from jieqi.setup import INVENTORY, POOL_KINDS, Color, coordinate, square  # noqa: E402

EXTERNAL = Path(os.environ.get("MUSESFISH_DIR")
                or Path(os.environ.get("JIEQI_OPPONENTS") or Path.home() / "jieqi-opponents") / "musesfish")
SOURCE_NAMES = ("musesfish_pvs_20210528_fixed.py", "board/__init__.py", "board/common.py",
                "board/board.py", "board/common_20210528_fixed.py", "board/library.py")
WORKER = ROOT / "build/actors/musesfish-timed-v1.pyz"
LIBRARY = Path(os.environ.get("JIEQI_NATIVE_LIBRARY") or ROOT / "build/release/lib/libjieqi_rules.so")
POOL_LETTERS = [k.value for k in POOL_KINDS]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation(tokens):
    """Rebuild the side-to-move's jieqi-observation-v1 dict from its own move tokens."""
    board = list(public_start_board())
    counts = {c: list(INVENTORY) for c in Color}
    unknown = {c: 0 for c in Color}
    history, clock = [], 0
    for ply, tok in enumerate(tokens):
        actor = Color.RED if ply % 2 == 0 else Color.BLACK
        o, d, rest = square(tok[:2]), square(tok[2:4]), tok[4:]
        mover, target = board[o], board[d]
        if mover == "." or mover.isupper() != (actor is Color.RED):
            raise ValueError(f"token {tok}: no own piece on origin")
        reveal = None
        if mover.upper() == "X":
            if not rest or rest[0].isupper() != (actor is Color.RED) or rest[0].upper() not in POOL_LETTERS:
                raise ValueError(f"token {tok}: missing reveal letter")
            reveal, rest = rest[0].upper(), rest[1:]
            counts[actor][POOL_LETTERS.index(reveal)] -= 1
        captured, hidden_target, identity = target != ".", target.upper() == "X", None
        if hidden_target:
            if rest:  # own capture of a face-down piece: identity shown to us
                identity = rest[0].upper()
                counts[actor.opponent][POOL_LETTERS.index(identity)] -= 1
                rest = rest[1:]
            else:
                unknown[actor.opponent] += 1
        elif captured:
            identity = target.upper()
        if rest:
            raise ValueError(f"token {tok}: unexpected suffix")
        history.append({"from": coordinate(o), "to": coordinate(d), "actor": actor.value,
                        "revealed_mover": reveal, "captured": captured,
                        "captured_was_hidden": hidden_target, "captured_identity": identity})
        board[o] = "."
        board[d] = (reveal if actor is Color.RED else reveal.lower()) if reveal else mover
        clock = 0 if captured else clock + 1
    turn = Color.RED if len(tokens) % 2 == 0 else Color.BLACK
    pools = [{"color": c.value, "candidates": dict(zip(POOL_LETTERS, counts[c])),
              "live_hidden_count": board.count("X" if c is Color.RED else "x"),
              "unknown_captured_count": unknown[c]} for c in Color]
    data = {"schema": "jieqi-observation-v1", "viewer": turn.value, "side_to_move": turn.value,
            "board": "".join(board), "pools": pools, "history": history, "ply": len(history),
            "no_capture_plies": clock, "capture_visibility": "capturer_only",
            "counter_policy": "capture_only_all_plies"}
    decode_observation(data)  # strict replay check of the same ledger
    return data


def main():
    sources = {name: sha(EXTERNAL / name) for name in SOURCE_NAMES}
    worker = subprocess.Popen(
        [sys.executable, "-I", "-B", str(WORKER), "--opponent", str(EXTERNAL),
         "--source-files", json.dumps(sources, sort_keys=True, separators=(",", ":")),
         "--library", str(LIBRARY), "--library-sha256", sha(LIBRARY)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def send(line):
        worker.stdin.write(line + "\n")
        worker.stdin.flush()

    def until(prefix, relay=False):
        for line in worker.stdout:
            line = line.rstrip("\n")
            if relay and line.startswith("info"):
                print(line, flush=True)
            if line.startswith(prefix):
                return line
        raise RuntimeError("worker exited")

    send("uci")
    until("uciok")
    overhead, tokens = 30, []
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "uci":
            print("id name musesfish-timed-v1 (shim)")
            print("option name MoveOverhead type spin default 30 min 0 max 1000")
            print("uciok", flush=True)
        elif cmd.startswith("setoption name "):
            name, _, value = cmd[len("setoption name "):].partition(" value ")
            if name == "MoveOverhead":
                overhead = int(value)
            # Hash/Threads are ignored: the worker is single-threaded with a fixed table.
        elif cmd == "isready":
            send("isready")
            until("readyok")
            print("readyok", flush=True)
        elif cmd == "ucinewgame":
            send("ucinewgame")
            tokens = []
        elif cmd.startswith("position"):
            parts = cmd.split()
            tokens = parts[parts.index("moves") + 1:] if "moves" in parts else []
        elif cmd.startswith("go"):
            parts = cmd.split()
            ms = int(parts[parts.index("movetime") + 1]) if "movetime" in parts else 1000
            send("observation " + json.dumps(observation(tokens), sort_keys=True, separators=(",", ":")))
            send(f"go movetime {max(1, ms - overhead)}")
            print(until("bestmove", relay=True), flush=True)
        elif cmd == "quit":
            break
    try:
        send("quit")
        worker.wait(timeout=2)
    except Exception:
        worker.kill()


if __name__ == "__main__":
    main()
