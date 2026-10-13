# Third-party software

The engine (`engine/`), the referee (`native/`, `jieqi/`), the adapters and the tools are original
code under the MIT licence (LICENSE), with one exception: `tools/repair_ab_release.py` quotes two
lines of AB-JChess's source and is under the GPL-3.0-or-later (its header says so).

No opponent's code, binary or network is included. Each opponent ran as a separate process,
talking to `engine/tools/match.py` over UCI, either directly or through an original adapter in
`adapters/`, and saw only its own player's observation. `tools/fetch_opponents.py` fetches each
at the commit below into `$JIEQI_OPPONENTS` (by default `~/jieqi-opponents`).

All three Pikafish-family opponents were classical builds: `USE_NNUEEVAL` is 0 in their
`src/types.h`, so they evaluate without a network, and no Pikafish network was used anywhere.

## Opponents

### Pikafish jieqi_old

- Source: https://github.com/official-pikafish/Pikafish, branch `jieqi_old`, commit
  `23b9466c981f0f3a1133f92de1a6f86406c4eccc`.
- Licence: GPL-3.0 (`Copying.txt`).
- Use: opponent `pikafish-old` of the formal run `f60t8-v015g-pikafish-old`. Built with
  `make -j2 all ARCH=x86-64-bmi2 COMP=gcc` (`tools/build_classical_opponents.py`).
- Not included.

### Mistboard PikaJieQi

- Source: https://github.com/brianhliou/pikafish-jieqi-wasm, branch `jieqi_old-mistboard`,
  commit `6398d4c191274a8f6ad43c9ce3b2d418a84da5c3`.
- Licence: GPL-3.0 (`Copying.txt`).
- Use: opponent `mistboard` of the formal run `f60t8-v015g-mistboard`. Built as Pikafish
  jieqi_old.
- Not included.

### pikajieqi-enhanced

- Source: https://github.com/CoderYiXin/pikajieqi-enhanced, commit
  `7d5ca267f23c9c5cb57315607a18a55de17808b1`.
- Licence: GPL-3.0, inherited from Pikafish (its README; the repository has no licence file).
- Use: opponent `pikaenh` of the formal run `f60t8-v015g-pikaenh` (results/README.md). Only `src/` was built, with
  `make ARCH=x86-64-avx2 build`; the repository's online bot script was never run.
- Not included.

### AB-JChess v0.2b

- Source: https://github.com/lxsgx23/AB-JChess, commit `cb0a48fe5820a401fd561016f378fac5041752f9`.
  Net: `abjchess-20260911.nnue` (sha256 `7a229d324e50d2b0acf3e5878a8f876b96a24b75d16c8492a3c3bf8e1418d944`)
  from the asset `0.2b_bmi2.zip` (sha256
  `6cb9cfe44946e5e4494643d32ae6352f7240c7e43d0ecbb4a437b04d7c388b03`) of the release v0.2b,
  https://github.com/lxsgx23/AB-JChess/releases/tag/v0.2b.
- Licence: GPL-3.0 (`LICENSE`; the source files say GPL-3.0-or-later). The net comes with no
  licence of its own; nothing allows passing it on.
- Use: opponent `abjchess` of the formal run `f60t8-v015g-abjchess` and of the long-clock run.
  Built from source with `make -j1 build ARCH=x86-64-bmi2 COMP=gcc` after a repair of
  `src/position.h` without which it does not compile (`tools/repair_ab_release.py`: one
  declaration moved to the public part of the class, two members declared, no function body
  changed). The publisher's Windows executable was never run.
- Not included: neither the source, the binary nor the net. The net is never redistributed.

### musesfish

- Source: https://github.com/miaosiSari/Jieqi, commit `3de6c17ae6dafa035b5eea5ec7d6b7f39118aab6`;
  the engine `musesfish_pvs_20210528_fixed.py` and the `board/` modules it imports.
- Licence: GPL-3.0 (`LICENSE.md`).
- Use: opponent `musesfish` of the formal run `f2s1-v015g-musesfish`, run from source in a
  separate Python process by the worker of `tools/package_musesfish.py`, behind the shim in
  `adapters/musesfish_uci/`.
- Not included.

### universe-st Jieqi

- Source: https://github.com/universe-st/Jieqi, version 1.7.1, commit
  `3579f28e5fd1f1ccb67f9b368ca89a12a755324c`.
- Licence: MIT (`LICENSE`).
- Use: opponent `universe` of the formal run `f2s1-v015g-universe`, at difficulty hard. Its
  modules `src/core/*.ts` and `src/ai/*.ts` are imported read-only by the adapter in
  `adapters/universe/`, run with Node.js (v24 in the recorded runs).
- Not included.

## Used to check the referee

### Pikafish, Jieqi branch

- Source: https://github.com/official-pikafish/Pikafish, branch `jieqi`, commit
  `9b963f727983a1d9308e0dca48b39c802b8e75a2`.
- Licence: GPL-3.0 (`Copying.txt`).
- Use: its rules code, in separate diagnostic programs with patches that only print what it
  computes, was compared with the referee in `native/` (docs/NATIVE.md, docs/RULE_FIXTURES.md).
  It was not an opponent, and its network was not used.
- Not included.

## Tools

- CMake, GCC and Python build and run the engine, the referee and the harness (the results used
  CMake 3.28, GCC 13.3 and Python 3.12 on Ubuntu 24.04 under WSL2).
- PyTorch and NumPy train the networks (`engine/train/`); they are not needed to run anything else.
- Node.js runs the universe-st adapter.

None of them is included.
