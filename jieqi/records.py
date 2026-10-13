"""Referee truth and explicit observation projection; NO movement adjudication.

record_unchecked_move is a structural ledger operation. The future native
oracle must approve a move before this operation is used in an actual match.
"""
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json

from .setup import Color, Kind, Piece, Setup, POOL_KINDS, INVENTORY, coordinate, square, mirror_square, dark_role


class CaptureVisibility(StrEnum):
    CAPTURER_ONLY = "capturer_only"
    BOTH = "both"
    NEITHER = "neither"


@dataclass(frozen=True, slots=True)
class ObservedMove:
    origin: int
    destination: int
    actor: Color
    revealed_mover: Kind | None
    captured: bool
    captured_was_hidden: bool
    captured_identity: Kind | None

    def protocol_token(self) -> str:
        token = coordinate(self.origin) + coordinate(self.destination)
        if self.revealed_mover is not None:
            token += Piece(self.actor, self.revealed_mover, False).code()
        if self.captured_was_hidden and self.captured_identity is not None:
            token += Piece(self.actor.opponent, self.captured_identity, False).code()
        return token

    def to_dict(self) -> dict:
        return {"from": coordinate(self.origin), "to": coordinate(self.destination), "actor": self.actor.value,
                "revealed_mover": self.revealed_mover.value if self.revealed_mover else None,
                "captured": self.captured, "captured_was_hidden": self.captured_was_hidden,
                "captured_identity": self.captured_identity.value if self.captured_identity else None}


@dataclass(frozen=True, slots=True)
class _TruthMove:
    origin: int
    destination: int
    actor: Color
    revealed_mover: Kind | None
    captured_piece: Piece | None

    def for_player(self, viewer: Color, visibility: CaptureVisibility) -> ObservedMove:
        captured = self.captured_piece
        known = captured is not None and (
            not captured.hidden or visibility is CaptureVisibility.BOTH or
            (visibility is CaptureVisibility.CAPTURER_ONLY and viewer is self.actor))
        return ObservedMove(self.origin, self.destination, self.actor, self.revealed_mover,
                            captured is not None, captured.hidden if captured else False,
                            captured.kind if known else None)


@dataclass(frozen=True, slots=True)
class PoolKnowledge:
    color: Color
    # Includes live hidden pieces AND captured identities unknown to this viewer.
    candidates: tuple[int, ...]
    live_hidden_count: int
    unknown_captured_count: int

    def to_dict(self):
        return {"color": self.color.value,
                "candidates": {kind.value: count for kind, count in zip(POOL_KINDS, self.candidates)},
                "live_hidden_count": self.live_hidden_count,
                "unknown_captured_count": self.unknown_captured_count}


@dataclass(frozen=True, slots=True)
class Observation:
    viewer: Color
    turn: Color
    board: str  # Exactly 90 PUBLIC codes, rank 0 first. No hidden identities.
    pools: tuple[PoolKnowledge, PoolKnowledge]
    history: tuple[ObservedMove, ...]
    no_capture_plies: int
    capture_visibility: CaptureVisibility

    def pool(self, color: Color) -> PoolKnowledge:
        if not isinstance(color, Color):
            raise ValueError("expected Color")
        return self.pools[0 if color is Color.RED else 1]

    def to_dict(self) -> dict:
        # A whitelist projection, never dataclasses.asdict(referee_state).
        return {"schema": "jieqi-observation-v1", "viewer": self.viewer.value,
                "side_to_move": self.turn.value, "board": self.board,
                "pools": [pool.to_dict() for pool in self.pools],
                "history": [event.to_dict() for event in self.history],
                "ply": len(self.history), "no_capture_plies": self.no_capture_plies,
                "capture_visibility": self.capture_visibility.value,
                "counter_policy": "capture_only_all_plies"}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def cache_key(self) -> str:
        # Includes perfect-recall observations, never a true-board hash or seed.
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def pikafish_fen(self) -> str:
        rows = []
        for rank in range(9, -1, -1):
            row, empty = "", 0
            for char in self.board[rank*9:rank*9+9]:
                if char == ".":
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += char
            rows.append(row + (str(empty) if empty else ""))
        counts = ""
        for pool in self.pools:
            by_kind = dict(zip(POOL_KINDS, pool.candidates))
            for char in "RACPNB":
                counts += (char if pool.color is Color.RED else char.lower()) + str(by_kind[Kind(char)])
        side = "w" if self.turn is Color.RED else "b"
        return f"{'/'.join(rows)} {side} {counts} {self.no_capture_plies} {len(self.history)//2+1}"


