#!/bin/sh
# Launches the universe-st/Jieqi adapter (adapter.mts) with Node.js, which strips the TypeScript types itself.
# Speaks the UCI-like protocol of engine/tools/match.py on stdin/stdout. No network, no installs: the universe
# checkout is imported read-only.
#   UNIVERSE_NODE       the node executable (default: node on PATH). A Windows node.exe called from WSL is
#                       given Windows paths, and Linux paths of LogFile are mapped through the WSL share.
#   UNIVERSE_JIEQI_DIR  the universe-st/Jieqi checkout (default: $JIEQI_OPPONENTS/universe-jieqi, with
#                       JIEQI_OPPONENTS defaulting to ~/jieqi-opponents)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
NODE=${UNIVERSE_NODE:-node}
UNIVERSE=${UNIVERSE_JIEQI_DIR:-${JIEQI_OPPONENTS:-$HOME/jieqi-opponents}/universe-jieqi}
case "$NODE" in
  *.exe)
    exec "$NODE" --no-warnings --experimental-strip-types \
      "$(wslpath -w "$HERE/adapter.mts")" \
      --universe "$(wslpath -w "$UNIVERSE")" \
      --wsl-root "$(wslpath -w /)" ;;
  *)
    exec "$NODE" --no-warnings --experimental-strip-types "$HERE/adapter.mts" --universe "$UNIVERSE" ;;
esac
