"""ctypes interface to the original C++ rules and public-history referee.

Adjudication follows the configured pinned fallback described in docs/ADJUDICATION.md.
The diagnostic repetition API remains separate from strict terminal-aware replay.
There is no Python fallback and no automatic compiler/package installation.
"""
import ctypes as ct
from dataclasses import dataclass
from enum import IntEnum
import os
from pathlib import Path

from .records import RefereeRecord
from .setup import Color, Kind, coordinate, square


class NativeUnavailable(FileNotFoundError):
    pass


class NativeError(ValueError):
    pass


class GameStatus(IntEnum):
    ONGOING = 0
    DRAW = 1
    RED_LOSES = 2
    BLACK_LOSES = 3


class BasicStatus(IntEnum):
    ONGOING = 0
    LOSS_FOR_SIDE_TO_MOVE = 1
    NO_CAPTURE_DRAW = 2


def _uint32(value, name):
    if type(value) is not int or not 0 <= value < 2**32:
        raise ValueError(name + " must be a uint32")
    return value


class RepetitionStatus(IntEnum):
    NOT_REPEATED = 0
    DRAW = 1
    RED_LOSES = 2
    BLACK_LOSES = 3
    CHASE_REQUIRED = 4


@dataclass(frozen=True, slots=True)
class RepetitionReport:
    status: RepetitionStatus
    begin: int
    end: int
    red_perpetual_check: bool
    black_perpetual_check: bool


