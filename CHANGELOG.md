# Changelog

## 0.1.0 (2026-10-13)

The first release.

* **Engine.** jqe v0.15g, an alpha-beta engine with chance nodes for face-down movers and a UCI
  interface, in C++20 ([engine/README.md](engine/README.md)).
* **Net.** it014 (`engine/nets/it014.jqn`), the network the results were played with, and its
  training record ([results/training/](results/training/)).
* **Referee.** The rules library in `native/`, which decided every game, with its tests and the
  Python interface in `jieqi/` ([docs/NATIVE.md](docs/NATIVE.md), [RULES.md](RULES.md)).
* **Match harness.** Refereed matches in colour-swapped pairs on seeded deals
  (`engine/tools/match.py`, `formal.py`), the adapters for musesfish and universe-st Jieqi, and
  the recipes for the opponents ([THIRD_PARTY.md](THIRD_PARTY.md)).
* **Results.** The records of the formal runs, of a long-clock run against AB-JChess and of the
  exploiter test ([results/README.md](results/README.md)).
* **Checks.** `tools/check_results.py` recomputes every result from the records, and
  `tools/check_all.sh` builds and checks a clean clone ([CONTRIBUTING.md](CONTRIBUTING.md)).

The opponents, the AB-JChess net and the engine's training data are not in the repository.
THIRD_PARTY.md says where the opponents come from and how they were built.
