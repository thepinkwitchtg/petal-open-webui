#!/usr/bin/env bash
# 🌸📻 petal-stream-taste — hear the petal stream without OWUI or the phone
#
# usage:  ./petal-stream-taste.sh                    her default tasting lines
#         ./petal-stream-taste.sh "your words. more words…"
#
# needs the omni voice awake on :8100 (petal-voice in chat mode in the launcher).
# writes an mp3 to ~/Gardens/Documents/Petal-App-Data/petal-voice/stream-tastes/ and opens it.
# cadence knobs: ~/Gardens/Documents/Petal-App-Data/petal-voice/stream-cadence.json
set -euo pipefail
cd "$(dirname "$0")"
PY="${PETAL_OWUI_PY:-$HOME/.venvs/openwebui/bin/python}"
if ! "$PY" -c "import lameenc" 2>/dev/null; then
  echo "» lameenc missing in the OWUI venv, planting it…"
  "$PY" -m pip install lameenc || uv pip install --python "$PY" lameenc
fi
out=$("$PY" backend/open_webui/routers/audio/petal_stream.py "$@" | tee /dev/stderr | sed -n 's/^📻 //p')
[ -n "$out" ] && command -v xdg-open >/dev/null && xdg-open "$out" >/dev/null 2>&1 &
