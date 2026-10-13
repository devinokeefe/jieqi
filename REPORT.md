# Report

This is the report on jqe, an engine for Jieqi, and on how its strength was measured. The rules it plays
by are in [RULES.md](RULES.md); how to build, play and check it is in [README.md](README.md).

Two kinds of number appear here. The **formal results**, the long-clock run and the exploiter test come
from game records in [results/](results/), and `python3 tools/check_results.py --check` recomputes each of
them from the records and fails if a number quoted below differs. The **development numbers** (self-play
tests, the chance-node measurements, the development standings) come from runs whose records are not in
the repository; they are reported as measured, and are not evidence for any claim against other engines.

## Claim status: no claim to be the strongest Jieqi engine

The project's standard for claiming that jqe is the strongest engine, set before the formal matches, has
four parts. They are not all met.

| Requirement | State |
|---|---|
| Against every engine that can be run: at least +100 Elo, with the lower end of the 95% interval above +50, over at least 500 duplicate pairs on deals not used for development | **Met against all six engines that could be run** (Formal results). |
| The clock and threads of the agreed profile | Partly: in the four formal runs at 60+0.6 both engines had 8 threads (docs/DECISIONS.md, D098), on a 32-thread computer that other work kept busy, so that for long stretches neither had 8 free cores. Against musesfish and universe, which take a time per move, jqe was held to one thread. |
| No exploiter, trained against jqe with a fixed budget, wins more than 60% | **One test, set before it was run, passed; it is a weak test** (Exploiter test 1). |
| The exact source and network can be rebuilt; the engines not tested are listed | Done: `bash tools/check_all.sh` rebuilds the engine from `engine/src` and checks its signature (bench 45315); the list is under Limits. |

The engines that could not be run include the one most likely to be stronger (Limits). So there is no
claim that jqe is the strongest Jieqi engine, only that it is the strongest of those that could be run here.

## The engine

`engine/src` is 4,046 lines of original C++20 (no third-party engine code); `engine/README.md` describes
its options and commands. Its network is `engine/nets/it014.jqn` (1,547,356 bytes, SHA-256
f90bd44e8ee244405eb08eb4f784e3f156900f0691f651b5124d50032f8ba160), trained only on jqe's own games.

- **Information.** The engine plays from what its side has seen. For each side it keeps an urn of the
  identities not yet accounted for; a face-down piece that moves turns out to be type t with probability
  urn[t] / urn total. A face-down piece of ours that the opponent captured stays in our urn, because we
  were not told what it was.
- **Search.** Principal-variation alpha-beta with the usual pruning and Lazy SMP threads. Moving a
  face-down piece is a chance node, averaged in expected-score space: a score v is mapped to
  1 / (1 + e^(−v/430)), averaged with the identities' probabilities, and mapped back. How each identity
  is searched is the subject of the next section.
- **Evaluation.** An NNUE network: 1,470 inputs per side (16 kinds of piece, the face-down piece as a kind
  of its own, on 90 points, and 30 inputs for the counts in the urns), 256 units per side, then 16, 32
  and one output. The first layer is kept in 16-bit integers and updated incrementally; the second uses
  8-bit weights.
- **Clock.** A moves-to-go time manager that stops early when the best move is stable. The harness can
  let the engines think on the opponent's time (+38 [−7, +85] at 60+0.6 in development), but the formal
  runs were played without it.

## Chance nodes

The change that mattered most was how a chance node values its identities.

**The old method** searched every identity inside the alpha-beta window of the node above. An identity
whose true value is below the window then returns a bound just under α, and one above it returns a bound
that can lie well above the window, closer to its value, because the search is fail-soft. Bad identities are
counted at about α and good ones near their value, so the average is too high, and the engine overvalued
moving its face-down pieces. (A model that clips both ends at the window gives an error of the opposite
sign, −0.025; the lopsidedness of fail-soft bounds is what matters.)

**The measurement.** 72 reveal moves that jqe played from the 16th ply on in development games against
AB-JChess at 8 s a move, each searched to depth 12 restricted to that move. The reference value is the
expectation over the identities, each searched alone to depth 11 with an open window. Errors are in
expected score:

