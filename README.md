# jqe, an engine for Jieqi

Jieqi (揭棋) is Chinese chess with the pieces face down. The generals start face up on their usual
points; each side's other fifteen pieces are shuffled and set face down on its fifteen other starting
points. A face-down piece moves as the piece that normally starts on its point, and it is turned over
when it moves. Every reveal is seen by both players, but a face-down piece that is captured is shown only
to the side that captured it. The rules, with a ruling wherever the sources are unclear or silent, are in
[RULES.md](RULES.md).

jqe is an engine for it, written from scratch: alpha-beta search in which moving a face-down piece is a
chance node, and a small neural network of the NNUE kind, trained on its own games. It was measured in 500
duplicate pairs of games against each of the six other Jieqi engines that could be run (each deal played
twice, with the colours swapped), on deals held out from development.

**jqe scored 71.3% against the strongest of them, AB-JChess, a margin of +158 Elo with a 95% interval of
+136 to +181, and more against the other five.** That makes it the strongest of the engines that could be
run here; it is not a claim to be the strongest Jieqi engine ([REPORT.md](REPORT.md) says why).

The repository holds:

* the **engine** (`engine/`, C++20, no third-party engine code) and its network, `engine/nets/it014.jqn`
  (1.5 MB);
* the **referee** (`native/`, C++, with a Python wrapper in `jieqi/`), a rules library that refereed every
  match: it holds the true deal and tells each engine only what its side may know;
* the **match harness** (`engine/tools/match.py`, `formal.py`), with adapters for the other engines;
* the **records** of every game the results rest on (`results/`), and the tools that recompute every
  number from them.

## Play it

Build the referee and the engine, then start the local board, from the repository's root:

```bash
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release -DJIEQI_SANITIZERS=OFF -DBUILD_TESTING=ON
cmake --build build/release -j 8
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build -j 8
python3 engine/tools/play.py            # then open http://localhost:8765
```

You play one colour against jqe on a random deal, with the clock you choose. The page is told only
what a player at the board would see. Everything stays on your computer: the server listens on
127.0.0.1 and talks to one engine process.

jqe also speaks UCI, the protocol through which chess programs talk to engines (`engine/build/jqe`, then
`uci`), with positions and moves written as in
Pikafish's Jieqi branch; its commands, options, positions and moves are described in [engine/README.md](engine/README.md). Always
set `EvalFile` to the network: without it the engine falls back to a much weaker hand-written
evaluation.

## Results

Each opponent played 500 pairs of games against jqe-v0.15g with it014. The two games of a pair use the
same deal, with the colours swapped. The intervals are 95%, over pairs (pentanomial: from the counts of
the five possible pair scores, which allows for the two games of a deal being alike) and over games
(trinomial: from the wins, draws and losses, as if the games were independent); the last column counts the
pairs by jqe's score in them, from 0 to 2 points.

<!-- results:begin -->
| Opponent | Clock | Threads each | Games | W-D-L for jqe | Score | Elo, pentanomial 95% | Elo, trinomial 95% | Pair scores 0 / ½ / 1 / 1½ / 2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AB-JChess v0.2b | 60+0.6 | 8 | 1000 | 701-24-275 | 0.713 | +158 [+136, +181] | +158 [+135, +182] | 30 / 6 / 210 / 16 / 238 |
| Mistboard PikaJieQi | 60+0.6 | 8 | 1000 | 761-20-219 | 0.771 | +211 [+187, +236] | +211 [+187, +237] | 18 / 7 / 176 / 13 / 286 |
| pikajieqi-enhanced | 60+0.6 | 8 | 1000 | 764-12-224 | 0.770 | +210 [+186, +235] | +210 [+185, +236] | 20 / 0 / 184 / 12 / 284 |
| Pikafish jieqi_old | 60+0.6 | 8 | 1000 | 780-14-206 | 0.787 | +227 [+202, +254] | +227 [+202, +254] | 18 / 4 / 166 / 10 / 302 |
| musesfish | 2 s a move | 1 | 1000 | 969-11-20 | 0.975 | +633 [+577, +713] | +633 [+578, +712] | 0 / 1 / 19 / 10 / 470 |
| universe-st Jieqi (hard) | 2 s a move | 1 | 1000 | 991-0-9 | 0.991 | +817 [+729, +999] | +817 [+729, +1000] | 0 / 0 / 9 / 0 / 491 |
<!-- results:end -->

The deals came from a book held out from development, in order, with no stopping early. The settings
were those of the match script before the first game; docs/DECISIONS.md, D093, wrote them down about 40
minutes into the first run. No game was void, lost on time or lost by an illegal move. The computer, a 32-thread i9-14900K, was also running other work, which slowed
both engines for long stretches of the matches. Against the four engines that can use threads the clock was 60 s a game
plus 0.6 s a move, with 8 threads each; musesfish and universe take a time per move, so they had 2 s a
move, and jqe one thread.

