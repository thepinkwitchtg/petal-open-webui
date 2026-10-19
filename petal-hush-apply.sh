#!/usr/bin/env bash
# 🌸 petal · hush — graft (or re-graft) the runtime whisper task onto routers/tasks.py.
# replaces any earlier hush graft in place; safe to run as often as you like.
# undo entirely: git checkout backend/open_webui/routers/tasks.py
set -e
cd "$(dirname "$0")"
exec python3 - <<'PY'
import py_compile, re
from pathlib import Path
T = Path('backend/open_webui/routers/tasks.py')
src = T.read_text(encoding='utf-8')
block = Path('petal-patches/tasks_petal_hush.py').read_text(encoding='utf-8')

if '# >>> petal · hush · begin >>>' in src:          # v0.3+ graft: swap between markers
    src = re.sub(r'\n*# >>> petal · hush · begin >>>.*?# <<< petal · hush · end <<<\n?', '', src, flags=re.S)
    how = 're-grafted (replaced the earlier v0.3 block)'
elif '# 🌸 petal · hush' in src:                        # v0.2 graft: it was appended last, cut from its banner
    i = src.index('# 🌸 petal · hush')
    i = src.rindex('##################################', 0, i)
    src = src[:i]
    how = 're-grafted (replaced the v0.2 block)'
else:
    how = 'grafted'

T.write_text(src.rstrip('\n') + '\n' + block, encoding='utf-8')
py_compile.compile(str(T), doraise=True)
print(f'🌷 {how} onto {T} — restart the server (python only, no frontend build needed)')
PY
