#!/usr/bin/env bash
# The check of a clean clone: build and test the referee and the engine, then recompute every result in
# results/ from its game records. Run it from anywhere; it works on the repository it is in.
#
#   bash tools/check_all.sh
#
# It needs CMake 3.20 or later, a C++20 compiler and Python 3.11 or later; nothing is downloaded.
# Settings (environment variables):
#   JOBS=4            parallel build jobs
#   NICE=19           niceness of every build and test; NICE= runs them without nice
#   BUILD=build/check build directory, relative to the repository or absolute (the referee in
#                     BUILD/native, the engine in BUILD/engine)
#   DIFFTEST_GAMES=1000 DIFFTEST_SEED=1   the differential test of the engine against the referee
#   REPLAY=1          replay every recorded game through the referee (REPLAY=0 skips it)
#   VECTORS=1         if engine/tests/vectors.py is present, regenerate a small set of the test vectors
#                     with the new build (VECTORS=0 skips it)
# The exit status is 0 only if every step passes.
set -u
cd "$(dirname "$0")/.." || exit 2
ROOT=$(pwd)
JOBS=${JOBS:-4}
NICE=${NICE-19}
BUILD=${BUILD:-build/check}
case "$BUILD" in /*) ;; *) BUILD="$ROOT/$BUILD" ;; esac
DIFFTEST_GAMES=${DIFFTEST_GAMES:-1000}
DIFFTEST_SEED=${DIFFTEST_SEED:-1}
REPLAY=${REPLAY:-1}
NET="$ROOT/engine/nets/it014.jqn"
NET_SHA256=f90bd44e8ee244405eb08eb4f784e3f156900f0691f651b5124d50032f8ba160
LOG="$BUILD/logs"
mkdir -p "$LOG"

run() { if [ -n "$NICE" ]; then nice -n "$NICE" "$@"; else "$@"; fi; }
names=() results=()
step() {  # step NAME COMMAND...: run, keep the output in $LOG/NAME.log, record pass or fail
    local name=$1; shift
    local t0=$SECONDS
    printf '%-26s ' "$name"
    if "$@" > "$LOG/$name.log" 2>&1; then
        results+=("PASS"); echo "pass ($((SECONDS - t0)) s)"
    else
        results+=("FAIL"); echo "FAIL ($((SECONDS - t0)) s), see $LOG/$name.log"; tail -n 15 "$LOG/$name.log" | sed 's/^/    /'
    fi
    names+=("$name")
}

build_native() {
    run cmake -S . -B "$BUILD/native" -DCMAKE_BUILD_TYPE=Release -DJIEQI_SANITIZERS=OFF -DBUILD_TESTING=ON &&
    run cmake --build "$BUILD/native" -j "$JOBS"
}
test_native() { run ctest --test-dir "$BUILD/native" --output-on-failure; }
build_engine() {
    run cmake -S engine -B "$BUILD/engine" -DCMAKE_BUILD_TYPE=Release &&
    run cmake --build "$BUILD/engine" -j "$JOBS" --target jqe jqe_difftest
}
difftest() { run "$BUILD/engine/jqe_difftest" "$DIFFTEST_GAMES" "$DIFFTEST_SEED"; }
perft() {
    local out
    out=$(printf 'position startpos\nperft 1\nperft 2\nperft 3\nquit\n' | run "$BUILD/engine/jqe") || return 1
    echo "$out"
    echo "$out" | grep -q '^perft 1 44 ' && echo "$out" | grep -q '^perft 2 1926 ' && echo "$out" | grep -q '^perft 3 83907 '
}
bench() {
    local out
    echo "net sha256 $(sha256sum "$NET" | cut -d' ' -f1)"
    [ "$(sha256sum "$NET" | cut -d' ' -f1)" = "$NET_SHA256" ] || { echo "engine/nets/it014.jqn is not the measured net"; return 1; }
    out=$(printf 'setoption name EvalFile value %s\nbench\nquit\n' "$NET" | run "$BUILD/engine/jqe") || return 1
    echo "$out"
    echo "$out" | grep -qx 'Nodes searched: 45315'
}
results_check() {
    local lib
    lib=$(find "$BUILD/native" -name 'libjieqi_rules.so' -o -name 'libjieqi_rules.dylib' | head -n 1)
    local extra=()
    [ "$REPLAY" = 1 ] && extra=(--replay)
    JIEQI_NATIVE_LIBRARY="$lib" run python3 tools/check_results.py --check "${extra[@]}"
}
vectors() {  # the engine's test vectors for ports (engine/tests/vectors.py), regenerated in a small set
    run python3 engine/tests/vectors.py "$BUILD/engine/jqe" --out "$BUILD/vectors-quick" --quick
}

echo "repository $ROOT"
echo "build      $BUILD (jobs $JOBS, nice ${NICE:-off})"
echo "compiler   $(c++ --version 2>/dev/null | head -n 1); $(cmake --version | head -n 1); $(python3 --version)"
echo
step native-build        build_native
step native-ctest        test_native
step engine-build        build_engine
step "difftest-$DIFFTEST_GAMES" difftest
step perft-1-2-3         perft
step bench-45315         bench
step results             results_check
if [ "${VECTORS:-1}" = 1 ] && [ -f engine/tests/vectors.py ]; then step vectors-quick vectors; fi

echo
fail=0
for i in "${!names[@]}"; do
    printf '  %-4s %s\n' "${results[$i]}" "${names[$i]}"
    [ "${results[$i]}" = PASS ] || fail=1
done
grep -h '^games .* failures' "$LOG/difftest-$DIFFTEST_GAMES.log" 2>/dev/null | sed 's/^/  difftest: /'
grep -h -E '^[0-9]+ runs, ' "$LOG/results.log" 2>/dev/null | sed 's/^/  results:  /'
if [ "$fail" = 0 ]; then echo "all steps passed"; else echo "some steps FAILED"; fi
exit "$fail"
