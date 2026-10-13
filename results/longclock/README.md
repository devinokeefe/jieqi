# Long clock against AB-JChess

`c300t8-v015g-abjchess`: jqe v0.15g with the net it014 (named `v015g`) against AB-JChess v0.2b
(`abjchess`), 300 s + 3 s per move, 8 threads and Hash 1024 MB each, one game at a time, on the
development deal book of seed 7711, not the held-out formal book. It was a development run
(docs/DECISIONS.md, D097), planned for up to 100 pairs and stopped after 100 games, 50 complete pairs.
Only the games were kept: there is no summary or manifest. The command, from the root of the working
repository:

```sh
python3 engine/tools/match.py \
    --engine v015g=engine/bin/jqe-v0.15g:EvalFile=$PWD/engine/nets/it014.jqn --engine abjchess=abjchess \
    --games 200 --tc 300+3 --threads 8 --hash 1024 --concurrency 1 --seed 7711 --scores --resume \
    --out engine/runs/c300t8-v015g-abjchess
```

`EvalFile` is an absolute path because match.py starts each engine in its own directory.
`tools/check_results.py` prints the pentanomial interval of this run twice: with population variance,
as match.py computes it, and with n−1 variance, as `engine/tools/formal_report.py` does.
