# Decisions D086 to D098

> The entries of the project's decision log from the start of the jqe engine (D086, 2026-10-01) to the
> thread profile of the formal results (D098, 2026-10-11), as written at the time, except for a few
> words: "the user" reads "the owner", and in D086 the parties to the handover are not named.
> MISSION.md, EVALUATION.md, JOURNAL.md and STATUS.md, which some entries cite, are documents of
> the working repository and are not part of this release. One statement is known to be wrong: D087
> item 5 says the opponents were qualified with "embedded Pikafish nets"; every Pikafish-family
> opponent was a classical build with no net (THIRD_PARTY.md).

## D086 — 2026-10-01T21:17 UTC: takeover; pivot to original alpha-beta + self-play NNUE (jqe)

The owner transferred the project to a new maintainer after pausing the previous
automation. The previous track's neural-MCTS learner remained far below the classical engines
(0/32 vs Pikafish and Mistboard), so the strength route changes:

1. Engine: `engine/` (jqe), original C++20 alpha-beta. PVS/TT/null-move/LMR,
   Lazy SMP, chance nodes for face-down movers with an urn information model.
   It reuses no GPL or other third-party engine code; the owner chose "original code
   only". Pikafish and other GPL engines may run only as separate processes
   (opponents or labellers).
2. Evaluation: an original NNUE (JQN1, float inference) trained in PyTorch on
   jqe self-play. The loop is expert iteration: generate data with net N,
   train N+1, then promote by refereed match.
3. Referee: the existing native oracle (`build/release` libjieqi_rules) through a
   lean runner (`engine/tools/match.py`), with seeded deals in duplicate pairs.
4. The previous MCTS/BC tracks are paused, not deleted. All prior evidence stays
   immutable. The world-best claim standard in MISSION.md is unchanged.

## D087 — 2026-10-02T01:00 UTC: jqe engineering defaults and RL protocol

1. Quantized NNUE inference is the default (FT int16 at scale 254, per-row int8 L1
   scales). It matched float within 4.9 cp MAE and won +14 [-2,+30] at equal time.
2. Promotion: candidate vs current best, 400 games (200 duplicate pairs) at
   100 ms/move, promoted if the score is above 0.5. Every candidate also plays a
   200-game anchor match against Pikafish jieqi_old to track absolute progress.
3. RL data window: the last 4 data files (v0 classical-labelled data drops out
   automatically from iteration 4). 100k games/iteration at 5k nodes, lam 0.7.
4. Engine changes enter the RL loop only at iteration boundaries and only if
   behaviour-exact (oracle difftest / bit-identical evals) or A/B-validated.
5. Strength claims about the opponents use the configurations as qualified by the
   previous track (embedded Pikafish nets; AB-JChess v0.2b with its published net).
   100 ms results are provisional until longer time controls are checked, because
   the Pikafish-based engines reach only depth 1-3 at 100 ms.

## D088 — ChanceTail=1 default; long time controls are the target; data before capacity (2026-10-02 06:54 UTC)

Context: at 100 ms jqe leads Pikafish jieqi_old by ~+100-130, but at 1 s it is +28 [-20,+77] vs
Pikafish and -26 [-75,+21] vs AB-JChess. jqe gains ~3-4 plies per 10x time against Pikafish's ~8.

Decisions:
1. ChanceTail=1 becomes the engine default (500 ms: +38 [+5,+72] vs 0; 100 ms: -12 [-39,+16]).
   ChanceTail=2 (+13) and ChanceRed=2 (-48 at 225 games) are rejected; MaxChanceLayers stays 3
   until the 1 s MCL1 test resolves (500 ms: MCL1 +19 [-14,+53], MCL2 -17 [-50,+17]).
2. Search changes are judged at >= 500 ms (1 s where affordable), not at the 100 ms gate.
3. Evaluation work targets data volume first: king buckets overfit at 19M records, width 512 and
   deeper labels gave nothing, and the baseline shows a train/val gap. A 600k-game it006 dataset
   (~45M records) is the next test; RL gating at 100 ms is kept only as a regression check.
