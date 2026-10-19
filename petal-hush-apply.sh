#!/usr/bin/env bash
# 🌸 petal · hush — graft (or re-graft) the runtime whisper task onto routers/tasks.py.
# replaces any earlier hush graft in place; safe to run as often as you like.
# v2 · checks the graft still FITS upstream (every name it leans on still exists);
#      if not, any old block is taken out so OWUI still boots — a merge can't break her.
# v3 · the fit check reads the PATCH itself: every name it borrows from tasks.py
#      and every `from open_webui… import …` it makes — so a new patch never
#      needs this script edited.
# undo entirely: git checkout backend/open_webui/routers/tasks.py
set -e
cd "$(dirname "$0")"
exec python3 - <<'PY'
import ast, builtins, py_compile, re, sys
from pathlib import Path

ROOT = Path('backend/open_webui')
T = ROOT / 'routers/tasks.py'
block = Path('petal-patches/tasks_petal_hush.py').read_text(encoding='utf-8')
original = T.read_text(encoding='utf-8')

# ── strip any earlier graft → the upstream body ─────────────
src = original
if '# >>> petal · hush · begin >>>' in src:
    src = re.sub(r'\n*# >>> petal · hush · begin >>>.*?# <<< petal · hush · end <<<\n?', '', src, flags=re.S)
    how = 're-grafted'
elif '# 🌸 petal · hush' in src:  # the old unmarked v0.2 graft, appended last
    i = src.rindex('##################################', 0, src.index('# 🌸 petal · hush'))
    src = src[:i]
    how = 're-grafted (replaced the old unmarked block)'
else:
    how = 'grafted'
upstream = src.rstrip('\n') + '\n'

# ── does the graft still fit upstream? ──────────────────────
def top_names(path):
    """every name a module defines or imports at top level — read, never imported."""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split('.')[0] for a in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                names.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
    return names

missing = []
host = set()  # what the upstream body of tasks.py defines (the graft itself excluded)
tree = ast.parse(upstream)
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        host.add(node.name)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        host.update((a.asname or a.name).split('.')[0] for a in node.names)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
            host.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))

# what the patch itself borrows — read from the patch, never hand-listed
patch = ast.parse(block)
own = set()
for n in ast.walk(patch):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        own.add(n.name)
    elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
        own.add(n.id)
    elif isinstance(n, ast.arg):
        own.add(n.arg)
    elif isinstance(n, ast.ExceptHandler) and n.name:
        own.add(n.name)
    elif isinstance(n, (ast.Import, ast.ImportFrom)):
        own.update((a.asname or a.name).split('.')[0] for a in n.names)
used = {n.id for n in ast.walk(patch) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
module_globals = {'__file__', '__name__', '__doc__'}
for name in sorted(used - own - set(dir(builtins)) - module_globals):
    if name not in host:
        missing.append(f'tasks.py no longer has `{name}`')

# every `from open_webui.x.y import z` in the patch must still exist upstream
for n in ast.walk(patch):
    if isinstance(n, ast.ImportFrom) and (n.module or '').startswith('open_webui.'):
        parts = n.module.split('.')[1:]
        path = ROOT.joinpath(*parts).with_suffix('.py')
        if not path.exists():
            path = ROOT.joinpath(*parts, '__init__.py')
        if not path.exists():
            missing.append(f'{n.module} is gone')
            continue
        names = top_names(path)
        for a in n.names:
            if a.name not in names:
                missing.append(f'{n.module} no longer has `{a.name}`')

if missing:
    # an old graft that no longer fits would break boot — take it out, keep upstream pure
    removed = upstream != original
    T.write_text(upstream, encoding='utf-8')
    print('💔 hush graft no longer fits upstream' + (' — old block taken out so OWUI boots clean:' if removed else ' — tasks.py untouched:'))
    for m in missing:
        print('   ·', m)
    print('   hush whispers from the pool meanwhile · bring this list to a session and we re-fit the patch')
    sys.exit(1)

# ── graft, compile, roll back on any failure ────────────────
T.write_text(upstream + block, encoding='utf-8')
try:
    py_compile.compile(str(T), doraise=True)
except py_compile.PyCompileError as e:
    T.write_text(original, encoding='utf-8')
    print('💔 hush graft did not compile — tasks.py restored untouched:\n  ', e.msg.strip().splitlines()[-1])
    sys.exit(1)
print(f'🌷 hush {how} onto {T} — fits upstream, compiles · restart serve to wake it')
PY
