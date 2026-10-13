# Observation and replay contract, version 1

> Written in September 2026, while the referee in `native/` was being built, and kept as written
> apart from local paths and status notes that had gone out of date. Files it names under
> `research/`, `configs/` and `tools/`, and modules of `jieqi/` other than the six in this
> repository, belong to the project's working repository and are not part of this release.

`RefereeRecord.record_unchecked_move` checks occupancy, side to move, capture ownership and king preservation, but deliberately does not validate movement geometry, check, repetition, chase or terminal results. Legality, check, repetition and results come from the native library (`jieqi/native.py`, docs/NATIVE.md).

## Coordinates and setup

Square index is `rank * 9 + file`, files a–i, ranks 0–9 with red at rank 0. Board strings contain 90 characters in that order. Uppercase pieces are red; lowercase are black. Visible piece codes are R/N/B/A/C/P/K; X/x are hidden and `.` is empty. Kings are face up at e0/e9. Hidden piece roles come from original starting points, independently of their true identities.

`sha256-fy32-v1` accepts an unsigned 64-bit seed. Each color has an independent deterministic word stream. Hash input is ASCII `jieqi/setup/v1`, a null byte, eight little-endian seed bytes, ASCII `red` or `black`, a null byte, then an eight-byte little-endian block number beginning at zero. SHA-256 digests yield eight little-endian uint32 words in byte order. To sample below n, reject words >= `floor(2^32/n)*n`, then take the remainder modulo n. This removes modulo bias under the pseudorandom-word model; it does not constitute proof of cryptographic or physical randomness.

For each color, begin with `RRNNBBAACCPPPPP` and use descending Fisher–Yates swaps i=14 through 1, sampling j in [0,i]. Assign to red points `a0 b0 c0 d0 f0 g0 h0 i0 b2 h2 a3 c3 e3 g3 i3`, or the same files with ranks reflected for black. Golden vectors for seeds 0, 1 and 2^64−1 are frozen in the tests. File mirroring transforms the complete deal and every event, not just a network input tensor.

The referee ledger stores the explicit initial truth as well as seed provenance, and verifies agreement when loading seeded records. `explicit-v1` is for original manual fixtures; it cannot assert a seed. Decimal seed strings preserve uint64 values across JSON consumers. Neither seed nor true layout is an observation field. Duplicate pairs will reuse one explicit deal and swap engine seats; never reuse an engine's hidden-piece cache across the pair.

## Separate wire formats

`jieqi-referee-ledger-v1` is private. Its fields are schema, setup (generator/seed/mirrored/board_truth), capture_visibility, counter_policy and moves. Moves are four-character coordinates without client-supplied identity suffixes: the referee derives identities from its fixed deal. Replay is deterministic but currently checks structural validity only. Unknown schema fields and unsupported versions/counter policies are rejected.

`jieqi-observation-v1` is an explicit whitelist: viewer, side_to_move, public board, pool knowledge, observed history, ply, no_capture_plies, capture_visibility and counter_policy, plus schema. Each observed move contains from/to/actor, public mover reveal, whether a capture occurred, whether its target was hidden, and captured identity only when allowed. Current counters implement capture-only reset with all plies counted; other configurations are not silently supported.

For each side, pool knowledge contains candidate identity counts, live-hidden count and unknown-captured count. Candidates include live hidden pieces **and** captured identities unknown to that viewer. Their sum equals the latter two counts combined. Under capturer-only visibility, the opponent's live pool is exact; your own candidate pool retains identities secretly taken by the opponent. A bright capture does not subtract a previously revealed identity a second time.

Cache keys hash only canonical observation JSON, including the viewer and full observed history. Tests compare different true worlds that yield the same observations, including altered privately captured identities and permutations of still-hidden pieces. These are application-level noninterference checks; OS process isolation and network-input/move-mask tests remain future harness work.

## External FEN and chance interface

`Observation.pikafish_fen()` emits board / side / candidate-counts / no-capture-ply / fullmove fields. Count order is R,A,C,P,N,B for red then black. The accompanying per-player history uses four coordinates, optional public mover identity, then optional known captured-dark identity. Bright-target captures have no identity suffix. FEN alone cannot represent repetition or the entire information history. These encoders have local fixtures but await independent native-engine handshake/replay validation.

