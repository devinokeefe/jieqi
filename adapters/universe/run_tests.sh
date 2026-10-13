#!/bin/sh
# Unit checks for the observer reconstruction (test_observer.mts). Node.js and the universe checkout are
# found as in run.sh (UNIVERSE_NODE, UNIVERSE_JIEQI_DIR, JIEQI_OPPONENTS).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
NODE=${UNIVERSE_NODE:-node}
UNIVERSE=${UNIVERSE_JIEQI_DIR:-${JIEQI_OPPONENTS:-$HOME/jieqi-opponents}/universe-jieqi}
case "$NODE" in
  *.exe)
    exec "$NODE" --no-warnings --experimental-strip-types \
      "$(wslpath -w "$HERE/test_observer.mts")" --universe "$(wslpath -w "$UNIVERSE")" ;;
  *)
    exec "$NODE" --no-warnings --experimental-strip-types "$HERE/test_observer.mts" --universe "$UNIVERSE" ;;
esac
