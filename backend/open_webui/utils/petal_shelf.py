"""
petal_shelf 💗 — her shelf, read the way the fork's 💗 strings filter reads it (slice A30 · the vLLM door).

petal-emotions keeps her shelf (the strings she ♡'d, the blends she saved) and vLLM's notes at home (EMO-HOME,
§11.1): `Petal-App-Data/petal-emotions/home.json` names both, as the host sees them and as OWUI does
(`owui_view`). this module only reads (it never writes a byte), each file cached by its (mtime, size), and it
speaks the door's shape:

- a **ready blend** (its slug, or its name) → `{"blend": <slug>, "strength": s}` (her strength over the blend's own)
- a **♡'d string** (its id, or its name) → `{"strings": {<id>: s}, "strength": 1}`, kept inside its card's range
  (a card that only pulls one way, downward, takes her strength its own way)
- a waiting blend, a name the shelf doesn't hold, no shelf to read, or a vLLM that says it isn't stringing →
  no steer, and why. vLLM is never asked

where it looks: an explicit path → home.json (`$PETAL_APP_DATA`, then `/gardens/Documents/Petal-App-Data`, then
`~/Gardens/Documents/Petal-App-Data`; its `owui_view` when that home is here, else the host's own paths) →
`$PETAL_STRINGS_SHELF` / `$PETAL_STRINGS_NOTES` → the old place beside the code (only while home.json is absent).
the body is the one vLLM says it strings (`status.json`), else the shelf's current one (`index.json`).

the fork names no blend and no string: every name comes from her shelf, at runtime.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any

APP_DATA = ('/gardens/Documents/Petal-App-Data', '~/Gardens/Documents/Petal-App-Data')
OLD_PLACE = (  # petal-emotions beside the code, before EMO-HOME (read only while home.json is absent)
    '/gardens/Transformation Sequences - Automation/petal_core/petal-emotions',
    '~/Gardens/Transformation Sequences - Automation/petal_core/petal-emotions',
)
EMPTY = {'vectors': [], 'blends': []}

_cache: dict[str, tuple] = {}
_lock = threading.Lock()


def _read_json(path: Path) -> Any:
    """a JSON file, read again only when its (mtime, size) changed · caught mid-write: the last whole one."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    got = _cache.get(key)
    if got and got[0] == (st.st_mtime_ns, st.st_size):
        return got[1]
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return got[1] if got else None
    with _lock:
        _cache[key] = ((st.st_mtime_ns, st.st_size), obj)
    return obj


def _path(p: Any) -> Path | None:
    s = str(p or '').strip()
    return Path(s).expanduser() if s else None


def home(app_data: str = '') -> dict | None:
    """petal-emotions' home.json (v1), or None while it's absent."""
    cands = ([app_data] if (app_data or '').strip() else []) + [os.environ.get('PETAL_APP_DATA') or ''] + list(APP_DATA)
    for c in cands:
        root = _path(c)
        if root is None:
            continue
        doc = _read_json(root / 'petal-emotions' / 'home.json')
        if isinstance(doc, dict) and doc.get('v') == 1:
            return doc
    return None


def places(h: dict) -> dict:
    """home.json's paths as they are here: its owui_view when that home exists here, else the host's own."""
    view = h.get('owui_view') if isinstance(h.get('owui_view'), dict) else {}
    for src, name in ((view, 'owui_view'), (h, 'host')):
        root = _path(src.get('home'))
        if root is not None and root.is_dir():
            return {**{k: str(src.get(k) or '') for k in ('home', 'shelf', 'notes')}, 'view': name}
    src, name = (view, 'owui_view') if view.get('home') else (h, 'host')
    return {**{k: str(src.get(k) or '') for k in ('home', 'shelf', 'notes')}, 'view': name}


def _notes_beside(shelf: Path) -> Path:
    """vLLM's notes beside a shelf: home's private/vllm-strings, else the older data/vllm-strings."""
    for cand in (shelf.parent.parent / 'private' / 'vllm-strings', shelf.parent / 'vllm-strings'):
        if cand.is_dir():
            return cand
    return shelf.parent.parent / 'private' / 'vllm-strings'


def where(shelf: str = '', notes: str = '', app_data: str = '') -> dict:
    """{shelf, notes, from}: an explicit path → home.json → $PETAL_STRINGS_* → the old place (home.json absent)."""
    s = _path(shelf)
    if s is not None:
        n = _path(notes) or _notes_beside(s)
        return {'shelf': str(s), 'notes': str(n), 'from': 'explicit'}
    h = home(app_data)
    if h:
        pl = places(h)
        n = _path(notes) or _path(pl['notes'])
        return {'shelf': pl['shelf'], 'notes': str(n) if n else '', 'from': f"home.json · {pl['view']}"}
    es, en = _path(os.environ.get('PETAL_STRINGS_SHELF')), _path(os.environ.get('PETAL_STRINGS_NOTES'))
    if es is not None or en is not None:
        if es is None:  # notes alone: the shelf beside them, as vLLM's own default reads it
            es = en.parent.parent / 'data' / 'shelf'
        return {'shelf': str(es), 'notes': str(en or _notes_beside(es)), 'from': '$PETAL_STRINGS_*'}
    for old in OLD_PLACE:
        root = _path(old)
        if root is not None and (root / 'data' / 'shelf' / 'index.json').is_file():
            return {
                'shelf': str(root / 'data' / 'shelf'),
                'notes': str(root / 'private' / 'vllm-strings'),
                'from': 'the old place',
            }
    return {'shelf': '', 'notes': '', 'from': None}