| Root value from | Bias | RMS error | Positions searched |
|---|---|---|---|
| The old method | +0.021 ± 0.011 | 0.053 | 1 |
| Exact Star1 windows (Ballard 1983) | +0.009 ± 0.006 | 0.028 | 11.5 times |
| The new method (ChanceMix 6) | +0.009 | 0.033 | 1.15 times |

**The new method** searches every identity with an open window six plies shallower, so that each returns
a value and not a bound, and the most numerous identity also at full depth; its deep value replaces its
shallow one in the average. In 112 development games against the old method, the engine's own expected
score drifted by −0.0124 after each of its reveals (−0.144 a game) with the old method and by +0.0014
(+0.016 a game) with the new.

**In games:** +137 [+83, +198] against the old method (80 pairs, 10+0.1 on a node clock), and a further
+34 [+11, +56] for applying the new method at every reveal of the main search (`ChanceXDepth 1`), not only at
the first along a line, together with three smaller changes (`ChanceFut`, `ChanceNW`, `ChanceMixTT`; the
last two alone gave +7 [−17, +30]).

## The network

The first network, trained on games of the hand-written evaluation, beat that evaluation by +92
[+45, +144]. Then came rounds of reinforcement: the best network so far played self-play games at 5,000
nodes a move, a new network was trained on a window of the most recent games, and it replaced the best
only if it scored above 50% against it in a 400-game match (from the tenth round, also only if its loss
on a fixed set of held-out positions was lower). Each position's training target is
0.7 · sigmoid(score / 430) + 0.3 · result, with the result as 0, ½ or 1. Promoted networks gained between
+2 and +61 each in their gate matches.

it014, the fourteenth, was trained on 82 million positions: the records of ten data files, each generated
with the best network of its time, about 124 million in all, less the positions in check, those whose
chosen move was a capture and those with a mate score
([results/training/it014-train.json](results/training/it014-train.json) has its settings and losses). Later rounds promoted it017 and it020, but in direct matches neither was better than
it014: it017 −2 [−40, +35] and it020 +9 [−30, +48] (300 games each at 1 s a move). Every result below uses
it014.

## Formal results

The formal matches follow docs/DECISIONS.md, D093. Its settings were those of the match script
(`engine/tools/formal.py`) before the first game; D093 wrote them down, unchanged, about 40 minutes into
the first run:

- a deal book held out from development, generated from the phrase `jqe formal deal book 1` (seed
  72335360501015), with the deals taken in order;
- 500 duplicate pairs against each opponent, with no stopping early; the two games of a pair share a deal
  and swap colours;
- one game at a time, no thinking on the opponent's time;
- 60 s a game plus 0.6 s a move with 8 threads and 1,024 MB of hash each, or, against the two engines that
  take a time per move, 2 s a move with jqe on one thread and 256 MB;
- a manifest of the program and network files of both engines, checked whenever a run was resumed.

The referee is the project's rules library in `native/`. It tells each engine only what its side may
know, and judges every ending.

<!-- report-results:begin -->
| Opponent | Clock | Points for jqe | W-D-L for jqe | Elo for jqe, 95% |
|---|---|---|---|---|
| AB-JChess v0.2b | 60+0.6, 8 threads each | 713 of 1000 | 701-24-275 | **+158 [+136, +181]** |
| Mistboard PikaJieQi | 60+0.6, 8 threads each | 771 of 1000 | 761-20-219 | **+211 [+187, +236]** |
| pikajieqi-enhanced | 60+0.6, 8 threads each | 770 of 1000 | 764-12-224 | **+210 [+186, +235]** |
| Pikafish jieqi_old | 60+0.6, 8 threads each | 787 of 1000 | 780-14-206 | **+227 [+202, +254]** |
| musesfish | 2 s a move, jqe on 1 thread | 974½ of 1000 | 969-11-20 | **+633 [+577, +713]** |
| universe-st Jieqi (hard) | 2 s a move, jqe on 1 thread | 991 of 1000 | 991-0-9 | **+817 [+729, +999]** |
<!-- report-results:end -->

The intervals are over pairs (pentanomial): the five possible pair scores are counted, which allows for
the two games of a pair not being independent. README.md has the same table with the intervals over games
as well; here they hardly differ. No game was void, lost on time, lost by an illegal move or stopped at the
move cap. Three runs were stopped and continued: musesfish once, after 20 games; Mistboard PikaJieQi
once, after 1 game; pikajieqi-enhanced twice, after 305 and 990 games. A continuation is a new start
of `engine/tools/formal.py` with the same arguments: it checks the manifest, keeps the games already
finished and plays the rest, and the run's `match.log` records it.

