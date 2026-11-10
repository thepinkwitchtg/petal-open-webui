#!/usr/bin/env bash
# 🌸 petal · slice A11 — offer the new words + knobs to your own files, once.
#
# petal-state/templates.json and trip-markers/settings.json were planted once and are never
# overwritten by OWUI. the new keys already work without this (the defaults fill in at read
# time), but you can't rewrite what you can't see. this helper shows what's missing and only
# writes if you say yes:
#   · every key you already have stays exactly as it is (same words, same place)
#   · only the missing keys are added, at the end (the orbit knobs inside "climax")
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

def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(f'💔 {path} does not parse (line {e.lineno}) — fix it by hand first, nothing was touched.')
        sys.exit(1)

plans = []
tpl_path = core.app_data_root() / 'petal-state' / 'templates.json'
mine = read(tpl_path)
if mine is None:
    print(f'🌱 no templates.json yet ({tpl_path}): OWUI plants the whole file on its first Petal request.')
elif isinstance(mine, dict):
    add = {k: v for k, v in TEMPLATES.items() if k not in mine}
    if add:
        plans.append((tpl_path, mine, {**mine, **add}, add))

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
        plans.append((set_path, knobs, grown, add))

if not plans:
    print('🌸 your files already hold every word and knob. nothing to do.')
    sys.exit(0)

show = lambda d: json.dumps(d, ensure_ascii=False, indent=2)
for path, _, _, add in plans:
    print(f'\n🌷 {path.parent.name}/{path.name} would grow:\n{show(add)}')
print('\n   every key you already have stays exactly as it is.')

try:
    with open('/dev/tty') as tty:
        print('\ngrow them? [y/N] ', end='', flush=True)
        answer = tty.readline().strip().lower()
except OSError:
    answer = ''
if answer not in ('y', 'yes', 'oui'):
    print('🌙 left untouched.')
    sys.exit(0)

for path, _, grown, _ in plans:
    backup = path.with_name(f'{path.name}.bak-{time.strftime("%Y%m%d-%H%M%S")}')
    shutil.copy2(path, backup)
    tmp = path.with_name(path.name + '.part')
    tmp.write_text(json.dumps(grown, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(tmp, os.stat(path).st_mode & 0o777)
    tmp.replace(path)
    print(f'🌸 {path.name} grew · backup kept at {backup.name}')
print('   read on the next request (no restart needed).')
PY
