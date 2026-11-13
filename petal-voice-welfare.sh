#!/usr/bin/env bash
# 🕊️🎀 petal voice welfare — a looping, runaway or broken take never reaches your ears. everything printed is numbers only.
#
#   before the first waking
#     ./petal-voice-welfare.sh sweep --since 2026-10-30   judge the speaker cache: what today's rule would kill
#     ./petal-voice-welfare.sh sweep play all              hear them, one after another (⚡ violent ones: numbers only)
#     ./petal-voice-welfare.sh sweep verdict 1,3 ok        ok = truly bad · wrong = a legit line (a false kill)
#     ./petal-voice-welfare.sh sweep delete                sweep the confirmed-bad ones out of the cache
#     ./petal-voice-welfare.sh on [airtight|near-free]     wake the guard (the first waking starts the audit fortnight)
#
#   every day
#     ./petal-voice-welfare.sh status | stats              awake? hold? the ceiling? kills, rate, verdicts (stats is paste-safe)
#     ./petal-voice-welfare.sh list                        the kills kept for listening (audit fortnight)
#     ./petal-voice-welfare.sh play [n|all]                the killed take(s), then the fresh one that replaced it
#     ./petal-voice-welfare.sh verdict <n|1,3|2-5> ok|wrong
#     ./petal-voice-welfare.sh off | hold near-free | audit 7
#     ./petal-voice-welfare.sh rule [name value] | act [reason kill|watch|off]   tune from verdicts, never by guessing
#
#   her voice and the never-again set (since nov 13 2026)
#     ./petal-voice-welfare.sh baseline --since 2026-10-30   measure her voice (pace, floor, loudness, crossings): arms surge
#     ./petal-voice-welfare.sh never-again add last 5        keep a take that must always be caught (numbers only, never played)
#     ./petal-voice-welfare.sh never-again                   re-judge the whole set with today's rule (exit 1 if one gets through)
#
#   🎙️ voice pairs for the next voice tune (every kill keeps one, gold tier)
#     ./petal-voice-welfare.sh pairs                         how many · labels · voices · size vs the cap
#     ./petal-voice-welfare.sh pairs list | play [n|all]     numbers only · the killed take(s), then the resample (⚡ never auto-played)
#     ./petal-voice-welfare.sh pairs verdict 1,3 ok          ok = the kill was right · wrong = a false kill (flips it: kept as her legit voice)
#     ./petal-voice-welfare.sh pairs export [--labeled]      one folder per voice, never mixed · pairs cap <mb> to resize
#
#   diagnostics:  calibrate [--cache --since 2026-10-30] · holdback
#
# chmod +x petal-voice-welfare.sh   (once)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PETAL_OWUI_PY:-$HOME/.venvs/openwebui/bin/python}"
[ -x "$PY" ] || PY=python3
TOOLS="$HERE/backend/open_webui/routers/audio/welfare_tools.py"

case "${1:-help}" in
  calibrate|sweep|baseline|never-again) cmd="$1"; shift; nice -n 10 "$PY" "$TOOLS" "$cmd" "$@" ;;
  holdback|status|on|off|hold|audit|rule|act|list|play|verdict|stats|pairs) "$PY" "$TOOLS" "$@" ;;
  *) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
