#!/usr/bin/env bash
# 🌙 petal · trip markers — void the statuses you set while testing, before the ledger
# starts harvesting trips (a voided status is never harvested).
#
# lists every live status from the last N hours (default 24) with its emoji, dose, ingestion
# time and phase, and asks about each one. only a "y" writes a `void` line (kept in the log,
# never deleted). nothing else is touched.
#
#   lives at the root of your petal-open-webui fork (beside petal-markers-mushrooms.sh)
#   chmod +x petal-markers-void-tests.sh
#   ./petal-markers-void-tests.sh          (or: ./petal-markers-void-tests.sh 48)
set -e
cd "$(dirname "$(readlink -f "$0")")"
exec python3 - "${1:-24}" <<'PY'
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location('petal_markers_core', 'backend/open_webui/utils/petal_markers_core.py')
core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)

hours = float(sys.argv[1])
g = core.Garden()
if not g.log.exists():
    print('🌱 no markers yet · nothing to void'); sys.exit(0)
now = int(time.time())
view, _ = core.settle(g, now)
recent = [tl for tl in view.timelines() if tl['taken_at'] >= now - hours * 3600 or (tl['end'] or now) >= now - hours * 3600]
if not recent:
    print(f'🌙 no statuses in the last {hours:g} h · nothing to void'); sys.exit(0)

try:
    tty = open('/dev/tty')
except OSError:
    sys.exit('🥀 needs a terminal to ask you')

voided = 0
for tl in recent:
    when = time.strftime('%a %d %b %H:%M', time.localtime(tl['taken_at']))
    dose = f" {tl['dose']}{tl.get('dose_unit') or ''}" if tl.get('dose') else ''
    tier = f" · {tl['tier']['label']}" if tl.get('tier') else ''
    harvested = [p for p, h in (tl.get('harvested') or {}).items() if h]
    print(f"\n{tl['emoji']} {tl['label']}{dose}{tier}\n   taken {when} · now: {core.phase_at(tl, now)}"
          + (f" · already harvested: {', '.join(harvested)}" if harvested else ''))
    print('   void it (a test)? [y/N] ', end='', flush=True)
    if tty.readline().strip().lower() in ('y', 'yes', 'oui'):
        core.write(g, {'kind': 'void', 'via': 'hand', 'ref': tl['id'], 'reason': 'sprint test'}, now=int(time.time()))
        voided += 1
        print('   🕊 voided')
    else:
        print('   🌸 kept')
print(f"\n🌙 {voided} voided · {len(recent) - voided} kept · the ledger will never harvest a voided status")
PY
