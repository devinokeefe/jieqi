# universe-st/Jieqi adapter

Offline adapter that lets `engine/tools/match.py` play the AI of
[universe-st/Jieqi](https://github.com/universe-st/Jieqi) (MIT, v1.7.1, commit 3579f28). Original code;
the universe modules (`src/core/*.ts`, `src/ai/*.ts`) are imported read-only at runtime from
`$UNIVERSE_JIEQI_DIR` (default `$JIEQI_OPPONENTS/universe-jieqi`, with `JIEQI_OPPONENTS` defaulting to
`~/jieqi-opponents`), and nothing from them is copied here. They need no npm packages: Node.js with
built-in TypeScript type stripping loads them directly, and an in-process resolve hook adds the `.ts`
extension their extensionless relative imports omit. No install step and no network. The node
executable is `node` from PATH unless `UNIVERSE_NODE` names another. The recorded runs used the
Windows `node.exe` (v24) called from WSL, which `run.sh` gives Windows paths; a Linux node has not been
tried.

| File | Purpose |
| --- | --- |
| `run.sh` | Launcher used by match.py (`KNOWN["universe"]`): execs node on `adapter.mts`. |
| `adapter.mts` | UCI-like loop: `uci`, `setoption`, `isready`, `ucinewgame`, `position`, `go`, `quit`, plus `d` (debug dump). |
| `observer.mts` | Rebuilds the side-to-move's information state from the start FEN and its own move tokens. |
| `test_observer.mts`, `run_tests.sh` | Hand-sequence unit checks (`./run_tests.sh`). |
| `crosscheck.py` | Randomised comparison against the native referee (`python3 adapters/universe/crosscheck.py --games 20`). |

Usage: `python3 engine/tools/match.py --engine universe=universe --engine ... --movetime 1000 ...`.
Options (`universe=universe:Opt=val,...`): `Difficulty` (easy/normal/hard, default hard),
`Deepening` (default true), `MaxDepth` (0 = time-bound), `Worlds`, `MinWorlds`, `Noise`,
`EpsilonPermille`, `Seed`, `MoveOverhead` (ms, default 15), `LogFile` (JSON lines per move; with a
Windows node.exe, Linux paths are mapped to `\\wsl.localhost\...`). `Hash`/`Threads` are accepted and ignored.

## Hidden information

The adapter process only ever receives what match.py sends to that player: the start FEN and its own
tokens (`from to [reveal] [victim]`, victim letter only on its own captures). `observer.mts` rebuilds
from those alone: the public board, the side to move, `Knowledge.revealed` (every public reveal),
`Knowledge.learned[observer]` (identities it captured face down), the no-capture clock and the
repetition counts. The observer's own face-down pieces lost to the opponent stay in its pool, as in
the rules. The true deal never enters the process, so the AI cannot see it.

The universe `Board` stores an identity for every face-down piece. The adapter fills it with the
piece's start-square kind (`homeKind`, public). It does not affect play: for standard mode,
`ai/engine.ts` `searchWorlds` calls `core/info.ts` `sampleWorld` before each sampled world. That
overwrites the identity of every face-down piece of both colours with a draw without replacement from
`poolsFor(knowledge, sideToMove)`. Root legality, check and repetition use only `homeKind`, occupancy
and the position key. `test_observer.mts` confirms that a different placeholder filling (every hidden
piece a rook) yields an identical decision (same move, scores and node count) for the same seed. The
adapter also checks that each colour's pool covers its face-down pieces, so no placeholder survives
sampling.

## Time control

`chooseMove` takes a fixed depth, a world count and a wall-clock `timeLimitMs` that aborts the search.
For `go movetime N` the budget is `0.9 N - MoveOverhead`. With `Deepening` (default), complete PIMC
decisions run at depth 1, 2, 3, ... with the preset's world count (hard: 12) and noise/epsilon, each
limited by the remaining budget. The deepest decision that completed at least `MinWorlds` (default
ceil(worlds / 3) = 4) worlds is played. `MaxDepth=4` reproduces the app's hard depth cap.
`Deepening=false` makes one time-capped call at the preset depth, which is what the app does. `go depth D`
runs one decision at depth D without a time limit, and `go nodes N` passes N as the node budget.

## Rules compatibility

Coordinates: universe `x = file`, `y = 9 - rank` (red at y = 9). Letters: our N/B are their H/E.
On randomised games (`crosscheck.py`), the universe generator's legal sets, check status and the
reconstructed boards and pools agree with the native referee in every position tested. Known
differences are all about game termination, not move legality:

* **Repetition.** Universe forbids a move that recreates a position for the third time unless the
  mover is in check, and scores "every move forbidden" as a loss. Our referee allows the move and
  adjudicates the repetition, including perpetual check/chase. The AI therefore never offers a third
  repetition unless every legal move is one. In that case the adapter clears the repetition history
  and lets the AI pick a legal move (`info string ... forced-repeat`). The universe search scores any
  in-tree repetition as 0 and has no perpetual-check/chase model.
* **80-ply clock.** Both sides draw after 80 plies without a capture. The universe search does not
  look at the clock (no legality impact).
* Incoming referee moves are also checked against the universe generator. Any disagreement is
  reported as `info string rule-difference ...` and logged.