**Against AB-JChess**, jqe won both games of a pair 238 times and lost both 30 times. Of the 210 pairs
in which jqe scored one point, Red won both games in 120 and Black in 89; one pair was two draws. jqe
scored 372½ of 500 as Red and 340½ as Black.

**The machine.** Each engine had 8 threads of a 32-thread computer (an i9-14900K) that other work kept
busy. All logical CPUs were in use 44 minutes into the AB-JChess run, and about 19 of 32 a day later
(two spot checks). In the Mistboard run the first 430 games were played with the computer near its normal
speed; then other jobs filled it, and a single core ran 2 to 4 times slower for the last 570 games
(measured by the rate of a one-core job; what an 8-thread search lost was not measured). jqe scored 0.780
over the 215 pairs before and 0.764 over the 285 after, a difference within noise (p = 0.53). The Pikafish
jieqi_old run had it the other way round: a single core ran 1.4 to 1.9 times slower for the first 420
games and at full speed for the last 580; jqe scored 0.774 over the 210 pairs before and 0.797 over the 290
after (p = 0.38). AB-JChess ran its clock down to the increment in most games, Mistboard and Pikafish
jieqi_old to a median low of 0.2 s; jqe kept a median reserve of about 15 s.

## A longer clock

One development run (D097) played AB-JChess at 300 s a game plus 3 s a move, 8 threads and 1,024 MB each,
on the development deal book: jqe scored 73½ of 100 (72-3-25), **+177 [+106, +266]** over 50 pairs. On
the same development deal book, the margin at 60+0.6 with one thread each had been +200 (Development,
below). Fifty pairs cannot measure a margin closely, and these were not the formal deals, so the run
shows only that jqe still won clearly at five times the clock, not whether its margin grew or shrank.
(An earlier version of this report gave
[+105, +267], computed with n − 1 in the variance; every interval here uses the population variance, as
the match harness does. `tools/check_results.py` prints both.) jqe left about a fifth of its time unused
in these games (median lowest clock 81 s of 300).

## Development

None of this is a formal result: it was measured on development deal books, whose results also guided
the work, so it runs high.

**Development standings of v0.15** (60+0.6, one thread each, 256 MB, 100 pairs each, on a loaded computer
that made the clock worth about a third of its nominal value): AB-JChess +200 [+152, +257], Mistboard
+272 [+212, +351], Pikafish jieqi_old +282 [+222, +359], pikajieqi-enhanced +298 [+244, +367]; universe
(2 s a move) 94 wins and one loss in 95 games; musesfish (2 s a move) 99½ of 100 points.

**How the margin over AB-JChess developed:** +76 [+25, +130] at 1 s a move early on (2 October); on the
same deals +47 at 2 s and +30 [−15, +75] at 8 s a move, and +60 [+12, +110] at 60+0.6 (3 and 4 October,
before the change to chance nodes); +200 [+152, +257] at 60+0.6 with v0.15 (5 October). The formal
figure, +158, is lower. It lies inside the interval of +200, so chance alone could account for the
gap; the development deals guided the work, and the formal runs had 8 threads each, not one.

**What moved strength** (self-play, unless stated):

| Change | Gain |
|---|---|
| The first self-play network over the hand-written evaluation | +92 [+45, +144] |
| Reinforcement rounds up to it014 | between +2 and +61 for each promoted network; later networks no better |
| Time management | +41 [+8, +75] at 20+0.2 |
| The search defaults of v0.14 | +38 [+7, +70] at 2 s a move |
| Chance nodes with mixed depths (ChanceMix) | **+137 [+83, +198]**, then +34 [+11, +56] for every reveal in the tree |
| Four times the nodes | +50 [+14, +88] and +49 [+15, +84] in two ranges: about +25 a doubling |
| Speed work on 5 October | 1.19 to 1.24 times the nodes a second; by the scaling above about +6 to +8, not measured in games |

**What did not help** (each tested, none adopted): wider networks (512 and 1,024 units) and king buckets;
more reinforcement data after it014; training labels from the new search; singular extensions, ProbCut,
razoring, history pruning, correction history and reductions of captures; every tunable search parameter
moved one step either way (69 variants on a benchmark of 949 decisions); spending the clock earlier;
changes to the hash table's size and buckets; profile-guided and link-time optimisation; explicit
penalties for late reveals.

