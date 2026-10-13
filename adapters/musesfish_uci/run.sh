#!/bin/sh
# Launches the musesfish UCI shim (shim.py); used by match.py KNOWN["musesfish"].
# JIEQI_PYTHON names the Python 3.11+ interpreter (default: python3 on PATH).
HERE=$(cd "$(dirname "$0")" && pwd)
exec "${JIEQI_PYTHON:-python3}" "$HERE/shim.py"