A development run at five times the clock, 300+3, against AB-JChess gave +177 [+106, +266] over 50
pairs (`results/longclock/`). An exploiter, the same program with its network fine-tuned on 100,000
games against jqe, won 48.1% and 46.3% of its games at two search budgets, under the 60% that would
have counted as a failure (`results/exploiter/`). That is a weak test, since the exploiter had little to
learn from an opponent so like itself. [REPORT.md](REPORT.md) has the details, the
development history, what moved strength, and the limits, including the engines that could not be
tested.

## How it works

**What the engine knows.** jqe plays from what its side has seen. For each side it keeps the
identities not yet accounted for; a face-down piece turns out to be a chariot with probability equal
to the number of chariots among them divided by their total. A face-down piece of jqe's that the
opponent captured stays among jqe's unknowns, since jqe was not told what it was.

**Search.** Principal-variation alpha-beta with the usual pruning, on several threads. Moving a
face-down piece is a chance node: the engine values it by the average over the identities the piece
could have, weighted by their probabilities, on the scale of expected score. Inside alpha-beta that
average is easy to get wrong. A search of each identity within the window of the node above returns
bounds, not values, and the average comes out too high. jqe searches every identity with an open window
six plies shallower, and the most numerous identity also at full depth; that cut the bias of the
average from 0.021 to 0.009 in expected score for 1.15 times the work, and gained +137 [+83, +198] in
games against the previous version (REPORT.md, Chance nodes).

**Evaluation.** An NNUE network: 1,470 inputs per side (which kind of piece is on which point, with the
face-down piece as a kind of its own, and the counts of unseen identities), 256 units per side, then 16,
32 and one output. It was trained on 82 million positions from jqe's own games, in rounds in which
each new network had to score more than half the points against the last ([results/training/](results/training/)).

## Checking it

One command builds the referee and the engine, runs their tests, checks the engine's signature and
recomputes every result from its records:

```bash
bash tools/check_all.sh
```

It needs CMake 3.20 or later, a C++20 compiler and Python 3.11 or later, and downloads nothing; it ends
with status 0 only if every step passes. The steps:

* the referee's own tests (`tests/native/`), and the engine's moves compared with the referee's at every
  position of 1,000 random games (`engine/tests/difftest.cpp`; a run of 20,000 games, built from the measured source, is recorded in
  `results/difftest/`);
* the engine's perft counts from the start, the numbers of move sequences one, two and three plies long
  with reveals not expanded (44, 1,926 and 83,907), and its `bench` with it014, which must search exactly
  45,315 nodes, the signature of the measured build;
* `python3 tools/check_results.py --check --replay`: every run in `results/` recounted from its games,
  each interval recomputed with the harness's formulas and compared with its summary, every deal
  regenerated from its seed and every reveal and capture checked against it, every game replayed through
  the referee to the ending it records, the table above compared with the records, and every number that README.md and
  REPORT.md quote from the records checked word for word.

## Reproducing the matches

The other engines are not in this repository; [THIRD_PARTY.md](THIRD_PARTY.md) says where each comes
from, at which commit, under which licence, and how the tools here build them. With them under
`$JIEQI_OPPONENTS`, a formal run is

```bash
python3 engine/tools/formal.py NAME --jqe engine/build/jqe --net "$PWD/engine/nets/it014.jqn" --opp abjchess
```

which plays the 500 pairs on the held-out book with the formal settings, writes a manifest of both
engines' files, and can be resumed. The games will not be the same as the recorded ones: the clocks
are wall-clock time, so the engines search different amounts on another computer, or on the same one
under a different load.

## What is where

```
RULES.md          the rules the referee plays, with a ruling wherever the sources are unclear or silent
REPORT.md         the results, how they were measured, and their limits
engine/           jqe: src/ (C++20), nets/ (it014, and the exploiter's network), tools/ (match harness,
                  formal runs, local board), train/ (training and the exploiter test), tests/
native/, jieqi/   the referee: the rules library (C++) and its Python wrapper
tests/native/     the referee's tests
adapters/         how the harness drives musesfish and universe
results/          the game records and summaries of the formal, long-clock and exploiter runs, and the
                  training record of it014
tools/            check_all.sh, check_results.py, and the scripts that fetch and build the opponents
docs/             the decisions of the project that the results depend on, and the rules' sources
```

Not in the repository:

| What | Why | How to make it |
|---|---|---|
| The self-play training data | about 124 million positions, 14 GB, of which it014 was trained on 82 million | `jqe selfplay`, `engine/train/rl2.py` |
| The development runs (self-play tests, development standings) | scratch, not evidence for a claim | `engine/tools/match.py` |
| The opponents' programs and networks | other projects, some without a licence to redistribute | THIRD_PARTY.md |

## Licence, citing

The code and the networks are under the [MIT licence](LICENSE). The other engines keep their own
licences; none of their code is in this repository. To cite the project, see
[CITATION.cff](CITATION.cff).