4. AB-JChess relabelling (allowed as a separate process) is deferred: its scores add little
   outcome information on our positions.

## D089 — MaxChanceLayers=1 default (2026-10-02 07:32 UTC)

With ChanceTail=1, MaxChanceLayers 1 vs 3: +19 [-14,+53] at 500 ms (400 games) and +27 [-12,+66]
at 1 s (300 games), both on it006. Pooled about +22 over 700 games. Only the first reveal on a
line is averaged over all identities; later reveals use the representative identity at full
depth. Depth at 1 s rises from 8-9 to ~14. Single-thread search is otherwise unchanged.
Rejected on the way: SeDepth=6 -18 [-52,+15] (500 ms); HistPrune=3000 +11 [-22,+45] (kept off).


## D090 — Data volume over capacity; it009 promoted (2026-10-02 08:40 UTC)

On a fixed held-out set (first 1M records of big-it006-b, 655k after filters, never trained on),
validation loss for FT 256: old window it006-it008 only (14.4M kept records) 0.015217;
+ big-it006-a (200k games, 24.0M kept) 0.014865; width 512 0.014999 (best at
epoch 4); 3 king buckets 0.015332; factorised 9 king buckets 0.015415 (best at epoch 2).
In games at 300 ms vs it006 (400 each): +big-a FT 256 +26 [-7,+60], FT 512 -5 [-39,+28].

1. The FT-256 net with big-it006-a is promoted as it009. Its gate alone is not significant; the
   held-out loss supports it, and generating the next data from it costs nothing extra.
2. Self-play moves to it009 with the current search defaults (v0.11f: MCL1, ChanceTail=1) at
   5k nodes, in 200k-game chunks. The it006 chunk c is not generated.
3. King buckets, width 512 and other FT capacity stay off until a larger dataset beats the plain
   net on the held-out set. Inference for king-bucketed nets exists (JQN1 version 2) for that test.
4. Comparisons of training recipes use the common held-out file (train.py --val-file), not the
   per-run last 1%.

## D091 — it010 promoted; streamed training; search over eval at long TC (2026-10-02 10:25 UTC)

it010 (FT 256, 42.8M kept records) has held-out loss 0.014602 vs it009's 0.014865 (seed noise
~0.00006) and gated +5 [-28,+39] vs it009 at 300 ms (400 games).

1. it010 is promoted by the loop rule (positive pentanomial Elo and lower held-out loss) and
   becomes the self-play net. The playing gain is unproven; the held-out gain is clear.
2. The RL loop trains with train.py --stream on a sliding window of up to 400M raw records,
   with epochs capped so that epochs x records <= 600M. Streaming matched in-memory training on
   identical data (0.014702 vs 0.014689), and the in-memory trainer would exhaust the 32 GB
   machine at ~150M records.
3. AB-JChess, the strongest opponent at 1 s, searches ~30x fewer nodes than jqe with an eval
   that predicts results no better than ours. The long-TC gap is a search problem, chiefly the
   treatment of reveals. Search work at long TC therefore prioritises chance structure (more
   averaged reveal layers at reduced depth, reveal safety via SEE) over evaluation capacity,
   while the data loop continues to improve the net.

## D092 — v0.13 defaults: SEE bundle, chase rule, mate before the clock (2026-10-02 12:30 UTC)

At 500 ms (it010, 400 games) the SEE bundle (QsSee=1, SeeOrder=1, SeeCap=100, SeeQuiet=20)
scored +35 [+1,+69] vs v0.12 defaults. At 1 s single-threaded, it010 with v0.12 scored +40
[-7,+89] vs AB-JChess and +81 [+33,+133] vs Pikafish jieqi_old (200 games each). Seven of the
losses to AB-JChess were chase-repetition losses, all in positions that were already lost.

1. jqe v0.13 makes the SEE bundle the default. It is the base for later A/B tests and for the
   RL generator after the thread tests.
