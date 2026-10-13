#!/usr/bin/env python3
"""Local board for playing full games against jqe in a browser.

  python3 engine/tools/play.py [--port 8765] [--engine engine/build/jqe] [--net engine/nets/it014.jqn]

then open http://localhost:8765 . Everything stays on this machine: the server listens on 127.0.0.1 only and talks
to one local engine process; it connects to nothing else.

Referee: the project's native rules library (legality, check, repetition/chase, 80-ply rule), as in match.py.
The deal is random and hidden from both players. The browser is sent only what a player at the board sees: reveals
are public, the identity of a face-down piece you capture is shown to you alone, and the hidden identities are
sent when the game is over. The engine receives its own observation (the tokens match.py sends) and nothing else.
Finished games are appended to engine/runs/play/games.jsonl.
"""
import argparse
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JIEQI_NATIVE_LIBRARY", str(ROOT / "build/release/lib/libjieqi_rules.so"))

from jieqi.native import GameStatus, NativeGame, NativeRules  # noqa: E402
from jieqi.setup import Color, Setup, square  # noqa: E402

START_FEN = "xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/9/X1X1X1X1X/1X5X1/9/XXXXKXXXX w R2A2C2P5N2B2r2a2c2p5n2b2 0 1"
INVENTORY = {"R": 2, "N": 2, "B": 2, "A": 2, "C": 2, "P": 5}
PAGE = Path(__file__).with_name("play.html")
RECORDS = ROOT / "engine/runs/play/games.jsonl"

CV = threading.Condition()  # guards every Game and the version counter; state requests wait on it
VERSION = 1                 # bumped on every visible change


def bump():
    global VERSION
    VERSION += 1
    CV.notify_all()


class EngineError(RuntimeError):
    pass


class Engine:
    """One UCI engine process. Used by one thread at a time (the game's engine-turn thread)."""

    def __init__(self, path, options):
        self.proc = subprocess.Popen([str(path)], cwd=str(Path(path).parent), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.lines = queue.Queue()
        self.pondering = False
        self.busy = threading.Lock()  # one conversation with the engine at a time
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("uci")
        self.wait_for("uciok", 10)
        for k, v in options.items():
            self.send(f"setoption name {k} value {v}")
        self.send("isready")
        self.wait_for("readyok", 120)  # a large hash table takes a moment
        self.send("ucinewgame")
        self.send("isready")
        self.wait_for("readyok", 120)

    def _reader(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))
        self.lines.put(None)

    def send(self, text):
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            raise EngineError(f"write failed: {e}")

    def wait_for(self, prefix, timeout, on_line=None):
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise EngineError(f"no {prefix} within {timeout:.0f} s")
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                raise EngineError(f"no {prefix} within {timeout:.0f} s")
            if line is None:
                raise EngineError("engine process exited")
            if line.startswith(prefix):
                return line
            if on_line:
                on_line(line)

    @staticmethod
    def position(tokens):
        # tokens: (token, revealed). As in match.py, a lone reveal letter is padded with 'x'.
        toks = [t + "x" if rev and len(t) == 5 else t for t, rev in tokens]
        return "position fen " + START_FEN + (" moves " + " ".join(toks) if toks else "")

    def go(self, tokens, go_args, timeout, on_line):
        with self.busy:
            self._stop_ponder()
            self.send(self.position(tokens))
            self.send("go " + go_args)
            parts = self.wait_for("bestmove", timeout, on_line).split()
            return parts[1] if len(parts) > 1 else "(none)"

    def ponder(self, tokens):
        """Think on the position after our own move (the opponent to move) to fill the hash table."""
        with self.busy:
            self.send(self.position(tokens))
            self.send("go infinite")
            self.pondering = True

    def _stop_ponder(self):
        if self.pondering:
            self.pondering = False
            self.send("stop")
            self.wait_for("bestmove", 15)

    def stop_ponder(self):
        with self.busy:
            self._stop_ponder()

    def close(self):
        try:
            self.send("stop")
            self.send("quit")
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()


def parse_info(line):
    """depth, seldepth, score, nodes, nps and pv of a UCI info line (None for other lines)."""
    t = line.split()
    if t[:2] != ["info", "depth"] or "score" not in t:
        return None
    out = {}
    for key in ("depth", "seldepth", "nodes", "nps", "hashfull"):
        if key in t:
            try:
                out[key] = int(t[t.index(key) + 1])
            except (ValueError, IndexError):
                pass
    i = t.index("score")
    try:
        out["score"] = {"kind": t[i + 1], "value": int(t[i + 2])}
    except (ValueError, IndexError):
        pass
    if "pv" in t:
        out["pv"] = t[t.index("pv") + 1:][:10]
    return out