def _plain(name: Any) -> str | None:
    """a body's folder name, nothing that walks out of the shelf."""
    s = str(name or '')
    if not s or len(s) > 200 or s.startswith('.') or '/' in s or '\\' in s:
        return None
    return s


def look(shelf: str = '', notes: str = '', app_data: str = '') -> dict:
    """the shelf vLLM serves: {body, manifest, status, why, shelf, notes, from} (why: nothing to steer by)."""
    w = where(shelf, notes, app_data)
    out = {**w, 'body': None, 'manifest': EMPTY, 'status': {}, 'why': None}
    if not w['shelf']:
        return {**out, 'why': "no shelf to read here (petal-emotions' home.json isn't where OWUI looks)"}
    root = Path(w['shelf'])
    status = _read_json(Path(w['notes']) / 'status.json') if w['notes'] else None
    status = status if isinstance(status, dict) else {}
    idx = _read_json(root / 'index.json')
    idx = idx if isinstance(idx, dict) else {}
    body = _plain(status.get('body')) if status.get('strung') else None
    body = body or _plain(idx.get('current'))
    man = _read_json(root / body / 'manifest.json') if body else None
    why = None
    if not idx:
        why = f'no shelf at {root}'
    elif not isinstance(man, dict):
        why = f'the shelf has nothing for {body or "her body"}'
    return {**out, 'body': body, 'manifest': man if isinstance(man, dict) else EMPTY, 'status': status, 'why': why}


def _range(entry: dict) -> tuple[float, float]:
    raw = entry.get('range')
    if raw is None and isinstance(entry.get('card'), dict):
        raw = entry['card'].get('range')
    try:
        lo, hi = (float(x) for x in list(raw)[:2])
    except (TypeError, ValueError):
        return -1.0, 1.0
    return (lo, hi) if lo <= hi else (hi, lo)


def _blends(man: dict) -> list:
    return [b for b in man.get('blends') or [] if isinstance(b, dict) and isinstance(b.get('slug'), str) and b['slug']]


def _strings(man: dict) -> list:
    return [v for v in man.get('vectors') or [] if isinstance(v, dict) and isinstance(v.get('id'), str) and v['id']]


def _is(entry: dict, key: str, name: str) -> bool:
    return entry[key] == name or str(entry.get('name') or '').strip().casefold() == name.casefold()


def door(name: str, strength: float, lk: dict | None = None) -> tuple[dict | None, dict | None, str | None]:
    """(steer, what, why): her pull's name read on the shelf, at her strength. steer is `petal_steer` as vLLM
    takes it; what is the pull as her record keeps it ({name, kind, id, strength[, asked]}); why, when no steer."""
    name = str(name or '').strip()
    if not name:
        return None, None, 'no pull named'
    lk = lk if lk is not None else look()
    if lk.get('why'):
        return None, None, lk['why']
    status = lk.get('status') or {}
    if status.get('strung') is False:
        return None, None, f"vLLM isn't stringing her ({status.get('why') or 'it gave no reason'})"
    man = lk.get('manifest') or EMPTY
    s = float(strength)
    for b in _blends(man):
        if b.get('ready') and _is(b, 'slug', name):
            s = round(s, 4)
            what = {'name': str(b.get('name') or b['slug']), 'kind': 'blend', 'id': b['slug'], 'strength': s}
            return {'blend': b['slug'], 'strength': s}, what, None
    for v in _strings(man):
        if _is(v, 'id', name):
            lo, hi = _range(v)
            want = -s if hi <= 0 < -lo else s  # a card that only pulls downward takes her strength its own way
            dial = round(max(lo, min(hi, want)), 4)
            label = str(v.get('name') or v['id'])
            if dial == 0:
                return None, None, f"{label}'s card keeps it at 0"
            what = {'name': label, 'kind': 'string', 'id': v['id'], 'strength': dial}
            if dial != round(want, 4):
                what['asked'] = round(want, 4)
            return {'strings': {v['id']: dial}, 'strength': 1}, what, None
    for b in _blends(man):
        if not b.get('ready') and _is(b, 'slug', name):
            waiting = b.get('waiting')
            return None, None, f"the blend “{b.get('name') or b['slug']}” is still waiting ({waiting if waiting else 'some'} strings)"
    return None, None, f"the shelf holds no ready blend or ♡'d string called “{name}”"


def pulls(lk: dict | None = None) -> dict:
    """what her shelf offers as a pull, for her settings: names come from the shelf, at runtime."""
    lk = lk if lk is not None else look()
    man = lk.get('manifest') or EMPTY
    out: list[dict] = []
    for b in _blends(man):
        ready = bool(b.get('ready'))
        out.append(
            {
                'name': str(b.get('name') or b['slug']),
                'kind': 'blend',
                'id': b['slug'],
                'ready': ready,
                **({} if ready else {'waiting': b.get('waiting')}),
            }
        )
    for v in _strings(man):
        out.append({'name': str(v.get('name') or v['id']), 'kind': 'string', 'id': v['id'], 'ready': True, 'range': list(_range(v))})
    status = lk.get('status') or {}
    return {
        'ok': not lk.get('why'),
        'why': lk.get('why'),
        'from': lk.get('from'),
        'body': lk.get('body'),
        'strung': status.get('strung') if isinstance(status.get('strung'), bool) else None,
        'pulls': out,
    }
