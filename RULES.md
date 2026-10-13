# Rules and information structure — working specification

> Written in September 2026, while the referee in `native/` was being built, and kept as written
> apart from local paths and status notes that had gone out of date. Files it names under
> `research/`, `configs/` and `tools/`, and modules of `jieqi/` other than the six in this
> repository, belong to the project's working repository and are not part of this release.

Research snapshot: 2026-09-28 Europe/London. This document specifies a **Tiantian-intended profile with explicit open-engine fallbacks**, not certified equivalence to the current Tiantian app. `docs/rules-tiantian-intended-v0.json` names the options. The referee in `native/` implements the default fallbacks (docs/NATIVE.md, docs/ADJUDICATION.md).

## Source hierarchy

1. Direct Tiantian rules are preferred. The [official 2017 Sanya championship regulations](https://xiangqi.qq.com/webplat/info/news_version3/15003/24026/24044/24047/m15147/201710/644928.shtml) are now archived and reviewed. They explicitly describe play through the Tiantian app and give historical adjudication/visibility evidence. The homepage had previously timed out; ordinary public HTTP retrieval now succeeds. These dated rules do not certify the current app. See the historical evidence section below.
2. Pinned [Pikafish Jieqi source](https://github.com/official-pikafish/Pikafish/tree/9b963f727983a1d9308e0dca48b39c802b8e75a2): `src/position.cpp`, `bitboard.h`, `bitboard.cpp`, `movegen.cpp`, `engine.cpp`. Implementation is stronger evidence than stale comments. This is the initial interoperability fallback; no local strength ordering exists yet.
3. [JieqiBox maintainer rules](https://github.com/Velithia/JieqiBox/wiki/What-is-Jieqi%3F) support standard setup, positional dark movement, unrestricted bright advisors/elephants, and stalemate loss. Its captured-piece wording is ambiguous about observer identity; use actual per-view history code as corroboration.
4. [JieqiArena history filtering](https://github.com/Velithia/JieqiArena/blob/3a1e4efd9a584cf07842dba1c424d0fa11e36985/src/game.cpp#L290) sends dark capture identity only to the capturer. Its terminal logic is not an oracle.
5. [Qizhe's own platform rules](https://qizhe.org.cn/home/?p=848) corroborate owner ignorance after a dark capture, but describe different repetition/check/chase counters, exclusions, and a maximum game length. They are evidence of variation, not Tiantian rules.
6. [Mistboard's rules](https://mistboard.com/rules/jieqi), updated 2026-09-17, explicitly confirm capturer-only dark-capture visibility, positional first moves and stalemate loss. Its 120-ply no-capture draw and absence of separate repetition draws are platform-specific, not Tiantian evidence.

## Board, setup and moves

- Board: files a–i, ranks 0–9, red's home rank 0; red moves first. Kings e0/e9 are face-up and never shuffled. Each side independently uniformly shuffles R2/N2/B2/A2/C2/P5 across its 15 ordinary nonking start squares. The referee stores the immutable assignment and seed; neither engine receives them.
- A dark piece moves/captures as the ordinary role of its starting square, then reveals at its destination. No stationary flip action. A piece cannot remain dark after moving. Moved-piece identity is public; captured dark identity follows the visibility option. Pin: `engine.cpp:158–185`.
- Chariot: any unobstructed orthogonal distance. Cannon: same noncapture movement, exactly one intervening piece to capture. Horse: (2,1) leap blocked by the orthogonal adjacent leg. Dark and bright pieces both block rays, legs, and elephant eyes.
- Bright advisor: one diagonal step anywhere on the board; no palace/river restriction. Dark advisor first move remains in its own palace. Pin: `position.cpp:404–407`, `bitboard.cpp:134–135`.
- Bright elephant: exactly two diagonal steps, midpoint empty; may cross the river, with no requirement to land on a traditional elephant point. Pin: `bitboard.cpp` bishop lame-leaper generation. Dark elephant uses its starting role for its first move.
- Soldier: one forward step anywhere on its own half, including when revealed on its own back rank. Sideways one step becomes available at red rank >=5 or black rank <=4. Never backward, no promotion. On the enemy back rank it can move sideways only. This follows current rank, not remembered crossing history. Pin: `bitboard.h:167–174`.
- King: one orthogonal step inside its own 3x3 palace. Exposing facing kings on an otherwise empty file is illegal. Move generation must enforce own-king safety against public bright types and positional dark roles. Giving check is evaluated after the mover's reveal. Pin: `position.cpp:379–425` and `do_flip`.

## Endings and unsettled adjudication

Checkmate and stalemate lose for the player with no legal moves. Default check evasion is mandatory; do not import coursework variants that allow ignoring check/capturing the king. Resignation and timeout lose. Process failures remain recorded with cause and are adjudicated under a frozen harness policy.

Initial fallback: the pinned Pikafish branch increments `rule40` every ply and resets it **only on a capture** (`position.cpp:618–621,669–670`). A noncapture reveal does not reset it (`do_flip:489–539`), nor does a soldier advance. At >=80 plies it draws unless the side to move has no legal moves, which loses (`1176–1180`). The comment mentioning rule 60 is stale. Qizhe instead describes reveal resets and excluded checking/evasion plies. The exact current Tiantian check-clock algorithm remains unverified; dated official evidence is below. Do not silently combine these policies.

Repetition fallback uses the pinned engine's root adjudication, including perpetual checking/chasing penalties. Its search uses some earlier twofold cutoffs; these are not automatically match rules. docs/ADJUDICATION.md now gives an original source-derived specification for check/chase responsibility, protection, threat renewal, target identity, history boundaries and precedence. Eight concrete cycle fixtures and 16 pending coverage cases are recorded in research/fixtures/adjudication-v0.json. Their expectations have not been independently executed. The new pinned helper requires a third occurrence at search ply zero; the classical helper differs. Ordinary UCI search skips the helper at its root, so a root score is not an adjudication verdict. Mere threefold-equals-draw is insufficient.

No automatic material shortcut or absolute total-ply draw is confirmed in this pinned `rule_judge`. Use no such shortcut by default. A harness resource cap produces an unresolved/technical outcome, never an invented draw. Freeze any explicit game-length rule before rating matches.

Known unsuitable referee: [JieqiArena `game.cpp:184–200`](https://github.com/Velithia/JieqiArena/blob/3a1e4efd9a584cf07842dba1c424d0fa11e36985/src/game.cpp#L184) makes stalemate a draw and all threefold repetitions draws. `main.cpp` also reports caught crashes as draws. Its random pool draws do not by themselves establish identical seeded piece assignments for duplicate pairs.

## Information structure: verified consequence and limits

The pool asymmetry follows under capturer-only visibility. For player A, opponent B's live dark pool is exactly initial B inventory minus public B reveals minus dark B pieces captured by A. A's own live pool is uncertain because B's private captures of A are unknown to A. Before any such capture, both sides' pool counts are common knowledge. With both-visible capture rules, the game becomes a public stochastic game.

Face-down identities physically exist at setup; an information-safe simulator can defer sampling them until needed because unseen slots are exchangeable. These are equivalent probability models only with conditional sampling **without replacement**. The referee will preassign identities to make duplicate pairs reproducible. Six types, not seven, are possible at a single reveal. A dark mover capturing a dark target entails up to 6x6 joint type outcomes, with public mover revelation and private capture observation.

This is substantially less asymmetric private information than Stratego, but it is not strategically perfect information. Opponent actions after private captures can signal their knowledge of your pool. Determinizing then maximizing independently in each world permits strategy fusion. Simulated opponent policies must see only that opponent's simulated information set; sampling a world must never reveal it to either network. Search keys must include the observing player, observable history/private record and rule counters, not the referee seed or true hidden layout.

The chance-only baseline is uniform over consistent **labeled assignments**, not count vectors. With publicly unrevealed inventory n and k own dark pieces secretly captured, loss-vector c has probability `product(comb(n[t],c[t])) / comb(sum(n),k)`, conditional only on inventory and capture count. Opponent action likelihoods produce a different posterior. `research/belief_prior.py` implements this distinction and is checked against independent subset enumeration. Uniform count vectors will be retained as an explicitly named heuristic ablation if useful, not described as the fair shuffle prior.

All possible capture-count vectors lie within 3^5*6 = 1458 possibilities before conditioning on total captured; exhaustive enumeration gives a maximum of 216 at a fixed capture count. This makes exact count-distribution baselines plausible. It does not bound the entire perfect-recall information tree or prove small exploitability. Preserve capture order/history for policy observations even if counts suffice for future physical chance dynamics.

## Serialization and validation plan

Pikafish uses five fields: `board side rest_counts halfmove fullmove`. Dark markers are X/x; bright letters RACPNBK/racpnbk. Initial rest field is `R2A2C2P5N2B2r2a2c2p5n2b2`. These are per-view unrevealed identity candidates: one's own counts can include secretly captured pieces. Never replace them with the referee's true own remaining pool.

Move history uses four coordinates, then an optional public moved-dark identity, then an optional captured-dark identity visible only to the capturer. For a bright mover taking a dark target, only the capture suffix is present. Preserve full per-player histories, since FEN alone loses repetition and knowledge chronology. Versioned JSON now separates `jieqi-referee-ledger-v1` and `jieqi-observation-v1`; see docs/PROTOCOL.md. The ledger is structural and does not yet validate legal moves. External FEN is an adapter format, with independent engine compatibility still pending.

Pikafish `perft.h` calls `do_move` but not `do_flip`: depth>1 with dark movers is **not chance-complete perft**. Use depth-one legal sets for mixed positions and deeper perft on fully revealed positions; separately cross-check explicit reveal transitions and enumerate chance outcomes in our oracle.

Required fixtures include every movement boundary/blocker, advisor first-move restriction, soldier back ranks/river thresholds, a reveal giving check, flying-general exposure, all dark-capture visibility cases, 79/80-ply boundary/reset behavior, mate before draw, perpetual-check/chase cases and observed-equivalent state pairs. The 10M-move invariant campaign and independent agreement remain unrun.

## Repetition construction evidence, 2026-09-28

Four remaining cases now have legal movement histories in research/fixtures/repetition-cases-v1.json. The [Asian Xiangqi Federation 2017 rulebook](https://www.asianxiangqi.org/%E6%AF%94%E8%B5%9B%E8%A7%84%E4%BE%8B/%E6%AF%94%E8%B5%9B%E8%A7%84%E4%BE%8B_2017.pdf) supplies mutual-check geometry (figure 4) and a mutual-chase cycle (figure 48); our reduced boards and two further constructions test the selected engine convention. This source is xiangqi evidence, not proof of Tiantian rules. The PDF is archived separately with SHA-256 f3b49c494520253ace8ea321fab05f9909ebff9ccc879037c58d6f361d2f597a.

All 132 history prefixes and 72 complete depth-one move sets/check flags match a pinned published opponent over original, mirrored and color/rank-exchanged boards. This resolves construction/legality questions only. Chase masks and final adjudication still need the newer direct helper and our compiled implementation. The [2024-08-31 Pikafish release notes](https://github.com/official-pikafish/Pikafish/releases/tag/Pikafish-2024-08-31) corroborate the check-interruption convention; the linked rule.html was inaccessible during that probe and has now been archived (see below). Qizhe's differing policy was rechecked, not adopted.

## Official historical Tiantian evidence (2026-09-28)

The [Sanya regulations](https://xiangqi.qq.com/webplat/info/news_version3/15003/24026/24044/24047/m15147/201710/644928.shtml) were published in 2017, with a 2017-10-13 signature. Section VII specifies six-round limits for checking/chasing, exempts soldier/king/advisor/elephant attackers from chase restrictions, gives fivefold neutral repetition and a 120-ply no-capture draw, and limits how checking rounds count toward that clock. It also provides an automatic draw for lack of attacking material. The display-secrecy instruction corroborates capturer-only dark-capture knowledge. Exact detection, check-clock accounting, material definitions and current-app continuity remain unresolved.

The [Wenzhou event regulations](https://xiangqi.qq.com/webplat/info/news_version3/15003/20947/20948/20949/20951/m13960/201707/605503.shtml) instead use a referee-approved 40-round count after all hidden pieces are revealed. This in-person tournament is a separate profile, despite being hosted on the same official site.

`docs/rules-tiantian-2017-evidence-v0.json` names these historical options and uncertainties. The active benchmark profile remains the coherent pinned Pikafish fallback (80-ply clock, third repetition, its chase rules); its known differences from historical Tiantian must be disclosed. Mixing isolated published thresholds into that helper would not establish a correct Tiantian implementation. No game defaults, native code or adjudication expectations were changed. Raw official pages, encodings, dates and hashes are in `research/data-source-discovery-v1.json`; they were read as documents only, without executing site code or connecting a bot.

## Published xiangqi rules and material-only counterexamples (2026-09-28)

The [Pikafish program-competition specification](https://www.pikafish.com/rule.html), revision 2023-11-22, is now accessible. It describes ordinary xiangqi, not Tiantian Jieqi. Chapter I.5 sets 120 counted noncapture plies: each side's first ten checks count; further checks and their induced evasions do not. Captures reset both counters. Mate/stalemate and a third repeated position take precedence. Chapter III excludes chase classification when the repetition interval contains any check; chase otherwise requires a continuing physical target and escape on every opponent reply. Chapter I.4 declares a draw when only kings/advisors/elephants remain. Its advisor/elephant movement restrictions differ from Jieqi. These provisions do not alter our pinned 80-ply fallback. Raw document SHA-256: `63658d28a0828365570550770341fce8142b69e1b5a117ca4e3332b2005d4ed3`; provenance: research/rule-method-source-audit-v1.json.

Our original constructions show why the ordinary material shortcut cannot simply be imported. All pieces below are revealed; Black is to move at the final position, and all unlisted squares are empty.

| Final board | Terminal geometry | Escape control |
|---|---|---|
| Red K e0, A e8; Black K e9 | Stalemate: d9/f9 attacked; capturing e8 exposes facing kings | Red K on d0 permits e9e8 |
| Red K e0, A c7/c8; Black K d9 | Checkmate: c8 checks d9, c7 covers d8, e9 exposes kings | Remove A c7: d9d8 is legal |
| Red K e0, B b6/b7; Black K d9 | Checkmate: b7 checks d9 through c8, b6 covers d8 through c7; e9 exposes kings | Remove B b6: d9d8 is legal |

The immediate moves producing these positions are respectively K d0-e0, A b7-c8 and B d5-b7. The separately pinned classical release accepted each move and the expected final complete move sets/check flags in original, mirrored and color/rank-exchanged orientations: 27 observed positions across 18 cases. These are sparse geometric witnesses with legal immediate predecessors; no full history from the shuffled starting position was constructed. Terminal labels are inferred from no-legal-move/check observations, not direct rule-helper outputs. The official Tiantian phrase about attacking material remains unresolved; neither a Tiantian verdict nor our native correctness follows. Preserve `insufficient_material=no_automatic_shortcut`.

## Implemented fallback and direct dark-chase observation — 2026-09-28 21:36 UTC

The independent snapshot helper confirms that a dark advisor at d0 can include c1 in its hypothetical chase set while d0c1 is absent from ordinary legal moves. It also confirms pool-independent dark-cannon target sets in the constructed R-vs-B candidate-pool pair. These are pinned-engine behaviors, not proof of current Tiantian rules. Full replay never receives captured private identities or unrevealed true assignments.
