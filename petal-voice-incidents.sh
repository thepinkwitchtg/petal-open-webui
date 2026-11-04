#!/usr/bin/env bash
# 🚩🎀 petal voice incidents — re-listen to every flagged reply and print the stats-only report
#
#   ./petal-voice-incidents.sh              report (also saved as incidents/report-<date>.md)
#   ./petal-voice-incidents.sh open         open the incidents folder
#   ./petal-voice-incidents.sh last         the newest incident's analysis (numbers only)
#
# the incidents folder holds her words (trace.json) — keep it on the rig. the report is what you share.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PETAL_OWUI_PY:-$HOME/.venvs/openwebui/bin/python}"
[ -x "$PY" ] || PY=python3
VT="$HERE/backend/open_webui/routers/audio/voice_trace.py"
INC="${PETAL_APP_DATA:-$HOME/Gardens/Documents/Petal-App-Data}/petal-voice/incidents"

case "${1:-report}" in
  report) nice -n 10 "$PY" "$VT" report ;;
  open)   mkdir -p "$INC" && xdg-open "$INC" >/dev/null 2>&1 & ;;
  last)   nice -n 10 "$PY" "$VT" last ;;
  *) echo "usage: $0 [report|open|last]"; exit 1 ;;
esac
