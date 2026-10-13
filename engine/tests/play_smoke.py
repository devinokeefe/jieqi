#!/usr/bin/env python3
"""Headless test of tools/play.py: start the server on a spare port, play games through the HTTP API with random
legal human moves, check what the browser is told at every step, stop the server.

  python3 engine/tests/play_smoke.py [GAMES=2] [PORT=8791]
"""
import json
import random
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
games = int(sys.argv[1]) if len(sys.argv) > 1 else 2
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8791
base = f"http://127.0.0.1:{port}"
records = Path(tempfile.mkdtemp(prefix="jqe-play-")) / "games.jsonl"
srv = subprocess.Popen([sys.executable, str(ROOT / "engine/tools/play.py"), "--port", str(port), "--records", str(records)],
                       stdout=subprocess.PIPE, text=True)
print(srv.stdout.readline().strip())


def get(path):
    with urllib.request.urlopen(base + path, timeout=40) as r:
        return r.status, r.read()


def post(path, data, header=True, host=None):
    h = {"Content-Type": "application/json"}
    if header:
        h["X-Jqe"] = "1"
    if host:
        h["Host"] = host
    req = urllib.request.Request(base + path, data=json.dumps(data).encode(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def state(v=0):
    return json.loads(get(f"/api/state?v={v}")[1])


ok = True


def check(cond, what):
    global ok
    ok = ok and bool(cond)
    print(("  ok   " if cond else "  FAIL ") + what)


try:
    code, page = get("/")
    check(code == 200 and b'<svg id="board"' in page, f"page served ({len(page)} bytes)")
    s = state()
    check(s.get("none") is True and "defaults" in s, "no game yet: defaults offered")
    check(post("/api/new", {"human": "red"}, header=False)[0] == 403, "POST without the X-Jqe header is refused")
    check(post("/api/new", {"human": "red"}, host="evil.example")[0] == 403, "foreign Host header is refused")
    check(post("/api/new", {"human": "green"})[0] == 400, "bad configuration is refused")
    rng = random.Random(5)
    for g in range(games):
        human = ["red", "black"][g % 2]
        if g % 2 == 0:
            cfg = {"human": human, "mode": "movetime", "movetime_s": 0.15, "threads": 1, "hash": 32, "ponder": g % 4 == 0}
        else:
            cfg = {"human": human, "mode": "clock", "base_min": 0.5, "inc_s": 0.2, "threads": 1, "hash": 32, "ponder": True}
        code, r = post("/api/new", cfg)
        check(code == 200, f"game {g + 1} started as {human} ({cfg['mode']})")
        s = state()
        check(s["board"].count("X") == 15 and s["board"].count("x") == 15 and "truth" not in s,
              "start: 15 face-down pieces each, no truth sent")
        leaks, plies, engine_took_hidden = 0, 0, False
        while not s["over"] and plies < 400:
            if s["turn"] == s["human"]:
                if not s["legal"]:
                    check(False, "human to move without legal moves")
                    break
                if "a0a9" not in s["legal"] and post("/api/move", {"id": s["id"], "move": "a0a9"})[0] != 400:
                    check(False, "illegal move accepted")
                mv = rng.choice(s["legal"])
                code, r = post("/api/move", {"id": s["id"], "move": mv})
                if code != 200:
                    check(False, f"legal move {mv} refused: {r}")
                    break
                plies += 1
            s = state(s["v"])
            if "truth" in s and not s["over"]:
                leaks += 1
            for m in s["moves"]:
                if m["ch"] and m["by"] != s["human"] and not s["over"]:
                    engine_took_hidden = True
                    leaks += m["c"] != "?"
        check(leaks == 0, f"no hidden identity sent during the game ({len(s['moves'])} plies; "
                          f"the engine captured a face-down piece: {engine_took_hidden})")
        if not s["over"]:
            post("/api/resign", {"id": s["id"]})
            s = state(s["v"])
        check(s["over"] and len(s.get("truth", "")) == 90, f"over: {s['result']} {s['reason']}; truth revealed")
        left = {"red": s["board"].count("X"), "black": s["board"].count("x")}
        check(all(sum(s["pool"][k].values()) == left[k] for k in left),
              f"after the game the unseen pools equal the face-down pieces left {left}")
    lines = records.read_text().strip().split("\n")
    check(len(lines) == games and "moves" in json.loads(lines[-1]), f"game records written ({len(lines)})")
finally:
    srv.terminate()
    srv.wait(timeout=5)
    records.unlink(missing_ok=True)
    records.parent.rmdir()
print("ALL OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