class Game:
    """One human-against-engine game. All fields are guarded by CV."""

    def __init__(self, gid, cfg, engine_path, net, engine):
        self.id = gid
        self.cfg = cfg
        self.engine_path, self.net = str(engine_path), str(net)
        self.seed = cfg["seed"]
        self.truth = list(Setup.from_seed(self.seed).board)
        public = "".join("." if p is None else (("X" if p.color is Color.RED else "x") if p.hidden else p.code())
                         for p in self.truth)
        self.native = NativeGame(RULES, public, Color.RED)
        self.human = Color(cfg["human"])
        self.bot = self.human.opponent
        self.tokens = {Color.RED: [], Color.BLACK: []}  # each side's own observation of the game
        self.moves = []
        self.result = self.reason = None  # result: 1.0 red wins, 0.0 black wins, 0.5 draw
        self.tc = (cfg["base_ms"], cfg["inc_ms"]) if cfg["mode"] == "clock" else None
        self.clock = {Color.RED: float(cfg["base_ms"]), Color.BLACK: float(cfg["base_ms"])} if self.tc else None
        self.info, self.thinking, self.last_info = {}, False, 0.0
        self.started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.engine = engine
        self.snap = self.native.snapshot()
        self.legal = ()
        self.turn_started = time.monotonic()
        self._after_move()

    # --- moves -----------------------------------------------------------------------------------------------
    def _apply(self, side, mv, used_ms):
        o, d = square(mv[:2]), square(mv[2:4])
        mover, victim = self.truth[o], self.truth[d]
        if mover is None or mover.color is not side:
            raise ValueError("not own piece")
        reveal = mover.kind if mover.hidden else None
        self.native.advance(mv[:4], reveal)  # raises on an illegal move
        own = opp = mv[:4]
        if reveal is not None:
            letter = reveal.value if side is Color.RED else reveal.value.lower()
            own += letter
            opp += letter
        if victim is not None and victim.hidden:
            own += victim.kind.value if victim.color is Color.RED else victim.kind.value.lower()  # capturer only
        self.tokens[side].append((own, reveal is not None))
        self.tokens[side.opponent].append((opp, reveal is not None))
        self.truth[d] = type(mover)(mover.color, mover.kind, False)
        self.truth[o] = None
        self.moves.append({"m": mv[:4], "by": side.value, "r": reveal.value if reveal else None,
                           "c": victim.kind.value if victim is not None else None,
                           "ch": bool(victim is not None and victim.hidden), "t": round(used_ms)})

    def _after_move(self):
        self.snap = self.native.snapshot()
        self.turn_started = time.monotonic()
        self.thinking = False
        if self.snap.status is not GameStatus.ONGOING:
            self._finish({GameStatus.DRAW: 0.5, GameStatus.RED_LOSES: 0.0, GameStatus.BLACK_LOSES: 1.0}[self.snap.status],
                         self.snap.status.name)
            return
        self.legal = RULES.legal_moves(self.snap.board, self.snap.turn) if self.snap.turn is self.human else ()
        bump()
        if self.snap.turn is self.bot:
            threading.Thread(target=self._bot_turn, daemon=True).start()

    def _finish(self, result, reason):
        if self.result is not None:
            return
        self.result, self.reason, self.thinking, self.legal = result, reason, False, ()
        eng = self.engine
        threading.Thread(target=eng.close, daemon=True).start()
        try:
            RECORDS.parent.mkdir(parents=True, exist_ok=True)
            with RECORDS.open("a") as f:
                f.write(json.dumps({"started": self.started, "seed": str(self.seed), "human": self.human.value,
                                    "result": result, "reason": reason, "engine": self.engine_path, "net": self.net,
                                    "config": self.cfg, "moves": self.moves}) + "\n")
        except OSError:
            pass
        bump()

    def human_move(self, mv):
        if self.result is not None or self.snap.turn is not self.human:
            raise ValueError("it is not your move")
        if mv not in self.legal:
            raise ValueError("illegal move")
        used = (time.monotonic() - self.turn_started) * 1000
        if self.tc:
            self.clock[self.human] += self.tc[1] - used  # shown, not enforced: the human's flag never falls
        self._apply(self.human, mv, used)
        self._after_move()

    def resign(self):
        if self.result is None:
            self._finish(0.0 if self.human is Color.RED else 1.0, "RESIGNATION")

    def abandon(self):
        """A new game replaces this one."""
        if self.result is None:
            self.result, self.reason, self.thinking = 0.5, "ABANDONED", False
            threading.Thread(target=self.engine.close, daemon=True).start()

    def _on_line(self, line):
        info = parse_info(line)
        if info is None:
            return
        with CV:
            self.info = info
            if time.monotonic() - self.last_info > 0.3:
                self.last_info = time.monotonic()
                bump()

    def _bot_turn(self):
        with CV:
            if self.result is not None:
                return
            eng, tokens = self.engine, list(self.tokens[self.bot])
            if self.tc:
                go = (f"wtime {max(1, int(self.clock[Color.RED]))} btime {max(1, int(self.clock[Color.BLACK]))} "
                      f"winc {self.tc[1]} binc {self.tc[1]}")
                timeout = max(self.clock[self.bot], 0) / 1000 + 15
            else:
                go = f"movetime {self.cfg['movetime_ms']}"
                timeout = self.cfg["movetime_ms"] / 1000 * 2 + 15
            self.thinking, self.info = True, {}
            bump()
        t0 = time.monotonic()
        human_wins = 1.0 if self.human is Color.RED else 0.0
        try:
            mv = eng.go(tokens, go, timeout, self._on_line)
        except EngineError as e:
            with CV:
                self._finish(human_wins, f"ENGINE_FAILURE: {e}")
            return
        used = (time.monotonic() - t0) * 1000
        with CV:
            if self.result is not None:
                return
            if self.tc:
                self.clock[self.bot] -= used
                if self.clock[self.bot] < 0:
                    self._finish(human_wins, "TIME_FORFEIT")
                    return
                self.clock[self.bot] += self.tc[1]
            try:
                self._apply(self.bot, mv, used)
            except Exception as e:
                self._finish(human_wins, f"ILLEGAL_ENGINE_MOVE {mv}: {e}")
                return
            self._after_move()
            if self.result is None and self.cfg["ponder"]:
                try:
                    eng.ponder(self.tokens[self.bot])
                except EngineError:
                    pass  # surfaces at the engine's next move

    # --- what the human may see --------------------------------------------------------------------------------
    def state(self):
        over = self.result is not None
        snap = self.snap
        moves = []
        for m in self.moves:
            secret = m["ch"] and m["by"] != self.human.value and not over  # the engine captured one of your face-down pieces
            moves.append({"m": m["m"], "by": m["by"], "r": m["r"], "c": "?" if secret else m["c"], "ch": m["ch"], "t": m["t"]})
        # identities the human has not seen yet, per side
        pool = {"red": dict(INVENTORY), "black": dict(INVENTORY)}
        unseen_lost = {"red": 0, "black": 0}
        for m in self.moves:
            if m["r"]:
                pool[m["by"]][m["r"]] -= 1
            if m["ch"]:
                owner = "black" if m["by"] == "red" else "red"
                if m["by"] == self.human.value or over:
                    pool[owner][m["c"]] -= 1
                else:
                    unseen_lost[owner] += 1
        clocks = None
        if self.tc:
            c = dict(self.clock)
            if not over:
                c[snap.turn] -= (time.monotonic() - self.turn_started) * 1000
            clocks = {"red": int(c[Color.RED]), "black": int(c[Color.BLACK]), "running": None if over else snap.turn.value}
        out = {"v": VERSION, "id": self.id, "human": self.human.value, "turn": snap.turn.value, "board": snap.board,
               "moves": moves, "legal": list(self.legal), "over": over, "result": self.result, "reason": self.reason,
               "check": (not over) and RULES.in_check(snap.board, snap.turn), "clocks": clocks,
               "no_capture": snap.no_capture_plies, "pool": pool, "unseen_lost": unseen_lost,
               "engine": {"thinking": self.thinking, "name": Path(self.engine_path).name, **self.info},
               "config": {k: self.cfg[k] for k in ("mode", "base_ms", "inc_ms", "movetime_ms", "threads", "hash", "ponder")}}
        if over:
            out["truth"] = "".join("." if p is None else p.code(reveal=True) for p in self.truth)
        return out