## Exploiter test 1

Set before it was run (D094, amended in D095 before any evaluation game, closed in D096). The champion is
jqe-v0.15g with it014 on one thread. The exploiter is the same program with a network fine-tuned from the
champion's on its own games against the champion, with full access to the champion's source, network and
games, and play through the same referee: six rounds of 20,000 games at 5,000 nodes a move, 120,000 in
all, each round's network trained on the records of every round so far and 3 million of jqe's own
self-play records. The networks of rounds 4 to 6 were compared on one deal book; the one selected, that
of round 5 and so trained on 100,000 games against jqe, was evaluated on another, unused book:

| Evaluation, 500 duplicate pairs | W / D / L for the exploiter | Win rate | Score | Elo |
|---|---|---|---|---|
| E1: 5,000 nodes a move | 481 / 21 / 498 | 0.481 | 0.4915 | −6 [−26, +14] |
| E2: 10+0.1 on the node clock, NodesTime 900 (about 100 times E1's search per move in the opening) | 463 / 32 / 505 | 0.463 | 0.4790 | −15 [−33, +4] |

The test fails at a win rate above 0.60. In the generation rounds every fine-tuned network scored below
the champion (−8 to −22 Elo over 20,000 games each). The budget was 12.7 core-hours and 0.05 GPU-hours.
An exploiter of this kind has little to learn, because its opponent is nearly itself: the test meets the
letter of the requirement and is not evidence that jqe is hard to exploit.

## The rules and the referee

The referee (`native/`) was tested on its own on 10,000,768 legal moves of 30,274 random games, with the
project's invariant checks and full replays, without a failure. jqe's move generator, built from the measured source, agrees with
it on every position of 20,000 random games (3,844,455 positions; `results/difftest/v0.15g.txt`, from
`engine/tests/difftest.cpp`, which `tools/check_all.sh` runs on 1,000 games). The rules follow the Tiantian app where they could be
confirmed and the conventions of Pikafish's Jieqi branch elsewhere (RULES.md, docs/ADJUDICATION.md); they
have not been checked against the current app.

## Limits

- **Evidence.** Beyond 60+0.6 there is one development run of 50 pairs at 300+3 against AB-JChess;
  nothing at longer clocks, with more threads, or against the other engines at a long clock.
- **Not tested, so nothing is said about them:** the official Pikafish Jieqi engine with its neural
  network (its maintainer says no network is available and the branch is gone; only the classical branch
  could be run; in xiangqi the maintainers' rating list puts the network about 756 Elo above the classical
  evaluation, so this is the untested engine most likely to be stronger than jqe); the AIs of the playing
  sites (Tiantian and others), which the project did not connect to; strong human players; ZenoJchess and
  ForgeQi (no usable release found); any closed commercial engine (two searches found no commercial Jieqi
  engine). Other public programs were not run either: JieqiAI (excluded for defects in its position
  handling), Jieqi-hybrid, AI-Jieqi, 2026-jieqi-AI, the rexfang prototype, fantasyzed/jieqi,
  jun-cui/jieqi (no implementation at the commit surveyed) and the flipchess wrapper; none has an engine
  interface the harness can drive.
- **Exploitability is essentially untested.** Exploiter test 1 does not cover larger budgets, an exploiter
  that models the champion's replies in its own search (the champion is deterministic at a fixed node
  count), exploiters built on other engines, or human anti-computer play.
- **Known weaknesses.** The value jqe puts on a reveal it has chosen is still too high, by +0.009 in
  expected score on average on the 72 positions of Chance nodes. In the development games it lost to
  AB-JChess, its own expected score was 0.44 on average after its fifth move and 0.32 after its tenth: those
  games were decided early, and no specific flaw was found there.
- **The machine.** Other work kept the computer busy, so wall-clock results are in effect at shorter
  clocks than labelled. A corrupted page of memory was seen once (2 October).

## Reproducing it

README.md has the commands: `bash tools/check_all.sh` builds the referee and the engine, runs their tests
and recomputes every result from its records; `engine/tools/formal.py` plays a formal run again (the
opponents are not in the repository, see THIRD_PARTY.md). A rerun gives different games: the clocks are
wall-clock time.
