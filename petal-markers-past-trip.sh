#!/usr/bin/env bash
# 🌙 petal · trip markers — lock in a trip that already happened (a backfill).
#
# asks for the substance, dose (+ strain when the row has strains), when you took it and,
# if you know it, when it ended. previews the whole timeline (end, tier, integration window)
# and writes only on your yes:
#   · a status.start   (via "hand", with your real ingestion time)
#   · a status.end     (manual, only if you gave an end time)
# then the ledger notices both parts are over and harvests them into one trip folder.
# nothing is ever overwritten: a mistake is undone with a void, kept in the log.
#
#   lives at the root of your petal-open-webui fork (beside petal-markers-mushrooms.sh)
#   chmod +x petal-markers-past-trip.sh
#   ./petal-markers-past-trip.sh
set -e
cd "$(dirname "$(readlink -f "$0")")"
exec python3 - <<'PY'
import importlib.util, sys, time
from datetime import datetime
spec = importlib.util.spec_from_file_location('petal_markers_core', 'backend/open_webui/utils/petal_markers_core.py')
core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)

try:
    tty = open('/dev/tty')
except OSError:
    sys.exit('🥀 needs a terminal to ask you')

def ask(q, default=None):
    print(f"{q}{f' [{default}]' if default else ''}: ", end='', flush=True)
    a = tty.readline().strip()
    return a or (default or '')

def when(s):
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %Hh%M', '%Y-%m-%d'):
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            pass
    sys.exit(f'🥀 "{s}" — write it like 2026-10-31 18:28')

def clock(t):
    return time.strftime('%a %d %b %H:%M', time.localtime(t)) if t else '—'

g = core.Garden(); g.ensure()
table = g.table()
keys = [k for k, v in table.items() if isinstance(v, dict)]
print('🌙 a trip that already happened\n')
print('   substances: ' + ' · '.join(f"{table[k].get('emoji', '✧')} {k}" for k in keys))
sub = ask('substance (its key)')
if sub not in table:
    sys.exit(f'🥀 "{sub}" is not in substances.json · nothing written')
row = table[sub]
dose = ask(f"dose{(' in ' + row['dose_unit']) if row.get('dose_unit') else ''}")
strain = None
if isinstance(row.get('strains'), dict) and row['strains']:
    strain = ask('strain (' + ' · '.join(row['strains']) + ')', row.get('strain_default')) or None
taken = when(ask('taken at (YYYY-MM-DD HH:MM)'))
ended_s = ask('ended at (YYYY-MM-DD HH:MM · empty = let the table decide)')
ended = when(ended_s) if ended_s else None
note = ask('a note (optional)') or None
now = int(time.time())
if taken > now or (ended and ended > now):
    sys.exit('🥀 that time is in the future · nothing written')
if ended and ended <= taken:
    sys.exit('🥀 the end comes before the ingestion · nothing written')

# preview on a scratch copy of the view: nothing touches the garden until you say yes
p = core.profile(sub, dose, table, g.settings(), strain)
if p['duration_h'] is None and not ended:
    sys.exit(f"🥀 {p['why_no_end']} · give a dose or an end time · nothing written")
exp_end = int(taken + p['duration_h'] * 3600) if p['duration_h'] is not None else None
end = ended or exp_end                       # her own clock wins, longer or shorter than the table
basis = max(end, exp_end) if exp_end else end  # a later end stretches the expected end (amend)
integ_open = min(int(taken + p['integration_from'] * (basis - taken)), end)
integ_close = end + int(float(g.settings().get('integration_tail_h', 72)) * 3600)
print(f"\n{p['emoji']} {p['label']} {dose or ''}{(' · ' + strain) if strain else ''}"
      + (f" · {p['tier']['label']}" if p.get('tier') else ''))
print(f"   taken        {clock(taken)}")
print(f"   ends         {clock(end)}  ({'your end time' if ended else 'from the table'})")
print(f"   integration  {clock(integ_open)} → {clock(integ_close)}")
print(f"   harvests     trip {'(due once written)' if end <= now else '(when it ends)'} · "
      f"integration {'(due once written)' if integ_close <= now else '(when it closes)'}")
if ask('\nwrite it? [y/N]').lower() not in ('y', 'yes', 'oui'):
    print('🌙 nothing written'); sys.exit(0)

body = {'kind': 'status.start', 'via': 'hand', 'substance': sub, 'dose': dose or None,
        'taken_at': taken, 'note': note}
if strain:
    body['strain'] = strain
sid = core.write(g, body, now=now)['id']
if ended and (exp_end is None or ended > exp_end):
    # later than the table says (or the table can't say): the expected end becomes hers
    core.write(g, {'kind': 'amend', 'via': 'hand', 'ref': sid, 'fields': {'ends_at': ended},
                   'reason': 'backfill: her real end'}, now=now)
elif ended and ended < exp_end:
    core.write(g, {'kind': 'status.end', 'via': 'hand', 'ref': sid, 'at': ended}, now=now)
view, _ = core.settle(g, int(time.time()))
due = [d['part'] for d in core.harvests_due(view, int(time.time())) if d['ref'] == sid]
print(f"🌸 locked in · {', '.join(due) if due else 'no part'} due for the ledger"
      f" · a mistake? void it with ./petal-markers-void-tests.sh 2000")
PY
