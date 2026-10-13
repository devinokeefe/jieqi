#!/bin/bash
# Exploiter test 1 against jqe-v0.15g + it014, as preregistered in docs/DECISIONS.md D094 (training values of rounds 3-6: D095).
#   bash engine/train/xpl1.sh [WORKERS]      (run from the repository root; safe to re-run after an interruption)
# Six rounds of 20,000 games at 5,000 nodes per move, selection among the last three nets on the selection book,
# then the two evaluations on the untouched book. Nothing here looks at an evaluation result to decide anything.
set -e
cd "$(dirname "$0")/../.."
W=${1:-1}
X=".venv/bin/python engine/train/exploit.py"
N=xpl1
BASE=engine/data/xpl-base-3m.bin
[ -f $BASE ] || head -c 336000000 engine/data/big-it014-0.bin > $BASE   # the first 3,000,000 self-play records of it014
[ -f engine/exploit/$N/state.json ] || $X init $N --binary engine/bin/jqe-v0.15g --net engine/nets/it014.jqn \
    --init-pt engine/nets/cand-it014/best.pt --base $BASE
rounds() { .venv/bin/python -c "import json; print(len(json.load(open('engine/exploit/$N/state.json'))['rounds']))"; }
while [ "$(rounds)" -lt 6 ]; do
  if [ "$(rounds)" -lt 2 ]; then
    H="--weight 3 --lam 0.5 --lr 3e-4 --epochs 2"   # rounds 1 and 2, as first registered
  else
    H="--weight 1 --lam 0.7 --lr 1e-4 --epochs 1"   # rounds 3 to 6 (D095): the first two fine-tunes made the net weaker
  fi
  $X round $N --games 20000 --nodes 5000 --concurrency $W --random-plies 4 --seed-base 9100 $H
done
for k in 4 5 6; do
  $X eval $N sel --phrase "jqe exploiter selection 1" --pairs 1000 --round $k --concurrency $W --count
done
$X eval $N e1 --phrase "jqe exploiter book 1" --pairs 500 --round best:sel --concurrency $W
$X eval $N e2 --phrase "jqe exploiter book 1" --pairs 500 --round best:sel --tc 10+0.1 --nodes-time 900 --hash 128 --concurrency $W
$X status $N