class App:
    def __init__(self, engine_path, net, defaults):
        self.engine_path, self.net, self.defaults = engine_path, net, defaults
        self.game = None
        self.count = 0
        self.starting = threading.Lock()
        self.last_seen = time.monotonic()

    def config(self, d):
        def num(key, lo, hi, default, kind=float):
            try:
                v = kind(d.get(key, default))
            except (TypeError, ValueError):
                raise ValueError(f"bad {key}")
            if not lo <= v <= hi:
                raise ValueError(f"{key} must be between {lo} and {hi}")
            return v
        human = d.get("human", "red")
        if human == "random":
            human = secrets.choice(["red", "black"])
        if human not in ("red", "black"):
            raise ValueError("human must be red, black or random")
        mode = d.get("mode", "clock")
        if mode not in ("clock", "movetime"):
            raise ValueError("mode must be clock or movetime")
        seed = d.get("seed")
        seed = secrets.randbits(63) if seed in (None, "") else int(seed)
        if not 0 <= seed < 2 ** 64:
            raise ValueError("seed must be a uint64")
        return {"human": human, "mode": mode, "seed": seed,
                "base_ms": int(num("base_min", 0.5, 600, 15) * 60000), "inc_ms": int(num("inc_s", 0, 300, 10) * 1000),
                "movetime_ms": int(num("movetime_s", 0.1, 3600, 5) * 1000),
                "threads": num("threads", 1, 64, self.defaults["threads"], int),
                "hash": num("hash", 16, 16384, self.defaults["hash"], int), "ponder": bool(d.get("ponder", True))}

    def new_game(self, d):
        cfg = self.config(d)
        with self.starting:
            with CV:
                if self.game:
                    self.game.abandon()
                    bump()
            try:  # engine start-up (hash allocation) happens outside CV
                engine = Engine(self.engine_path, {"EvalFile": self.net, "Threads": cfg["threads"], "Hash": cfg["hash"]})
            except (EngineError, OSError) as e:
                raise ValueError(f"could not start the engine: {e}")
            with CV:
                self.count += 1
                self.game = Game(self.count, cfg, self.engine_path, self.net, engine)
                bump()

    def state(self, since):
        with CV:
            self.last_seen = time.monotonic()
            CV.wait_for(lambda: VERSION != since, timeout=25)
            self.last_seen = time.monotonic()
            if self.game is None:
                return {"v": VERSION, "id": 0, "none": True, "defaults": self.defaults,
                        "engine": {"name": Path(self.engine_path).name}}
            return {**self.game.state(), "defaults": self.defaults}

    def watchdog(self):
        """Stop pondering when no browser has asked for the state for a while (the tab was closed)."""
        while True:
            time.sleep(15)
            with CV:
                game, idle = self.game, time.monotonic() - self.last_seen
            if game is not None and game.result is None and idle > 90:
                try:
                    game.engine.stop_ponder()
                except EngineError:
                    pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _local(self):
        # Only this machine's browser: the Host header must name the loopback address this server listens on.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host in ("localhost", "127.0.0.1"):
            return True
        self._json(403, {"error": "local use only"})
        return False

    def do_GET(self):
        if not self._local():
            return
        path, _, query = self.path.partition("?")
        if path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/state":
            try:
                since = int(parse_qs(query).get("v", ["0"])[0])
            except ValueError:
                since = 0
            self._json(200, APP.state(since))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._local():
            return
        # A page from another site cannot set this header without a preflight, which is never answered.
        if self.headers.get("X-Jqe") != "1":
            self._json(403, {"error": "missing X-Jqe header"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                raise ValueError("request too large")
            data = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/new":
                APP.new_game(data)
            elif self.path == "/api/move":
                with CV:
                    if APP.game is None or data.get("id") != APP.game.id:
                        raise ValueError("no such game")
                    APP.game.human_move(str(data.get("move", "")))
            elif self.path == "/api/resign":
                with CV:
                    if APP.game is not None and data.get("id") == APP.game.id:
                        APP.game.resign()
            else:
                self._json(404, {"error": "not found"})
                return
            self._json(200, {"ok": True})
        except Exception as e:
            self._json(400, {"error": str(e)})


def newest_engine():
    def key(p):  # jqe-v0.15g -> (0, 15, 'g')
        s = p.name[len("jqe-v"):]
        num = "".join(ch if ch.isdigit() or ch == "." else " " for ch in s).split()
        parts = [int(x) for x in num[0].split(".") if x] if num else []
        return (parts, s)
    cands = [p for p in (ROOT / "engine/bin").glob("jqe-v*") if "-" not in p.name[len("jqe-v"):]]
    return max(cands, key=key) if cands else ROOT / "engine/build/jqe"


def main():
    global RULES, APP, RECORDS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--engine", default=None, help="engine binary (default: the newest engine/bin/jqe-v*, else engine/build/jqe)")
    ap.add_argument("--net", default=str(ROOT / "engine/nets/it014.jqn"))
    ap.add_argument("--threads", type=int, default=4, help="default in the new-game dialog")
    ap.add_argument("--hash", type=int, default=1024, help="default in the new-game dialog (MB)")
    ap.add_argument("--records", default=str(RECORDS), help="file the finished games are appended to")
    args = ap.parse_args()
    RECORDS = Path(args.records)
    engine = Path(args.engine) if args.engine else newest_engine()
    if not engine.is_absolute():
        engine = ROOT / engine
    net = Path(args.net)
    if not net.is_absolute():
        net = ROOT / net
    for p in (engine, net, PAGE):
        if not p.exists():
            sys.exit(f"missing {p}")
    RULES = NativeRules()
    APP = App(engine, net, {"threads": args.threads, "hash": args.hash})
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    threading.Thread(target=APP.watchdog, daemon=True).start()
    print(f"jqe board: http://localhost:{args.port}   engine {engine.name}, net {net.name}   (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with CV:
            if APP.game:
                APP.game.abandon()


if __name__ == "__main__":
    main()
