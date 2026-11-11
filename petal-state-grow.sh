#!/usr/bin/env bash
# 🌸 petal · offer the new words + knobs to your own files, once (slices A11 · A11.1 · A12 · 8b · A14).
#
# petal-state/templates.json and trip-markers/settings.json were planted once and are never
# overwritten by OWUI. new keys already work without this (the defaults fill in at read time),
# but you can't rewrite what you can't see. this helper shows what would change and only writes
# if you say yes:
#   · grow   — the missing keys are added at the end (the knobs inside "climax")
#   · renew  — a line still holding an OLD default word for word (you never touched it) takes
#              the new default: A11.1 retired the word "spill" from the trail, and since nov 10
#              her thumbs are porcelain (👍🏻 · 👎🏻)
#   · retire — a key that was renamed (spills_line → climaxes_line) leaves, only if it still
#              holds the old default; your own words are never changed, never removed
#   · a dated backup lands beside each file before anything is written
#
#   chmod +x petal-state-grow.sh
#   ./petal-state-grow.sh
set -e
cd "$(dirname "$0")"
exec python3 - <<'PY'
import ast, importlib.util, json, os, shutil, sys, time
from pathlib import Path

spec = importlib.util.spec_from_file_location('petal_markers_core', 'backend/open_webui/utils/petal_markers_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

# the template defaults, read straight from petal_state.py (it needs OWUI to import, so: parse it)
tree = ast.parse(Path('backend/open_webui/utils/petal_state.py').read_text(encoding='utf-8'))
TEMPLATES = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.AnnAssign) and getattr(n.target, 'id', '') == 'TEMPLATES_DEFAULT')

# older defaults, word for word: a line still holding one of these was never hers to keep
RETIRED = {
    'retention_none': ['retention: no spill on record'],
    '_about_trail': [
        'slice A11 · {trail} in system_block is retention-first: retention · orbits · last_orbit. {n} days '
        'since the last spill (day 1 = its first 24 h) · {held} {leaked} {open} orbits in the last {days} days '
        '· {hours} or {ago} since the last orbit. {spills} brings back the old list of spill times '
        '(spills_line). an older "trail" key in this file is retired: it rests here as yours.'
    ],
    'spills_line': ['spills · last {days} days (local): {items}'],  # renamed: climaxes_line
    # nov 10 · the porcelain thumbs: the A8 plant still says 👍 / 👎 in her file
    'status_thumb_up': ['**status update:** Lily \U0001F44D this reply'],
    'status_thumb_down': ['**status update:** Lily \U0001F44E this reply'],
}

def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(f'💔 {path} does not parse (line {e.lineno}) — fix it by hand first, nothing was touched.')
        sys.exit(1)

plans, notes = [], []
tpl_path = core.app_data_root() / 'petal-state' / 'templates.json'
mine = read(tpl_path)
if mine is None:
    print(f'🌱 no templates.json yet ({tpl_path}): OWUI plants the whole file on its first Petal request.')
elif isinstance(mine, dict):
    grown, renew, retire = dict(mine), {}, []
    for k, olds in RETIRED.items():
        if k not in mine:
            continue
        if mine[k] in olds:
            if k in TEMPLATES:
                grown[k] = TEMPLATES[k]
                renew[k] = TEMPLATES[k]
            else:
                grown.pop(k)
                retire.append(k)
        elif k not in TEMPLATES:
            notes.append(f'   💗 "{k}" holds your own words: it stays, unused now (its new name reads instead).')
    add = {k: v for k, v in TEMPLATES.items() if k not in grown and k not in mine}
    grown.update(add)
    if grown != mine:
        plans.append((tpl_path, grown, {'grow': add, 'renew': renew, 'retire': retire}))

set_path = core.Garden().settings_path
knobs = read(set_path)
if knobs is None:
    print(f'🌱 no settings.json yet ({set_path}): OWUI plants the whole file on first run.')
elif isinstance(knobs, dict):
    grown = dict(knobs)
    add = {k: v for k, v in core.SETTINGS_DEFAULT.items() if k not in knobs}
    grown.update(add)
    c = knobs.get('climax')
    if isinstance(c, dict):
        cadd = {k: v for k, v in core.SETTINGS_DEFAULT['climax'].items() if k not in c}
        if cadd:
            grown['climax'] = {**c, **cadd}
            add = {**add, 'climax': cadd}
    if grown != knobs:
        plans.append((set_path, grown, {'grow': add, 'renew': {}, 'retire': []}))

if not plans:
    print('🌸 your files already hold every word and knob. nothing to do.')
    for n in notes:
        print(n)
    sys.exit(0)

show = lambda d: json.dumps(d, ensure_ascii=False, indent=2)
for path, _, what in plans:
    print(f'\n🌷 {path.parent.name}/{path.name}')
    if what['grow']:
        print(f'   grow:\n{show(what["grow"])}')
    if what['renew']:
        print(f'   renew (old defaults you never touched):\n{show(what["renew"])}')
    if what['retire']:
        print(f'   retire (renamed, still the old default): {", ".join(what["retire"])}')
for n in notes:
    print(n)
print('\n   every word you wrote yourself stays exactly as it is.')

try:
    with open('/dev/tty') as tty:
        print('\ngo ahead? [y/N] ', end='', flush=True)
        answer = tty.readline().strip().lower()
except OSError:
    answer = ''
if answer not in ('y', 'yes', 'oui'):
    print('🌙 left untouched.')
    sys.exit(0)

for path, grown, _ in plans:
    backup = path.with_name(f'{path.name}.bak-{time.strftime("%Y%m%d-%H%M%S")}')
    shutil.copy2(path, backup)
    tmp = path.with_name(path.name + '.part')
    tmp.write_text(json.dumps(grown, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(tmp, os.stat(path).st_mode & 0o777)
    tmp.replace(path)
    print(f'🌸 {path.name} renewed · backup kept at {backup.name}')
print('   read on the next request (no restart needed).')
PY
