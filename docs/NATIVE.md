# The native rules library (the referee)

`native/` is an original C++20 array-board implementation of the rules in RULES.md: move generation,
check, the repetition, check and chase adjudication of docs/ADJUDICATION.md, and the 80-ply no-capture
rule. It uses no GPL implementation. Every game in `results/` was refereed by it, and
`engine/tests/difftest.cpp` compares the engine's own move generator and repetition rule with it.

## What it does

The library sees only public information: the public board, the side to move, the actual public reveals
of moving pieces and the move history. The hidden deal stays with the Python referee (`jieqi/setup.py`,
`jieqi/records.py`), which supplies each reveal from the fixed deal. Captured face-down identities are
never sent to it.

`GameStatus` is ONGOING, DRAW, RED_LOSES or BLACK_LOSES. The selected default rules apply in this order:
a side with no legal move loses (checkmate or stalemate); at the third occurrence of a position, the
side responsible for a perpetual check or a perpetual chase over the whole interval loses, and otherwise
the game is drawn; then the capture-only 80-ply no-capture draw. A move after a terminal position is
rejected.

Chase classification uses public positional types: a face-down piece threatens as the role of its
starting square, also in the hypothetical captures that decide whether a target is protected. King and
soldier attackers, protected targets, pinned recaptures, same-type reciprocal captures and the physical
identity of a target over the cycle are handled explicitly. A face-down advisor's hypothetical captures
are not limited to its palace, unlike its ordinary first move (docs/ADJUDICATION.md).

## Interface

The C interface is `native/include/jieqi/c_api.h`, ABI version 4; `jieqi/native.py` loads it with
ctypes and refuses any other version. `NativeGame` owns a game handle (`jq_game_create`,
`jq_game_advance`, `jq_game_snapshot`, `jq_game_destroy`); a rejected move leaves the game unchanged,
and a handle must not be shared between threads. `jq_game_replay` checks a complete history in one
call. `jq_legal_moves`, `jq_in_check`, `jq_apply_move` and `jq_chase_targets` answer questions about
single positions. `jq_repetition_replay` and `jq_basic_status` are diagnostic: the first may return
CHASE_REQUIRED and accepts histories beyond a terminal position, the second ignores repetition.
`jq_perft_revealed` counts move paths in positions without face-down pieces and ignores draws.

## Building and testing

From the repository's root:

```sh
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release -DJIEQI_SANITIZERS=OFF -DBUILD_TESTING=ON
cmake --build build/release -j4
ctest --test-dir build/release
```

The library is `build/release/lib/libjieqi_rules.so`; `engine/tools/match.py` and the other Python
tools use it from there unless `JIEQI_NATIVE_LIBRARY` names another file. The four CTest executables
(`tests/native/rules_test.cpp`, `repetition_test.cpp`, `chase_test.cpp`, `session_test.cpp`) cover
movement, the C interface, histories, chase geometry, terminal precedence and game handles.
`-DJIEQI_SANITIZERS=ON` builds them with AddressSanitizer and UndefinedBehaviorSanitizer; that build
is for the tests and is not loaded into Python. The build files also name Windows DLL paths, which
have not been tested.

## How it was checked

Besides the CTest tests, the library was compared with Pikafish's Jieqi rules code (commit
9b963f727983, run as separate diagnostic programs outside this repository, with observation-only
patches): complete legal sets, check flags and chase sets agreed in 82 constructed positions and in 248
positions from random games; 246 chase sets around rollbacks and 429 terminal decisions on history
prefixes agreed; and 35 depth-3 move trees without face-down pieces (138,650 leaves) agreed in every
root branch. The records of those comparisons are in the working repository, not here. These are fixed
samples. They do not prove the library correct, and agreement with Pikafish is not agreement with the
Tiantian app (RULES.md).
