# jqe, the engine

An original C++20 alpha-beta engine for Jieqi with a small NNUE trained on its own games. It contains
no third-party engine source; other engines are used only as separate processes, as opponents
(THIRD_PARTY.md). The version measured in `results/` is jqe v0.15g with the net it014; the UCI name is
`jqe 0.1`.

## Build

```sh
cmake -S engine -B engine/build
cmake --build engine/build -j4 --target jqe jqe_difftest
```

The default is a Release build (`-O3`) tuned for the build machine (`-march=native`);
`-DJQE_NATIVE=OFF` gives a portable build and `-DJQE_SANITIZE=ON` adds AddressSanitizer and
UndefinedBehaviorSanitizer. `jqe_difftest` builds the referee from `../native` as well.
`tools/check_all.sh` builds both in `build/check` and checks them.

## Nets

- `nets/it014.jqn` (sha256 `f90bd44e8ee244405eb08eb4f784e3f156900f0691f651b5124d50032f8ba160`,
  1,547,356 bytes): the net of every result. Its training record is
  `results/training/it014-train.json`.
- `nets/xpl-xpl1-r5/last.jqn` (sha256
  `e96b073bb24bb1dbf521f02ee6589180feabb890d4a74900b972ceb49aa6f245`): the exploiter net of round 5
  of the exploiter test, a fine-tune of it014 on its games against it, evaluated in
  `results/exploiter/`. It is weaker than it014 and is kept only as the subject of that test.

Without `EvalFile` the engine falls back to a much weaker hand-written evaluation, so always set it.
The signature of the build with it014 is the node count of `bench` at its default depth:

```sh
printf 'setoption name EvalFile value %s\nbench\nquit\n' "$PWD/engine/nets/it014.jqn" | engine/build/jqe
# ... Nodes searched: 45315
```

## Information model

Each side's urn holds the identities still unaccounted for among its face-down pieces, as seen by
the side the engine plays for. The opponent's urn is known exactly; our own also holds those of our
face-down pieces that were captured without our seeing them. By exchangeability, a face-down mover
reveals identity t with probability `urn[t] / urnTotal`. In search, capturing a face-down piece
leaves the urn unchanged, and moving one is a chance node with up to six outcomes.

## Search (`src/search.cpp`)

- PVS with a transposition table, null move, reverse futility, futility and late-move pruning,
  LMR, SEE pruning, killers, counter-moves, butterfly, continuation and capture history, check
  extension, aspiration windows and Lazy SMP.
- Chance nodes average their outcomes in expected-score space, `sigmoid(v / ChanceK)`, with values
  saturating at ±10000.
  - At an expanded chance node (`ChanceMix 6`, the default) every identity gets an open-window
    search at depth − 6 and the most numerous identity a full-depth search; the value is the
    probability-weighted average with the full-depth value in place of that identity's shallow
    one. `ChanceMix 0` searches every outcome at full depth with the parent's window instead.
  - `ChanceXDepth 1` (the default): every chance node of the main search with depth 1 or more is
    expanded this way, however many chance nodes lie above it on the line. Elsewhere (in quiescence,
    and at depth 0 once the line has used its expanded chance layers, `MaxChanceLayers`) the move
    plays one representative identity, the one whose value is closest to the urn's mean. `ChanceCV`,
    a correction of the representative by the identities' shallow values, is therefore in effect
    unused at the defaults.