class NativeRules:
    def __init__(self, library_path=None):
        if library_path is None:
            library_path = os.environ.get("JIEQI_NATIVE_LIBRARY")
        if library_path is None:
            root = Path(__file__).resolve().parent.parent
            candidates = [root / "build/lib/libjieqi_rules.so", root / "build/lib/libjieqi_rules.dylib",
                          root / "build/bin/jieqi_rules.dll", root / "build/bin/Debug/jieqi_rules.dll",
                          root / "build/bin/Release/jieqi_rules.dll"]
            library_path = next((p for p in candidates if p.is_file()), None)
        if library_path is None or not Path(library_path).is_file():
            raise NativeUnavailable("Build the native library as docs/NATIVE.md describes, or set JIEQI_NATIVE_LIBRARY")
        self.library_path = Path(library_path).resolve()
        self._lib = ct.CDLL(str(self.library_path))
        self._lib.jq_abi_version.argtypes = []
        self._lib.jq_abi_version.restype = ct.c_int
        if self._lib.jq_abi_version() != 4:
            raise NativeError("native ABI version mismatch")
        base = [ct.c_char_p, ct.c_size_t, ct.c_int]
        error = [ct.POINTER(ct.c_char), ct.c_size_t]
        self._lib.jq_game_destroy.argtypes = [ct.c_void_p]
        self._lib.jq_game_destroy.restype = None
        signatures = {
            "jq_game_create": base + [ct.c_uint32, ct.c_uint32, ct.POINTER(ct.c_void_p)] + error,
            "jq_game_advance": [ct.c_void_p, ct.c_int, ct.c_int, ct.c_char] + error,
            "jq_game_snapshot": [ct.c_void_p, ct.POINTER(ct.c_char), ct.c_size_t, ct.POINTER(ct.c_int),
                ct.POINTER(ct.c_uint32), ct.POINTER(ct.c_size_t), ct.POINTER(ct.c_int)] + error,
            "jq_chase_targets": base + [ct.POINTER(ct.c_ubyte), ct.c_size_t] + error,
            "jq_game_replay": base + [ct.c_uint32, ct.POINTER(ct.c_uint16), ct.c_char_p, ct.c_size_t,
                ct.c_uint32, ct.POINTER(ct.c_int)] + error,
            "jq_repetition_replay": base + [ct.c_uint32, ct.POINTER(ct.c_uint16), ct.c_char_p, ct.c_size_t,
                ct.POINTER(ct.c_int), ct.POINTER(ct.c_size_t), ct.POINTER(ct.c_size_t), ct.POINTER(ct.c_int)] + error,
            "jq_legal_moves": base + [ct.POINTER(ct.c_uint16), ct.c_size_t, ct.POINTER(ct.c_size_t)] + error,
            "jq_in_check": base + [ct.POINTER(ct.c_int)] + error,
            "jq_apply_move": base + [ct.c_int, ct.c_int, ct.c_char, ct.POINTER(ct.c_char), ct.c_size_t] + error,
            "jq_basic_status": base + [ct.c_uint32, ct.c_uint32, ct.POINTER(ct.c_int)] + error,
            "jq_perft_revealed": base + [ct.c_int, ct.POINTER(ct.c_uint64)] + error,
        }
        for name, args in signatures.items():
            function = getattr(self._lib, name)
            function.argtypes = args
            function.restype = ct.c_int

    @staticmethod
    def _board_args(board, side):
        if type(board) is not str or len(board) != 90 or not isinstance(side, Color):
            raise ValueError("expected a 90-cell public board and Color")
        return board.encode("ascii"), 90, 0 if side is Color.RED else 1

    def _call(self, name, *args):
        error = ct.create_string_buffer(512)
        status = getattr(self._lib, name)(*args, error, len(error))
        if status != 0:
            raise NativeError(f"{name} failed ({status}): " + error.value.decode("utf-8", errors="replace"))

    def legal_moves(self, board, side):
        output = (ct.c_uint16 * 8100)()
        count = ct.c_size_t()
        self._call("jq_legal_moves", *self._board_args(board, side), output, len(output), ct.byref(count))
        if count.value > len(output):
            raise NativeError("native move count exceeded output capacity")
        return tuple(coordinate(code // 90) + coordinate(code % 90) for code in output[:count.value])

    def in_check(self, board, side):
        result = ct.c_int()
        self._call("jq_in_check", *self._board_args(board, side), ct.byref(result))
        return bool(result.value)

    def apply(self, board, side, move, revealed_mover=None):
        if type(move) is not str or len(move) != 4:
            raise ValueError("expected four-coordinate move")
        if revealed_mover is not None and not isinstance(revealed_mover, Kind):
            raise ValueError("reveal must be Kind or None")
        origin, destination = square(move[:2]), square(move[2:])
        reveal = b"\0" if revealed_mover is None else revealed_mover.value.encode("ascii")
        result = ct.create_string_buffer(90)
        self._call("jq_apply_move", *self._board_args(board, side), origin, destination, reveal, result, len(result))
        return result.raw.decode("ascii")

    def basic_status(self, board, side, no_capture_plies, no_capture_limit=80):
        result = ct.c_int()
        self._call("jq_basic_status", *self._board_args(board, side),
                   _uint32(no_capture_plies, "no_capture_plies"), _uint32(no_capture_limit, "no_capture_limit"), ct.byref(result))
        return BasicStatus(result.value)

    def perft_revealed(self, board, side, depth):
        if type(depth) is not int or not 0 <= depth <= 12:
            raise ValueError("depth must be an integer in [0,12]")
        result = ct.c_uint64()
        self._call("jq_perft_revealed", *self._board_args(board, side), depth, ct.byref(result))
        return result.value

    @staticmethod
    def _history_args(moves, reveals):
        if type(moves) not in (tuple, list):
            raise ValueError("moves must be a list or tuple")
        if reveals is None:
            reveals = [None] * len(moves)
        if type(reveals) not in (tuple, list) or len(reveals) != len(moves):
            raise ValueError("one reveal entry per move required")
        codes, letters = [], bytearray()
        for move, reveal in zip(moves, reveals):
            if type(move) is not str or len(move) != 4:
                raise ValueError("expected four-coordinate move")
            if reveal is not None and (not isinstance(reveal, Kind) or reveal is Kind.KING):
                raise ValueError("expected nonking Kind or None")
            codes.append(square(move[:2]) * 90 + square(move[2:]))
            letters.append(0 if reveal is None else ord(reveal.value))
        return (ct.c_uint16 * len(codes))(*codes), bytes(letters)

    def chase_targets(self, board, actor):
        """Public positional-type threats, not ordinary legal captures."""
        output = (ct.c_ubyte * 90)()
        self._call("jq_chase_targets", *self._board_args(board, actor), output, len(output))
        if any(value not in (0, 1) for value in output):
            raise NativeError("invalid native chase mask")
        return tuple(coordinate(s) for s, value in enumerate(output) if value)

    def game_replay(self, board, side, moves, reveals=None, no_capture_plies=0, no_capture_limit=80):
        """Validate every move and reject any continuation after a terminal.

        Only public board, mover reveals and counters enter native adjudication;
        private captured identities and hidden assignments are never supplied.
        """
        encoded, letters = self._history_args(moves, reveals)
        result = ct.c_int()
        self._call("jq_game_replay", *self._board_args(board, side),
                   _uint32(no_capture_plies, "no_capture_plies"), encoded, letters, len(moves),
                   _uint32(no_capture_limit, "no_capture_limit"), ct.byref(result))
        return GameStatus(result.value)

    def adjudicate_record(self, record: RefereeRecord, no_capture_limit=80):
        """Bind truth to its ledger, then validate the entire public game."""
        record.assert_invariants()
        initial = RefereeRecord.start(record.setup, record.visibility).observe(Color.RED)
        moves = [coordinate(e.origin) + coordinate(e.destination) for e in record.history]
        reveals = [e.revealed_mover for e in record.history]
        return self.game_replay(initial.board, Color.RED, moves, reveals, no_capture_limit=no_capture_limit)

    def repetition_replay(self, board, side, moves, reveals=None, no_capture_plies=0):
        """Diagnostic only: no clock/terminal admission or chase geometry.

        CHASE_REQUIRED is unresolved, not a draw. Replay is relative to the
        supplied starting board, never inferred from its no-capture clock.
        """
        encoded, letters = self._history_args(moves, reveals)
        status, begin, end, checks = ct.c_int(), ct.c_size_t(), ct.c_size_t(), ct.c_int()
        self._call("jq_repetition_replay", *self._board_args(board, side),
                   _uint32(no_capture_plies, "no_capture_plies"), encoded, letters, len(moves),
                   ct.byref(status), ct.byref(begin), ct.byref(end), ct.byref(checks))
        if not (0 <= begin.value <= end.value == len(moves)) or checks.value not in range(4):
            raise NativeError("invalid native repetition report")
        return RepetitionReport(RepetitionStatus(status.value), begin.value, end.value,
                                bool(checks.value & 1), bool(checks.value & 2))

    def advance(self, record: RefereeRecord, move: str, no_capture_limit=80):
        """Validate the prior game, then apply the fixed deal's public reveal.

        Terminal positions cannot be advanced. The immutable result is compared
        with the native transition; errors never mutate the original ledger.
        """
        # Check the input before a new capture could erase a corrupted clock or
        # a cached board could influence the legality/terminal query.
        record.assert_invariants()
        obs = record.observe(record.turn)
        if self.adjudicate_record(record, no_capture_limit) is not GameStatus.ONGOING:
            raise NativeError("terminal position cannot be advanced")
        candidate = record.record_unchecked_move(move)
        revealed = candidate.history[-1].revealed_mover
        native_board = self.apply(obs.board, obs.turn, move, revealed)
        if native_board != candidate.observe(candidate.turn).board:
            raise NativeError("native transition and referee ledger disagree")
        candidate.assert_invariants()
        return candidate


@dataclass(frozen=True, slots=True)
class GameSnapshot:
    board: str
    turn: Color
    no_capture_plies: int
    plies: int
    status: GameStatus


class NativeGame:
    """Owned public native history. Single owner/thread; use with or close()."""
    def __init__(self, rules, board, side, no_capture_plies=0, no_capture_limit=80):
        self._rules, self._handle = rules, ct.c_void_p()
        rules._call("jq_game_create", *rules._board_args(board, side),
                    _uint32(no_capture_plies, "no_capture_plies"), _uint32(no_capture_limit, "no_capture_limit"),
                    ct.byref(self._handle))
        if not self._handle: raise NativeError("native returned a null game")

    def _open(self):
        if not self._handle: raise NativeError("native game is closed")
        return self._handle

    def close(self):
        handle = getattr(self, "_handle", None)
        if handle:
            self._handle = ct.c_void_p()
            self._rules._lib.jq_game_destroy(handle)

    def __del__(self):
        self.close()

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *_):
        self.close()

    def snapshot(self):
        board=ct.create_string_buffer(90)
        side, idle, plies, result=ct.c_int(), ct.c_uint32(), ct.c_size_t(), ct.c_int()
        self._rules._call("jq_game_snapshot", self._open(), board, len(board), ct.byref(side), ct.byref(idle),
                          ct.byref(plies), ct.byref(result))
        if side.value not in (0, 1): raise NativeError("invalid native turn")
        return GameSnapshot(board.raw.decode("ascii"), Color.RED if side.value==0 else Color.BLACK,
                            idle.value, plies.value, GameStatus(result.value))

    def advance(self, move, revealed_mover=None):
        codes, letters=self._rules._history_args([move], [revealed_mover])
        self._rules._call("jq_game_advance", self._open(), codes[0]//90, codes[0]%90, bytes(letters))


class RefereeSession:
    """Incremental native history bound to an immutable referee ledger.

    Truth/history invariants still run at each advance. Full independent replay
    remains available through NativeRules.adjudicate_record for audit checks.
    """
    def __init__(self, rules, record, no_capture_limit=80):
        record.assert_invariants()
        self._rules, self._record = rules, record
        initial=RefereeRecord.start(record.setup, record.visibility).observe(Color.RED)
        self._game=NativeGame(rules, initial.board, initial.turn, no_capture_limit=no_capture_limit)
        try:
            for e in record.history:
                self._game.advance(coordinate(e.origin)+coordinate(e.destination), e.revealed_mover)
            self._snapshot=self._checked_snapshot(record)
        except BaseException:
            self.close()
            raise

    def _checked_snapshot(self, record):
        snapshot=self._game.snapshot()
        board=record.observe(record.turn).board
        if (snapshot.board!=board or snapshot.turn is not record.turn or
            snapshot.no_capture_plies!=record.no_capture_plies or snapshot.plies!=len(record.history)):
            raise NativeError("native session and referee ledger disagree")
        return snapshot

    @property
    def record(self): return self._record

    @property
    def snapshot(self):
        self._game._open()
        return self._snapshot

    def advance(self, move):
        self._game._open()
        self._record.assert_invariants()
        if self._snapshot.status is not GameStatus.ONGOING: raise NativeError("terminal session cannot advance")
        candidate=self._record.record_unchecked_move(move)
        candidate.assert_invariants()
        self._game.advance(move, candidate.history[-1].revealed_mover)
        try: snapshot=self._checked_snapshot(candidate)
        except BaseException:
            self.close()  # Fail closed if native and truth ever diverge.
            raise
        self._record, self._snapshot = candidate, snapshot
        return candidate

    def close(self): self._game.close()
    def __enter__(self):
        self._game._open()
        return self
    def __exit__(self, *_): self.close()
