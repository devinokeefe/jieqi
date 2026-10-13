# Results

The records of the matches this release reports, as `engine/tools/match.py` wrote them, with the local
paths taken out. `python3 tools/check_results.py` recomputes every count, score and interval from the
games and checks the deals they were played on; `bash tools/check_all.sh` also replays every game
through the referee.

## Layout

- `formal/<run>/`: the formal runs of jqe v0.15g with the net it014, one opponent each, 500 pairs of
  games on the held-out deal book (seed 72335360501015, the first 12 hex digits of the sha256 of
  "jqe formal deal book 1"), one game at a time, no pondering. `f60t8-*`: 60 s + 0.6 s per move, 8
  threads and Hash 1024 MB each. `f2s1-*`: 2 s per move, jqe on one thread with Hash 256 MB, against
  engines that do not use threads. Each run has:
  - `games.jsonl.gz`: the games (below);
  - `summary.json`: match.py's summary (counts, Elo, intervals, reasons, arguments);
  - `manifest.json`: written by `engine/tools/formal.py` before the first game: the sha256 of the jqe
    binary, the net and the opponent's files, the settings, the deal seed, the source commit, the
    host's CPU and the command;
  - `match.log`: the progress lines, with a `# start` line for each start of `formal.py` and a
    `resume:` line for each continuation of a stopped run, ending with `# exit 0` and the time;
  - `void.jsonl`: games voided by an engine failure and replayed (none in these runs).
- `longclock/c300t8-v015g-abjchess/`: a development run against AB-JChess at 300 s + 3 s per move,
  stopped after 100 games ([its README](longclock/README.md)).
- `exploiter/`: the fixed-budget exploiter test xpl1 (docs/DECISIONS.md, D094 to D096).
  `xpl1-state.json` is the test's state file: the generation rounds, their training values, the
  evaluations and the compute used. `xpl-xpl1-sel-r4` to `-r6` are the selection matches of the
  exploiter nets of rounds 4 to 6 on the book "jqe exploiter selection 1"; `xpl-xpl1-e1-r5` and
  `xpl-xpl1-e2-r5` are the two evaluations of the selected net, that of round 5
  (`engine/nets/xpl-xpl1-r5/last.jqn`), on the book "jqe exploiter book 1". Each has `games.jsonl.gz`
  and `summary.json`. The engines are `x`, the exploiter, and `champ`, jqe v0.15g with it014; scores
  are the exploiter's. The games of the generation rounds (about 465 MB) are not included.
- `difftest/v0.15g.txt`: the output of `jqe_difftest 20000 1` built from this release's `engine/`
  (the measured source): the engine's legal moves, checks, chase threats, repetition verdicts and
  position updates compared with the referee's at every position of 20,000 seeded random games. It
  takes about three minutes on one core.
- `training/it014-train.json`: the training record of the net it014 (`engine/train/train.py`): data
  files, settings, the fitted K and the loss by epoch. `engine/nets/it014.jqn` is that run's final
  net. The training data are not included.

## Game records

One JSON object per line:

- `pair`: the index of the deal in the book; `seed`: the deal's seed as a decimal string
  (`jieqi.setup.Setup.from_seed`). The deal of pair i is the i-th value of
  `random.Random(SEED).getrandbits(63)`, and both games of a pair use it, with colours swapped.
- `red`, `black`: the engines' names; `result`: from Red's side, 1, 0.5 or 0; `reason`: `RED_LOSES`,
  `BLACK_LOSES` or `DRAW` from the referee, or `TIME_FORFEIT`; `plies`.
- `moves`, one per ply, Red first: `m`, the from and to points (files a to i, ranks 0 to 9 from Red's
  side); `r`, the identity a face-down mover turned out to be, else null; `c`, the true identity of a
  captured piece, else null; `s`, the mover's reported score in centipawns, with mates as
  ±(30000 − distance); `t`, the milliseconds it used, in runs with a clock. Letters: R rook, N horse,
  B elephant, A advisor, C cannon, P soldier.

## What was changed

Paths on the machine that ran the matches were rewritten: those in the working repository became
relative to it (`engine/bin/jqe-v0.15g`, `engine/nets/it014.jqn`), and those in the opponents'
directory became `$JIEQI_OPPONENTS/...`. Nothing else was changed: hashes, commits, counts, the host's
CPU model and the thread counts are as recorded. The games are compressed with `gzip -9 -n`.
`tools/import_run.py` made the copies; it refuses a record that still holds a local path.

Some files the records name are not in this repository. The jqe binary `engine/bin/jqe-v0.15g` is
rebuilt from `engine/`: in every manifest `engine_src_dirty` is false, and the source commits named
there, which belong to the working repository's unpublished history, have the same `engine/src`,
`engine/CMakeLists.txt` and `native/` as this release; `tools/check_all.sh` checks that the rebuilt
engine's `bench` gives the recorded 45315 nodes with it014. The opponents are listed in THIRD_PARTY.md.
The musesfish and universe runs name the launchers `adapters/*/run.sh` as they were then; the
launchers in `adapters/` now take their paths from environment variables, so their sha256 differ from
the manifests'.
