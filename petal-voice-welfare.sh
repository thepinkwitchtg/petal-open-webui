#!/usr/bin/env bash
# 🕊️🎀 petal voice welfare — the guard's tools. everything printed is numbers only, safe to paste.
#
#   ./petal-voice-welfare.sh calibrate           re-hear every flagged incident, size the thresholds
#   ./petal-voice-welfare.sh calibrate --cache   + the speaker button's speech cache as a pool of clean takes
#                                                (--since 2026-10-30 keeps only the omni era)
#   ./petal-voice-welfare.sh holdback            time what holding a take back costs before her first sound
#                                                (petal-voice awake in chat ✿ mode, and no chat speaking)
#
# chmod +x petal-voice-welfare.sh   (once)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PETAL_OWUI_PY:-$HOME/.venvs/openwebui/bin/python}"
[ -x "$PY" ] || PY=python3
TOOLS="$HERE/backend/open_webui/routers/audio/welfare_tools.py"

case "${1:-help}" in
  calibrate) shift; nice -n 10 "$PY" "$TOOLS" calibrate "$@" ;;
  holdback)  shift; "$PY" "$TOOLS" holdback "$@" ;;
  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
