#!/usr/bin/env bash
# 🌸📏 petal long chats — what opening her longest chats costs, numbers only (slice A24 · the login line A25)
#
#   ./petal-long-chats.sh            the 12 largest chats, opened the way her desktop opens them
#   ./petal-long-chats.sh 20         the 20 largest
#   ./petal-long-chats.sh 8 --phone  as her phone would (360×780 @3x, CPU ×4)
#
# a reader only: every API call that isn't a GET is refused in the probe's browser and its socket never sends a
# "read" mark (no "viewed" stamps, her unread dots untouched, no device readings, no whispers). never a title or
# a word: chats are picked by size and named by a hash of their id.
# OWUI must be running (OWUI_URL, default http://127.0.0.1:3000). OWUI opens chats in a browser only for a human
# session, so an sk- key (PETAL_OWUI_KEY · OWUI_TOKEN · Petal-App-Data/_secrets/owui.key) gets one line and her
# login is asked once (kept in memory only, never stored); a session token found there is used as is.
# the report is printed and kept in Petal-App-Data/petal-probes/.
# the first run brings its own headless browser: a small venv at ~/.venvs/petal-probe (playwright + chromium).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${PETAL_PROBE_VENV:-$HOME/.venvs/petal-probe}"

if ! "$VENV/bin/python" -c 'import playwright' >/dev/null 2>&1; then
  echo "🌸 first run: the probe's own little venv at $VENV (playwright)"
  if command -v uv >/dev/null 2>&1; then
    uv venv -q -p 3.12 "$VENV" && uv pip install -q --python "$VENV/bin/python" playwright
  else
    python3 -m venv "$VENV" && "$VENV/bin/pip" install -q playwright
  fi
fi
# its chromium, once (~/.cache/ms-playwright); a no-op when it's already there
"$VENV/bin/python" -m playwright install chromium >/dev/null || {
  echo "💔 chromium didn't install. if it says libraries are missing: sudo $VENV/bin/python -m playwright install-deps chromium"
  exit 1
}
# not niced on purpose: it measures timings, and it stays light (one page at a time)
exec "$VENV/bin/python" "$HERE/petal-long-chats.py" "$@"
