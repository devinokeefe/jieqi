"""Portable deterministic deals. Everything in this module is referee-only truth."""
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
import hashlib


class Color(StrEnum):
    RED = "red"
    BLACK = "black"

    @property
    def opponent(self):
        return Color.BLACK if self is Color.RED else Color.RED


class Kind(StrEnum):
    ROOK = "R"
    HORSE = "N"
    ELEPHANT = "B"
    ADVISOR = "A"
    CANNON = "C"
    SOLDIER = "P"
    KING = "K"


POOL_KINDS = tuple(Kind(x) for x in "RNBACP")
INVENTORY = (2, 2, 2, 2, 2, 5)
GENERATOR = "sha256-fy32-v1"
EXPLICIT = "explicit-v1"
RED_STARTS = (0, 1, 2, 3, 5, 6, 7, 8, 19, 25, 27, 29, 31, 33, 35)
START_ROLES = tuple(Kind(x) for x in "RNBAABNRCCPPPPP")


def square(text: str) -> int:
    if type(text) is not str or len(text) != 2 or text[0] not in "abcdefghi" or text[1] not in "0123456789":
        raise ValueError("square must be a0 through i9")
    return int(text[1]) * 9 + ord(text[0]) - ord("a")


def coordinate(index: int) -> str:
    if type(index) is not int or not 0 <= index < 90:
        raise ValueError("square index must be an integer in [0, 90)")
    return chr(ord("a") + index % 9) + str(index // 9)


def mirror_square(index: int) -> int:
    coordinate(index)
    return index // 9 * 9 + 8 - index % 9


def start_squares(color: Color) -> tuple[int, ...]:
    if not isinstance(color, Color):
        raise ValueError("expected Color")
    return RED_STARTS if color is Color.RED else tuple((9 - s // 9) * 9 + s % 9 for s in RED_STARTS)


def dark_role(color: Color, index: int) -> Kind:
    try:
        return START_ROLES[start_squares(color).index(index)]
    except ValueError as error:
        raise ValueError("dark piece is not on one of its original starting points") from error


@dataclass(frozen=True, slots=True)
class Piece:
    color: Color
    kind: Kind
    hidden: bool

    def __post_init__(self):
        if not isinstance(self.color, Color) or not isinstance(self.kind, Kind) or type(self.hidden) is not bool:
            raise ValueError("invalid piece fields")
        if self.kind is Kind.KING and self.hidden:
            raise ValueError("kings cannot be hidden")

    def code(self, *, reveal: bool = False) -> str:
        letter = self.kind.value if reveal or not self.hidden else "X"
        return letter if self.color is Color.RED else letter.lower()


class _WordStream:
    """Versioned SHA-256 stream, independent of Python's random implementation."""
    def __init__(self, seed: int, color: Color):
        self.prefix = b"jieqi/setup/v1\0" + seed.to_bytes(8, "little") + color.value.encode("ascii") + b"\0"
        self.block = 0
        self.words = []

    def word(self) -> int:
        if not self.words:
            digest = hashlib.sha256(self.prefix + self.block.to_bytes(8, "little")).digest()
            self.block += 1
            self.words = [int.from_bytes(digest[i:i+4], "little") for i in range(28, -1, -4)]
        return self.words.pop()

    def below(self, n: int) -> int:
        # Rejection removes modulo bias, assuming uniformly distributed hash words.
        limit = (2**32 // n) * n
        while True:
            value = self.word()
            if value < limit:
                return value % n


def _seeded_board(seed: int) -> tuple[Piece | None, ...]:
    """Generate truth without constructing Setup, allowing constructor validation."""
    board = [None] * 90
    for color, king_square in ((Color.RED, 4), (Color.BLACK, 85)):
        pieces = [kind for kind, count in zip(POOL_KINDS, INVENTORY) for _ in range(count)]
        stream = _WordStream(seed, color)
        for i in range(len(pieces) - 1, 0, -1):
            j = stream.below(i + 1)
            pieces[i], pieces[j] = pieces[j], pieces[i]
        for index, kind in zip(start_squares(color), pieces):
            board[index] = Piece(color, kind, True)
        board[king_square] = Piece(color, Kind.KING, False)
    return tuple(board)


@dataclass(frozen=True, slots=True)
class Setup:
    board: tuple[Piece | None, ...]
    generator: str = EXPLICIT
    seed: int | None = None
    mirrored: bool = False

    def __post_init__(self):
        if type(self.board) is not tuple or len(self.board) != 90 or type(self.mirrored) is not bool:
            raise ValueError("setup requires an immutable 90-square board")
        if any(piece is not None and not isinstance(piece, Piece) for piece in self.board):
            raise ValueError("invalid board entry")
        if self.generator not in (GENERATOR, EXPLICIT):
            raise ValueError("unknown setup generator")
        if self.generator == GENERATOR:
            if type(self.seed) is not int or not 0 <= self.seed < 2**64:
                raise ValueError("seed must be a uint64")
        elif self.seed is not None:
            raise ValueError("explicit setups cannot assert a generator seed")
        for color, king_square in ((Color.RED, 4), (Color.BLACK, 85)):
            expected = set(start_squares(color)) | {king_square}
            actual = {s for s, p in enumerate(self.board) if p is not None and p.color is color}
            if actual != expected:
                raise ValueError("setup pieces must occupy their standard starting points")
            if self.board[king_square] != Piece(color, Kind.KING, False):
                raise ValueError("king must start face up on its normal point")
            pieces = [self.board[s] for s in start_squares(color)]
            if not all(p.hidden for p in pieces):
                raise ValueError("all nonking setup pieces must be hidden")
            if Counter(p.kind for p in pieces) != Counter(dict(zip(POOL_KINDS, INVENTORY))):
                raise ValueError("setup inventory does not match Jieqi")
        if self.generator == GENERATOR:
            expected = _seeded_board(self.seed)
            if self.mirrored:
                expected = tuple(expected[mirror_square(s)] for s in range(90))
            if self.board != expected:
                raise ValueError("seed provenance disagrees with explicit deal")

    @classmethod
    def from_seed(cls, seed: int):
        if type(seed) is not int or not 0 <= seed < 2**64:
            raise ValueError("seed must be a uint64")
        return cls(_seeded_board(seed), GENERATOR, seed)

    def mirror_files(self):
        return Setup(tuple(self.board[mirror_square(s)] for s in range(90)),
                     self.generator, self.seed, not self.mirrored)

    def truth_string(self) -> str:
        return "".join(p.code(reveal=True) if p else "." for p in self.board)

    def to_record(self) -> dict:
        return {"generator": self.generator, "seed": str(self.seed) if self.seed is not None else None,
                "mirrored": self.mirrored, "board_truth": self.truth_string()}

    @classmethod
    def from_record(cls, record: dict):
        if type(record) is not dict or set(record) != {"generator", "seed", "mirrored", "board_truth"}:
            raise ValueError("unexpected setup schema")
        text = record["board_truth"]
        if type(text) is not str or len(text) != 90:
            raise ValueError("board_truth must contain 90 characters")
        board = []
        for char in text:
            if char == ".":
                board.append(None)
            elif char in "RNBACPKrnbacpk":
                board.append(Piece(Color.RED if char.isupper() else Color.BLACK,
                                   Kind(char.upper()), char.upper() != "K"))
            else:
                raise ValueError("invalid true piece code")
        seed_text = record["seed"]
        if seed_text is None:
            seed = None
        elif type(seed_text) is str and seed_text.isascii() and seed_text.isdigit() and len(seed_text) <= 20:
            seed = int(seed_text)
            if str(seed) != seed_text:
                raise ValueError("seed must use canonical decimal notation")
        else:
            raise ValueError("seed must be null or a decimal string")
        return cls(tuple(board), record["generator"], seed, record["mirrored"])
