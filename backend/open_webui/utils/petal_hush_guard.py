"""🌸 petal hush · the startup check (A49).

her rig once served a page that asked hush for her line as she writes it while routers/tasks.py held an older hush
block (a graft laid a pre-A47 block back over the file after A47 landed): every whisper came whole, and nothing said
why. at boot this reads both sides and names any mismatch in the log, loud:
  · the block: the newest `# v0.NN ·` line between the hush markers in routers/tasks.py (no markers: no block)
  · the page: the line the page's hush.js carries, `needs the server's hush block ≥ 0.NN` (the copy the page is
    served: STATIC_DIR, filled from the build at boot; else the build's; else the tree's own static/)
  · the graft: the block petal-hush-apply.sh pastes (petal-patches/tasks_petal_hush.py): an older block of exactly
    its version is named as that graft laid back over the file
it never stops the boot and never edits anything: it only tells. numbers and file names only.
"""

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

BEGIN = '# >>> petal · hush · begin >>>'
END = '# <<< petal · hush · end <<<'
VERSION = re.compile(r'^#\s*v(\d+)\.(\d+)\s*·', re.M)
NEEDS = re.compile(r"needs the server's hush block\s*≥\s*(\d+)\.(\d+)")
SELF = re.compile(r'petal · hush\s*·\s*v(\d+)\.(\d+)')
FIX = 'git checkout backend/open_webui/routers/tasks.py, then restart openwebui'


def block_version(src: str) -> tuple[int, int] | None:
    """the hush block's version in routers/tasks.py: its newest changelog line · None: no block at all"""
    i = src.find(BEGIN)
    j = src.find(END, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        return None
    found = [(int(a), int(b)) for a, b in VERSION.findall(src[i:j])]
    return max(found) if found else (0, 0)


def page_needs(js: str) -> tuple[int, int] | None:
    """the block the page's hush.js needs (its own `needs … ≥ 0.NN` line) · None: it doesn't say"""
    m = NEEDS.search(js)
    return (int(m[1]), int(m[2])) if m else None


def page_version(js: str) -> str | None:
    m = SELF.search(js)
    return f'v{m[1]}.{m[2]}' if m else None


def _v(t: tuple[int, int] | None) -> str:
    return f'v{t[0]}.{t[1]}' if t else 'none'


def check(tasks_py: Path, hush_js: list[Path], patch: Path | None = None) -> dict:
    """read both sides and tell · returns what it found: {ok, block, needs, page, page_file, graft, why}"""
    out: dict = {'ok': True, 'block': None, 'needs': None, 'page': None, 'page_file': None, 'graft': None, 'why': ''}
    try:
        block = block_version(Path(tasks_py).read_text(encoding='utf-8'))
    except OSError as e:
        out.update(ok=False, why=f'routers/tasks.py unreadable ({type(e).__name__})')
        log.warning('🌸⚠️ petal hush: %s', out['why'])
        return out
    out['block'] = _v(block)
    page = next((p for p in hush_js if p and Path(p).is_file()), None)
    js = ''
    if page is not None:
        try:
            js = Path(page).read_text(encoding='utf-8')
        except OSError:
            js = ''
        out['page_file'] = str(page)
    needs = page_needs(js) if js else None
    out['needs'] = _v(needs) if needs else None
    out['page'] = page_version(js) if js else None
    if block is None:
        out.update(ok=False, why='no hush block in routers/tasks.py: hush whispers from its pool only')
        log.warning('🌸⚠️ petal hush: %s', out['why'])
    elif needs and block < needs:
        graft = None
        try:
            graft = block_version(Path(patch).read_text(encoding='utf-8')) if patch else None
        except OSError:
            graft = None
        out['graft'] = _v(graft) if graft else None
        page = out['page'] or '?'
        if graft and graft == block:
            why = (
                f'routers/tasks.py holds hush block {_v(block)}, the block petal-hush-apply.sh pastes '
                f"(petal-patches/tasks_petal_hush.py): it was laid back over the file after the build, and the page's "
                f'hush.js ({page}) needs ≥ {_v(needs)}'
            )
        else:
            why = f"routers/tasks.py holds hush block {_v(block)}, older than the page's hush.js ({page}) needs (≥ {_v(needs)})"
        out.update(ok=False, why=f'{why}. every whisper comes whole until it is restored: {FIX}')
        log.warning('🌸⚠️ petal hush: %s', out['why'])
    elif not js:
        out['why'] = "the page's hush.js was not found (the build has no skin?): nothing to compare"
        log.info('🌸 petal hush: block %s · %s', out['block'], out['why'])
    elif not needs:
        out['why'] = "the page's hush.js doesn't say which block it needs (older than A49)"
        log.info('🌸 petal hush: block %s · %s', out['block'], out['why'])
    else:
        log.info("🌸 petal hush: block %s · the page's hush.js %s needs ≥ %s · ok", out['block'], out['page'], out['needs'])
    return out


def check_at_boot() -> dict | None:
    """the check as openwebui boots (main.py): the files this backend really serves · never raises"""
    try:
        here = Path(__file__).resolve().parent.parent  # backend/open_webui
        from open_webui.env import FRONTEND_BUILD_DIR, STATIC_DIR

        candidates = [
            Path(STATIC_DIR) / 'petal' / 'hush.js',
            Path(FRONTEND_BUILD_DIR) / 'static' / 'petal' / 'hush.js',
            here.parent.parent / 'static' / 'static' / 'petal' / 'hush.js',
        ]
        return check(here / 'routers' / 'tasks.py', candidates, here.parent.parent / 'petal-patches' / 'tasks_petal_hush.py')
    except Exception as e:  # never the reason a boot fails
        log.warning('🌸⚠️ petal hush: the startup check could not run (%s)', type(e).__name__)
        return None
