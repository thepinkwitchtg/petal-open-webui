#!/usr/bin/env bash
# 🚩🎀 petal voice incidents — the black box lives at the voice now (V1): this points there
#
#   ./petal-voice-incidents.sh              report (also saved as incidents/report-<date>.md)
#   ./petal-voice-incidents.sh open         open the incidents folder
#   ./petal-voice-incidents.sh last         the newest incident's analysis (numbers only)
#   ./petal-voice-incidents.sh recent       what the voice's black box holds right now (numbers only)
#
# petal-voice's own helper ($PETAL_VOICE_DIR/petal-voice-incidents.sh) does the work; its report hears
# with welfare's ear, beside this file. the incidents folder holds her words (trace.json): keep it on the rig.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOICE_DIR="${PETAL_VOICE_DIR:-$HOME/Gardens/Transformation Sequences - Automation/petal_core/petal-voice}"
if [ -x "$VOICE_DIR/petal-voice-incidents.sh" ]; then
  PETAL_OWUI_DIR="${PETAL_OWUI_DIR:-$HERE}" exec "$VOICE_DIR/petal-voice-incidents.sh" "$@"
fi
echo "✗ petal-voice isn't at $VOICE_DIR (set PETAL_VOICE_DIR) — the black box and its report live there now"
exit 1