- The rules in search are those of the referee: no legal move loses; at a repetition the side
  responsible for a perpetual check or, with `ChaseRule 1`, a perpetual chase loses (a port of
  the referee's chase classification); otherwise a repetition and the 80-ply no-capture rule draw.

## NNUE (`src/nnue.*`, `train/train.py`), format JQN1

- Inputs per perspective (1470): 16 piece kinds (own and opponent's K R N B A C P and face-down)
  on 90 points, oriented to the perspective's home rank, and 30 urn thresholds `urn[c][t] >= j`.
- Layers: 1470 → 256 and one PSQT column, with the same weights for both perspectives, then
  [us, them] 512 → 16 → 32 → 1, clipped ReLU. Incremental accumulators per ply. Inference is quantised (int16 and int8, AVX2
  where the build allows) unless `NNUEQuant` is false, which uses floats.
- Training target: `lam · sigmoid(score / K) + (1 − lam) · result`, mean squared error in
  win-probability space; `K` is fitted to the data (430 for it014).

## UCI

Options: `Hash` (MB, default 64), `Threads` (default 1), `EvalFile` (path of a JQN1 net),
`Clear Hash`, `NNUEQuant` (default true), and every search parameter as a spin option, with the
measured configuration as its default (`uci` lists them). `NodesTime N` makes the clock run on
nodes, N per millisecond, for tests on a loaded host.

`go` takes `wtime btime winc binc movestogo`, `movetime`, `depth`, `nodes`, `infinite` and
`searchmoves`. Commands besides UCI: `d` (the position and its FEN), `eval`, `moves` (legal
moves), `see MOVE`, `perft N` (move paths, reveals not expanded; 44, 1,926 and 83,907 from the
start for N = 1 to 3), `perftc N` (with chance outcomes), `bench [DEPTH]` (default 7), `nnbench`
and `selfplay` (training records, `src/selfplay.cpp`). Arguments on the command line run one
command and exit, as in `jqe perft 3`.

### Positions and moves

A FEN has five fields, `board side pools no-capture-plies move-number`:

```
xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/9/X1X1X1X1X/1X5X1/9/XXXXKXXXX w R2A2C2P5N2B2r2a2c2p5n2b2 0 1
```

The board runs from rank 9 to rank 0, Red in upper case, with the letters K R N B A C P and `X`
for a face-down piece, which can only stand on its starting point. The side is `w` (or `r`) for
Red and `b` for Black. The pools are the urns, as counts of the identities each side's face-down
pieces can still be: `R2A2C2P5N2B2` for Red at the start, written in Pikafish's order R A C P N B
but read in any order, `-` when both are empty. The move number is read and ignored.

A move is `from to` in Pikafish's coordinates, files a to i and ranks 0 to 9 from Red's side
(`h2e2`). A face-down mover's move adds the identity it revealed, in the mover's case (`a3a4P`);
when the side to move captured a face-down piece and saw what it was, its own record of the move
adds that identity in the victim's case (`b2b9Pr`: a face-down piece on Red's cannon point captures
on b9, turns out to be a soldier, and the piece it took was a chariot), while the other side's record
leaves it out.
An `x` or `X` in the suffix, which the Pikafish dialect writes after a lone reveal, is ignored.

## Playing against it

```sh
python3 engine/tools/play.py            # then open http://localhost:8765
```

A local board in the browser (`tools/play.py` and `tools/play.html`, Python standard library only).
The server listens on 127.0.0.1 and talks to one local engine process; it connects to nothing else.
Options: `--port`, `--engine` (default `engine/build/jqe`, or the newest `engine/bin/jqe-v*` if there
is one), `--net`, and `--threads` and `--hash` as defaults for the new-game dialog.

- New game: your colour, a game clock (minutes and seconds per move) or a fixed time per engine
  move, threads, hash, and whether the engine thinks on your time.
- The referee is the native rules library, the deal is random, and the browser is told only what a
  player at the board sees: reveals are public, a face-down piece you capture is shown to you alone,
  and a face-down piece the engine captures from you stays unknown to you until the game is over.
  The engine receives its own observation, exactly as in `match.py`.
- Finished games are appended to `engine/runs/play/games.jsonl` (seed, moves, result).
- `python3 engine/tests/play_smoke.py` plays two games through the HTTP API and checks that no
  hidden identity reaches the browser before the game is over.

## Tools

- `build/jqe_difftest N SEED`: plays N seeded random games and compares the engine's legal moves,
  check, chase threats, repetition verdicts and position updates with the referee's at every ply.
- `tests/vectors.py`: test vectors for ports of the engine, in `tests/vectors/` (rules and the
  referee's verdicts on 130 seeded games, network evaluations, the libm calls, the bench and 799
  searches); the TypeScript port on devinokeefe.com is checked against them.
- `tools/match.py`: refereed matches on seeded deals in colour-swapped pairs; each engine receives
  only its own observation, as Pikafish-dialect move tokens. It reports Elo with trinomial and
  pentanomial intervals. Opponents named by key are found under `$JIEQI_OPPONENTS`.
- `tools/formal.py NAME --jqe BIN --net NET --opp KEY`: a formal run (500 pairs on the held-out deal
  book, 60+0.6, 8 threads and Hash 1024 each, one game at a time), with a manifest of hashes and
  settings; the same command continues an interrupted run. `tools/formal_report.py NAME` prints the
  facts of such a run without looking at any position or move.
- `tools/games2rec.py`, `tools/label.py`: training records from refereed games, and re-labelling
  of records with another engine's scores.
- `tools/spsa.py`: SPSA tuning of search parameters on duplicate pairs.
- `train/train.py`: trains a JQN1 net from training records (PyTorch). `train/rl.py` and
  `train/rl2.py` are the self-play loops that produced the training data, and `train/exploit.py`
  with `train/xpl1.sh` the fixed-budget exploiter test (docs/DECISIONS.md, D094). They run Python
  from `.venv/` at the repository's root and keep their state in `engine/rl/`, `engine/data/`,
  `engine/exploit/` and `engine/runs/`, none of which is in the repository.