@dataclass(frozen=True, slots=True)
class RefereeRecord:
    setup: Setup
    board: tuple[Piece | None, ...]
    history: tuple[_TruthMove, ...]
    visibility: CaptureVisibility
    no_capture_plies: int

    @classmethod
    def start(cls, setup: Setup, visibility=CaptureVisibility.CAPTURER_ONLY):
        if not isinstance(setup, Setup) or not isinstance(visibility, CaptureVisibility):
            raise ValueError("invalid setup or capture visibility")
        return cls(setup, setup.board, (), visibility, 0)

    @property
    def turn(self) -> Color:
        return Color.RED if len(self.history) % 2 == 0 else Color.BLACK

    def record_unchecked_move(self, token: str):
        """Record a structural transition; DOES NOT check movement or king safety.

        Intended for replay/projection tests until a native legal-move gate exists.
        Observations are generated AFTER the reveal, not from an intermediate board.
        """
        if type(token) is not str or len(token) != 4:
            raise ValueError("expected four-character from/to coordinates, no reveal suffix")
        origin, destination = square(token[:2]), square(token[2:])
        moved, captured = self.board[origin], self.board[destination]
        if origin == destination or moved is None or moved.color is not self.turn:
            raise ValueError("invalid mover or turn")
        if captured is not None and (captured.color is self.turn or captured.kind is Kind.KING):
            raise ValueError("cannot structurally capture own piece or a king")
        board = list(self.board)
        board[origin] = None
        board[destination] = Piece(moved.color, moved.kind, False)
        event = _TruthMove(origin, destination, moved.color, moved.kind if moved.hidden else None, captured)
        return RefereeRecord(self.setup, tuple(board), self.history + (event,), self.visibility,
                             0 if captured else self.no_capture_plies + 1)

    def observe(self, viewer: Color) -> Observation:
        if not isinstance(viewer, Color):
            raise ValueError("expected observing Color")
        history = tuple(event.for_player(viewer, self.visibility) for event in self.history)
        candidates = {color: list(INVENTORY) for color in Color}
        unknown = {color: 0 for color in Color}
        for event in history:
            if event.revealed_mover is not None:
                candidates[event.actor][POOL_KINDS.index(event.revealed_mover)] -= 1
            if event.captured_was_hidden:
                if event.captured_identity is None:
                    unknown[event.actor.opponent] += 1
                else:
                    candidates[event.actor.opponent][POOL_KINDS.index(event.captured_identity)] -= 1
        pools = tuple(PoolKnowledge(color, tuple(candidates[color]),
                                    sum(p is not None and p.color is color and p.hidden for p in self.board),
                                    unknown[color]) for color in Color)
        for pool in pools:
            if min(pool.candidates) < 0 or sum(pool.candidates) != pool.live_hidden_count + pool.unknown_captured_count:
                raise ValueError("inconsistent observation inventory")
        return Observation(viewer, self.turn, "".join(p.code() if p else "." for p in self.board),
                           pools, history, self.no_capture_plies, self.visibility)

    def assert_invariants(self):
        """Bind current truth and counters to the immutable setup and event history.

        This validates structural transitions only, never movement or king safety.
        Replay is deliberately separate from record_unchecked_move, so a stale
        cached board, wrong reveal or bad capture clock cannot validate itself.
        """
        if (not isinstance(self.setup, Setup) or type(self.board) is not tuple or len(self.board) != 90 or
                type(self.history) is not tuple or not isinstance(self.visibility, CaptureVisibility) or
                type(self.no_capture_plies) is not int or not 0 <= self.no_capture_plies <= len(self.history)):
            raise AssertionError("invalid record field, board or counter")
        if any(p is not None and not isinstance(p, Piece) for p in self.board):
            raise AssertionError("invalid board piece")
        replay = list(self.setup.board)
        actor, idle = Color.RED, 0
        for event in self.history:
            if (not isinstance(event, _TruthMove) or not isinstance(event.actor, Color) or
                    type(event.origin) is not int or not 0 <= event.origin < 90 or
                    type(event.destination) is not int or not 0 <= event.destination < 90 or
                    (event.revealed_mover is not None and not isinstance(event.revealed_mover, Kind)) or
                    (event.captured_piece is not None and not isinstance(event.captured_piece, Piece))):
                raise AssertionError("invalid history event fields")
            moving, captured = replay[event.origin], replay[event.destination]
            if (event.origin == event.destination or moving is None or moving.color is not actor or
                    event.actor is not actor or
                    (captured is not None and (captured.color is actor or captured.kind is Kind.KING))):
                raise AssertionError("history contains an invalid structural transition")
            expected_reveal = moving.kind if moving.hidden else None
            if event.revealed_mover is not expected_reveal or event.captured_piece != captured:
                raise AssertionError("history reveal or capture disagrees with setup replay")
            replay[event.origin] = None
            replay[event.destination] = Piece(moving.color, moving.kind, False)
            idle = 0 if captured is not None else idle + 1
            actor = actor.opponent
        if tuple(replay) != self.board or idle != self.no_capture_plies:
            raise AssertionError("board or capture counter disagrees with setup replay")
        for color in Color:
            expected = Counter({Kind.KING: 1, **dict(zip(POOL_KINDS, INVENTORY))})
            actual = Counter(p.kind for p in self.board if p is not None and p.color is color)
            actual.update(event.captured_piece.kind for event in self.history
                          if event.captured_piece is not None and event.captured_piece.color is color)
            if actual != expected:
                raise AssertionError("piece inventory not conserved")
            for index, piece in enumerate(self.board):
                if piece is not None and piece.color is color and piece.hidden:
                    dark_role(color, index)
            self.observe(color)

    def mirror_files(self):
        result = RefereeRecord.start(self.setup.mirror_files(), self.visibility)
        for event in self.history:
            token = coordinate(mirror_square(event.origin)) + coordinate(mirror_square(event.destination))
            result = result.record_unchecked_move(token)
        return result

    def to_referee_dict(self) -> dict:
        return {"schema": "jieqi-referee-ledger-v1", "setup": self.setup.to_record(),
                "capture_visibility": self.visibility.value,
                "counter_policy": "capture_only_all_plies",
                "moves": [coordinate(e.origin) + coordinate(e.destination) for e in self.history]}

    @classmethod
    def from_referee_dict(cls, record: dict):
        expected = {"schema", "setup", "capture_visibility", "counter_policy", "moves"}
        if type(record) is not dict or set(record) != expected or record["schema"] != "jieqi-referee-ledger-v1":
            raise ValueError("unexpected referee ledger schema")
        if record["counter_policy"] != "capture_only_all_plies" or type(record["moves"]) is not list:
            raise ValueError("unsupported counter policy or move list")
        result = cls.start(Setup.from_record(record["setup"]), CaptureVisibility(record["capture_visibility"]))
        for token in record["moves"]:
            result = result.record_unchecked_move(token)
        result.assert_invariants()
        return result
