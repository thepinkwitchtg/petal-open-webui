#!/usr/bin/env bash
# 🍄 petal · trip markers — offer the 1.2 mushrooms map to your live substances.json, once.
#
# your table was planted on first run and is never overwritten by OWUI. this helper
# shows your current mushrooms row beside the new one and only writes if you say yes.
#   · anything you hand-tuned in the old row (label, emoji, a key of your own) is kept
#   · the old `duration_h` range steps aside for the curve (the curve is read first anyway)
#   · a dated backup lands beside the file before anything is written
#   · every other substance (lsd, …) is left exactly as it is
#
#   chmod +x petal-markers-mushrooms.sh
#   ./petal-markers-mushrooms.sh
set -e
cd "$(dirname "$0")"
exec python3 - <<'PY'
import importlib.util, json, os, shutil, sys, time
from pathlib import Path

spec = importlib.util.spec_from_file_location('petal_markers_core', 'backend/open_webui/utils/petal_markers_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

# the row as first planted (contract 1, nov 4) — how we tell your tuning from the old default
PLANTED_V1 = {'label': 'mushies', 'emoji': '🍄', 'dose_unit': 'g', 'duration_h': [6, 8], 'peak_h': [0, 3]}
NEW = core.SUBSTANCES_DEFAULT['mushrooms']

g = core.Garden()
path = g.substances_path
if not path.exists():
    print(f'🌱 no table yet at {path}\n   open OWUI once: the first run plants the new mushrooms map by itself.')
    sys.exit(0)
try:
    table = json.loads(path.read_text(encoding='utf-8'))
except json.JSONDecodeError as e:
    print(f'💔 {path.name} does not parse (line {e.lineno}) — fix it by hand first, nothing was touched.')
    sys.exit(1)

old = table.get('mushrooms')
merged, kept, dropped = dict(NEW), [], []
for k, v in (old or {}).items():
    if k == 'duration_h' and v == PLANTED_V1['duration_h']:
        dropped.append(k)                       # the curve replaces the planted range
    elif k in PLANTED_V1 and v == PLANTED_V1[k]:
        continue                                # untouched default → the new map's value
    elif k not in NEW or NEW[k] != v:
        merged[k] = v                           # yours (tuned, or a key of your own) wins
        kept.append(k)

if merged == old:
    print('🍄 already merged — your mushrooms row is the 1.2 map (with your own touches). nothing to do.')
    sys.exit(0)

show = lambda d: json.dumps(d, ensure_ascii=False, indent=2)
print('🍄 your mushrooms row now:\n' + (show(old) if old else '   (none)'))
print('\n🌷 after the merge:\n' + show(merged))
if kept:
    print(f'\n   kept from your row (hand-tuned): {", ".join(kept)}')
if dropped:
    print(f'   steps aside for the curve: {", ".join(dropped)}')
print(f'\n   everything else in {path.name} stays as it is.')

try:
    with open('/dev/tty') as tty:
        print('\nmerge it? [y/N] ', end='', flush=True)
        answer = tty.readline().strip().lower()
except OSError:
    answer = ''
if answer not in ('y', 'yes', 'oui'):
    print('🌙 left untouched.')
    sys.exit(0)

backup = path.with_name(f'{path.name}.bak-{time.strftime("%Y%m%d-%H%M%S")}')
shutil.copy2(path, backup)
table['mushrooms'] = merged
tmp = path.with_name(path.name + '.part')
tmp.write_text(json.dumps(table, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
tmp.replace(path)
print(f'🍄 merged · backup kept at {backup.name}\n   the chip reads it on its next open (no restart needed).')
PY
