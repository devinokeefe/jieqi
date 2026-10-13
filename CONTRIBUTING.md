# Contributing

Bug reports and pull requests are welcome. For a wrong move, a wrong verdict or a crash, give
the position (a FEN in the dialect of engine/README.md, or the start position and the moves),
the commands that show it, and the build (compiler and CMake options).

## Rules questions

The rules are those of RULES.md, with the adjudication of repetition, perpetual check and
perpetual chase in docs/ADJUDICATION.md. Where the published rules are silent or unclear, the
referee in `native/` implements the fallbacks those documents name, and the referee, not the
engine, decided every game in `results/`. A report that it disagrees with another implementation
or with a published ruling should name the rule and give the game or position.

## Results

Every number about the engine's strength must come from a record committed under `results/` or
from a command the text names. `tools/check_results.py` recomputes the counts, scores and
intervals of every run from its games and checks the deals they were played on. A sentence of
README.md or REPORT.md that quotes such a number is rebuilt from the records by its `stated()`,
so that `--check` fails if the number changes or the sentence disappears. A new match is copied into `results/` with
`tools/import_run.py`, and the command that played it is stated next to it.

## Setting up

You need CMake 3.20 or newer, a C++20 compiler (the results were built with GCC 13.3) and
Python 3.11 or newer. The harness, the referee's Python interface and the checks use only the
standard library; training (`engine/train/`) needs PyTorch and NumPy in `.venv/` at the
repository's root. The opponents are not included: THIRD_PARTY.md says how to get and build them.

## Checking a change

One command builds the referee and runs its tests, builds the engine, runs the differential test
of the engine against the referee on 1,000 seeded games, checks perft 1 to 3 from the start
position (44, 1,926 and 83,907) and the bench signature with it014 (45,315 nodes), and recomputes
every result, replaying each game through the referee. It prints a summary and fails if any step
fails:

```sh
bash tools/check_all.sh
```

It builds in `build/check` at nice 19 with 4 jobs; `BUILD`, `NICE` and `JOBS` change that, and
the script's header lists the other settings. A change to the search changes the bench signature;
the results were played with the engine as it is, so such a change needs new matches before any
claim about it.

## What must stay in agreement

| What | Where | Checked by |
|---|---|---|
| The rules | `native/` (the referee) and `engine/src/position.cpp` (the engine's move generation, repetition and chase rule) | `jqe_difftest` |
| The C interface | `native/include/jieqi/c_api.h` and `jieqi/native.py` | the ABI version (4), checked on load; `tests/native/session_test.cpp` |
| The deals | `jieqi/setup.py` | `tools/check_results.py`: fixed seeds, and every deal of the records |
| The statistics | `engine/tools/match.py` (`summarize`) and `tools/check_results.py` | `check_results.py` against every summary |

A change to the C interface changes its version. Text files end lines with LF (.gitattributes).