`neutral_reveal_outcomes` consumes only the acting player's observation and a structurally valid move. It enumerates up to six mover identities and six target identities (36 joint outcomes), using exact rational probabilities. Already-bright/empty participants contribute no random identity. For uncertain own pools, its marginal averages the hypergeometric prior: candidate count divided by total candidates. Separate sides' chance-only assignments factorize. This prior ignores informative opponent actions; it is not a learned posterior or an equilibrium search method. Sampled private outcomes must be reprojected through visibility before either player's policy is called.

## Validation boundary

The suite covers inventory conservation, hidden-information equivalence, visibility variants, reveal suffixes, counters, deterministic replay, seed provenance and mirroring. Its randomized campaign contains 2,400 **structural ledger transitions**, some illegal as chess moves by design. Zero of these count toward the required 10M legal random-playout moves. C++ movement, Python bindings, independent perft, chase adjudication, timed adapters and ratings are still outstanding.

## Observation decoder and diagnostic subprocess, 2026-09-28

`jieqi/observation_wire.py` now loads this whitelist by replaying only public start geometry and observed events. It rejects unknown fields, duplicate JSON keys, nonfinite values, boolean counter aliases and inconsistencies in board/pools/history/visibility. It does not validate movement or terminal rules. The observation-only musesfish worker consumes this decoder and disables the external UI's true-layout APIs. ADAPTERS.md documents the diagnostic JSON envelope, actual privacy/search checks and unfulfilled match-admission requirements. The parent process never imports the GPL engine, and the worker never receives referee truth.

## Frozen diagnostic transcripts, 2026-09-28

RULE_FIXTURES.md describes four explicit-deal cases and 30 per-player prefix transcripts in research/fixtures/replay-transcripts-v1.json. Hand-authored suffixes and an independent structural reader are checked against production observations and mirrors. These are intended future UCI inputs, not observed external responses or legal-game records. Compare each debug FEN because the pinned parser silently truncates replay at an illegal move; readiness alone is insufficient. Candidate count/key consistency after a private capture remains a source-derived runtime probe.

## Referee integrity binding (2026-09-28)

The Python ledger now verifies its cached truth against an independent structural replay from the immutable setup. Every event must have the right actor, coordinates, moved identity/reveal and captured piece; the final board and exact capture-only clock must agree. Immutable container and enum/integer field types are enforced. Material totals alone previously failed to detect hidden-identity swaps, misplaced bright pieces, false reveals and stale clocks. A deliberately forged king-capture history could also balance inventory; it is rejected by replay.

Seed claims are checked in the Setup constructor, including the mirror flag, so direct Python construction has the same provenance check as wire loading. The seed algorithm and golden vectors are unchanged. Alternative counterfactual deals must remain explicitly identified as explicit setups. The observation wire schema and capturer-only projections are unchanged.

NativeRules.advance validates input integrity before querying native status/legality, preventing a later capture from masking a stale input clock. It still compares the native public board with the structural result and validates the output. Python tests of that call order use mocks and are not C++ execution. The ledger remains deliberately movement-unchecked: an occupancy-valid teleport still passes structural replay. Native legality, repetition/chase and all phase gates remain separate.

## In-memory observation and chance validation (2026-09-28)

`validate_observation` checks immutable container shapes, exactly six candidate counts per pool, typed colors/events, then reuses the public-history wire decoder. This check runs before chance enumeration, public-history reconstruction, classical UCI encoding and resident-session dispatch. Direct Python construction can otherwise bypass wire validation. In particular, a seventh pool entry used to affect chance denominators while disappearing from the serialized six-key pool; accepting it could emit probabilities totaling 15/16. Negative/oversized probabilities and stale/private-inconsistent histories were also reproduced with deliberate malformed inputs. The wire schema and valid projections remain unchanged. These are input-corruption tests, not observed game failures.

Exact enumeration verifies the neutral prior with 144 equiprobable explicit deals: four variable slots per color contain RRNP, the other identities are exposed by a fixed structural prelude, then zero/one/two private captures are conditioned on. Three visibility profiles and both file orientations yield 2,592 world/observation instances, 42 information sets and 290 joint-support entries. Counts of actual identities in each observational-equivalence class match every predicted rational probability. With one unknown own capture from RRNP, the next rook chance is 1/2; uniform remaining count vectors would incorrectly give 5/9. This is a finite fixture check of the neutral chance prior, not a learned posterior, legality test, or general exploitability proof.

Validation currently replays history at each public API boundary. Profile real search before adding a trusted validated-view cache; do not silently weaken the checks for speculative speed. Chance outcomes still describe latent identities and must be reprojected through the selected visibility rule before policy calls. No successor-view/search implementation or move legality is implied by this change.