2. The search now applies the referee's chase rule at repetitions (ChaseRule=1). A third
   occurrence without check where exactly one side chased continuously is scored as a loss for
   the chaser. difftest checks threat sets and constructed cycles against the native referee.
3. When the 80-ply no-capture limit is reached with no legal move, the side to move is mated,
   matching the referee (mate takes precedence over the clock).
4. The TT is lockless: each entry stores key XOR data and probes copy the entry. This removes
   torn reads under Lazy SMP. TTWays (default 1) and CapLmr (default 0) are options for
   long-TC tests.
5. Data files can be corrupted in the page cache while the disk copy is intact (seen once in
   rl-it008.bin). train.py drops malformed records and rl2 retries a failed training once.
   A repeat would point to hardware instability, which must be reported.

## D093 — Formal-profile runs: held-out deal book, fixed length, manifest (2026-10-05 17:01 UTC)

The development standings (100 pairs per opponent, seed 7711 and its relatives) were also the data
that steered development, so they cannot support a claim. EVALUATION.md asks for a held-out frozen
setup book, no optional stopping and no pondering.

1. Formal results come only from `engine/tools/formal.py`: 500 duplicate pairs, fixed length, no
   SPRT, no pondering, one game at a time, on the deal book with seed 72335360501015 (the first 12
   hex digits of sha256("jqe formal deal book 1")). The run directory holds a manifest with the
   source commit and the sha256 of both engines and their weights; the same command continues an
   interrupted run and a changed argument is refused.
2. No development decision may use a formal game. The book certifies jqe-v0.15g + it014 only; a
   changed engine or net is certified on a new book phrase.
3. Two profiles. `f60t8`: 60+0.6, 8 threads and Hash 1024 for each side, for the opponents that
   use threads (AB-JChess, Mistboard, Pikafish jieqi_old, pikajieqi-enhanced). `f2s1`: 2 s per
   move, one thread, Hash 256, for universe and musesfish, which jqe beats about 99 to 1; the
   single thread is a handicap for jqe relative to the MISSION profile.
4. Every formal result is reported with its deviations from the MISSION profile: the opponent has
   8 threads, not every useful thread of the host; the host is shared with other jobs, mine and the
   owner's, which slows both sides; an engine failure voids a game (it is replayed once) while a
   time forfeit counts as a loss; void and forfeit counts are given by engine.
5. Certification belongs after the engine is frozen. The exploiter test (D094) therefore runs
   before the remaining formal runs. If it leads to a change of engine or net, the formal runs
   are repeated for the new version.

## D094 — Exploiter test 1: preregistration (2026-10-05 17:01 UTC)

MISSION requires that no fixed-budget exploiter wins more than 60% against the champion.
EVALUATION.md requires the budget, seeds, opponent access, selection protocol and an untouched
evaluation book to be fixed first. This entry is written before any game of the test is played.
A pipeline dry run on throw-away seeds (140 games, deleted) preceded it.

- **Champion (frozen):** tag `jqe-v0.15g-it014`; binary sha256 d382bce0…5c03d, net it014.jqn
  sha256 f90bd44e…8ba160; default options, one thread.
- **Exploiter class:** the same binary with a net fine-tuned from the champion's weights
  (`engine/nets/cand-it014/best.pt`) on the exploiter's own games against the champion, default
  options. Other UCI option values ("arms") may be tried in any round; their games count in the
  budget and they enter selection like the nets.
- **Opponent access:** white box. The exploiter's author has the champion's source, weights and
  as many games against it as the budget allows. In play the exploiter goes through the same
  referee as every engine and never sees the champion's hidden information.
- **Budget:** 6 rounds of 20,000 games at 5,000 nodes per move for both sides (about 21
  core-hours), selection matches of 6,000 games (about 1 core-hour), training under 0.5 GPU-hours
  on the shared RTX 4090. Hard caps: 30 core-hours (wall time x workers, kept in
  `engine/exploit/xpl1/state.json`) and 0.5 GPU-hours.
- **Generation:** round k uses deal seed 9100+k in duplicate pairs, with 0 to 4 random opening
  plies per pair (the same prefix for both games). Records are the exploiter's own positions with
  its search score and the game result (`engine/tools/games2rec.py --side x`).
- **Training:** round k starts from round k-1's weights and trains 2 epochs at lr 3e-4, lam 0.5
  (half search score, half result), K = 430, on the first 3,000,000 self-play records of
  big-it014-0.bin plus the records of every round so far, each listed three times; seed 9100+k.
  lam, lr, weight and epochs may be changed between rounds on the strength of generation results
  only; every value used is logged in state.json.
- **Selection:** the nets of rounds 4, 5 and 6 each play 1,000 pairs against the champion at
  5,000 nodes on the selection book (seed = first 12 hex digits of sha256("jqe exploiter
  selection 1")). The highest score rate is the exploiter (ties: the later round).
- **Evaluation book (untouched until then):** seed = first 12 hex digits of sha256("jqe exploiter
  book 1"). E1: 500 pairs at 5,000 nodes per move, the training condition. E2: 500 pairs at
  10+0.1 on the node clock (NodesTime=900 for both), about 60 times more search per move, the
  nearest affordable stand-in for long time controls. E3, only if the exploiter's score rate in
  E1 or E2 is at least 0.55: the first 200 pairs of the book at 60+0.6 wall clock, one thread
  each.
- **Verdict:** the requirement fails if the exploiter's win rate (wins / games) exceeds 60% in
  E1, E2 or E3. Reported for each: win rate, draw rate, score rate, pentanomial interval and the
  draw-adjusted score wins / (wins + losses).
- **Commands:** `bash engine/train/xpl1.sh` runs rounds, selection, E1 and E2 without any choice
  left to me.

What a pass means: this exploiter, with this budget, did not exceed the threshold. It is not an
exploitability bound. Not covered: larger budgets, an exploiter that models the champion's
replies inside its search, exploiters built on other engines, and humans. A larger second test
(about 200 core-hours) is planned for when the formal runs free the cores. What a failure means:
the weakness is analysed, the champion is changed and retested on new book phrases.

## D095 — Exploiter test 1: training values from round 3 on (2026-10-05 22:35 UTC)

D094 lets lam, lr, weight and epochs change between rounds on the strength of generation results
only. Those results: round 2 (the net of round 1 against the champion) scored 0.4793, -14 Elo
[-19,-10] over 20,000 games; round 3 (the net of round 2) stood at 0.466, -23 [-37,-10] after
2,380 games. Each fine-tune made the exploiter weaker. Training loss ended at 0.0302 and 0.0298
against 0.0330 and 0.0334 on the held-out self-play file (0.0323 before any fine-tuning): the net
was fitting a small set seen six times.

1. From round 3 on: each round's records listed once (was three times), lam 0.7 (was 0.5; 0.7 is
   what the champion was trained with), lr 1e-4 (was 3e-4), 1 epoch (was 2). Everything else stays
   as registered in D094: start from the previous round's weights, base file, seeds, round size,
   selection among rounds 4 to 6, evaluations E1 to E3 and the verdict.
2. No game on the selection book or the evaluation book had been played when this was decided.
3. The round-3 generation was stopped to apply this (twice, see the journal; 736 s booked to the
   budget) and continues from its games file. `engine/train/xpl1.sh` carries both sets of values.
4. Stated now, before the evaluations: I do not expect this class of exploiter to pass the
   champion. Its games are against a near-identical engine, so they carry almost no information
   that is specific to the opponent. The test runs to the end as registered whatever I expect.

## D096 — Exploiter test 1 passed; no larger test of the same class (2026-10-06 09:48 UTC)

Exploiter test 1 (D094, D095) ended with the selected exploiter at win rate 0.481 (E1, 5,000
nodes per move) and 0.463 (E2, 10+0.1 on the node clock) over 500 pairs each on the untouched
book; score rates 0.4915 and 0.4790. The threshold is a win rate above 0.60. Budget used: 12.7
core-hours and 0.05 GPU-hours.

1. The MISSION item "no fixed-budget exploiter wins >60%" is recorded as: one preregistered
   test passed, of a weak class. It is not an exploitability bound and is not to be described
   as one.
2. The larger second test of the same class announced in D094 is dropped. The generation
   rounds show why it would say nothing new: the exploiter's games are against a near-identical
   engine, and every fine-tune left it below the champion (-8 to -22 Elo over 20,000 games each).
3. A meaningful next test would need a different class: an exploiter that models the champion's
   replies inside its search, or one built on a different engine. Neither is built. They are
   listed as untested in REPORT.md.
4. The engine and net are unchanged, so the formal runs continue for jqe-v0.15g + it014 on the
   same held-out book: Mistboard, Pikafish jieqi_old and pikajieqi-enhanced (f60t8) after
   AB-JChess on lane d; musesfish and universe (f2s1) on lane a.

## D097 — Long-clock check against AB-JChess before the remaining formal runs (2026-10-07 09:01 UTC)

The formal result against AB-JChess is +158 [+136,+181] at 60+0.6 with 8 threads each. The owner's
goal is full games at much longer clocks, and that is where the evidence is thinnest: before
v0.15 the margin over AB-JChess shrank with thinking time, AB-JChess gained more from extra time
than jqe did at short clocks, and nothing has been measured beyond 60+0.6 since.

1. Lane d runs a development match first: jqe-v0.15g + it014 against AB-JChess at 300+3, 8
   threads and Hash 1024 each, seed 7711 (the development seed of all standings against
   AB-JChess), up to 100 pairs, `engine/runs/c300t8-v015g-abjchess`. About 12 minutes per game,
   so about 40 h for 200 games. It is a development run: interim readings may be used, and it may
   be cut at 100 games if the answer is clear either way.
2. The formal run against Mistboard, started 08:57 UTC and stopped after one game, continues
   after it from its games file, then Pikafish jieqi_old and pikajieqi-enhanced. Reason for the
   order: this is the measurement whose outcome is uncertain and could redirect the work, while
   the three remaining formal runs are against engines jqe led by 270 to 300 Elo in development.
   If the long clock shows a serious loss of margin, development resumes and the certification of
   v0.15g stops being the priority.
3. One 8-thread match at a time. Running it beside a formal run would put 27 threads on the 32
   logical CPUs with the owner's other job and would degrade both.

## D098 — Thread profile: equal threads, by the owner's ruling (2026-10-11 23:31 UTC)

MISSION.md asks for "same wall-clock move allowance, opponents allowed useful CPU threads with
about 8 reserved for ours". It had been read as jqe on 8 threads and each opponent on every thread
that helps it (up to 24 on this host). The formal runs give both engines 8 threads (D093), and
REPORT.md listed that as a deviation. At 23:31 UTC on 2026-10-11 the owner ruled: "Equal threads is fine as the
standard".

1. The thread item of the claim is equal threads: 8 each in the 60+0.6 runs (AB-JChess, Mistboard,
   Pikafish jieqi_old, pikajieqi-enhanced); jqe on one thread in the 2 s per move runs against
   musesfish and universe-st, which D093 counts among the engines that do not use threads. Equal
   hardware is also the convention of the Xiangqi rating list on the Pikafish wiki (4 cores each).
2. No opponent run with 16 or 24 threads is needed; the extra formal run against AB-JChess on 16
   threads, proposed on 10-11, is dropped.
3. The shared host stays a stated deviation: neither engine is guaranteed its cores (measured
   slowdowns in JOURNAL.md and REPORT.md).
4. Consequence: if the pikajieqi-enhanced run ends at +100 or more with its lower bound above +50,
   every numeric item of MISSION.md is met. The exploiter item is met by the letter only (D096: one
   preregistered test of a weak class, not an exploitability bound). A claim would then say "against
   every Jieqi engine available to us", carry these caveats, and list the untested engines, above
   all the unpublished Pikafish Jieqi NNUE.
