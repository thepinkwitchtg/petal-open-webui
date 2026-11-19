"""
petal_arms 🍒 — the strength search (slice A30b): arms stop drawing from a fixed set and discover the strength.

every arm asks one question: at this strength, does the pulled reply win over the unsteered one? her 💗 for the
pulled side says "this much helps" (the edge sits higher), her 💗 for the unsteered side says "too much" (the
edge sits lower). the search keeps a belief over where that edge is, on [0, cap] (cap: 0.5, or less where the
pull's card ends), and tries each arm at the belief's centre: stochastic bisection (probabilistic bisection, as
Horstein and Waeber · Frazier · Henderson do it, with a psychometric likelihood as QUEST uses: near the edge her
answers are close to a coin flip, far from it they are clear, and a few are simply random: seeds differ).

- **searching** while the belief is wide (its 90% interval wider than 0.25), **narrowing** as it closes,
  **stable** once it has held within ±0.03 over her last 3 arms and her answers fit it. stable arms probe gently,
  0.01–0.02 either side of the centre
- **re-open**: when her answers lean one way the belief doesn't expect (a two-sided CUSUM on her answers'
  surprise), the belief widens again (its shape kept, a floor laid under it) and the search goes on from there:
  it follows who she is now
- one search per pull (its shelf id), global rather than per moment: the tuning fork (W) can replace the draw
  later through the same seam, `petal_pick.draw_arm`
- an arm's strength is chosen at the send (`tried`) and learned from when her 💗 lands (`learn`, called by the
  thumbs door with the reply the server recorded): an arm she never picks teaches nothing, a verdict sent twice
  teaches once
- state: `$PETAL_APP_DATA/petal-open-webui/arms-search.json`; every step a line in `arms-search.jsonl`, numbers
  only (the pull is a number there, never its name) · dir 700, files 600 · never in the repo
"""

import hashlib
import json
import logging
import math
import os
import random
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

GRID = 0.001  # strengths are free decimals: the belief lives on a 0.001 grid
CAP = 0.5  # never above, whatever the card allows
TAU = 0.03  # how soft her edge is: within ~0.03 of it her answers are close to a coin flip
LAPSE = 0.06  # how often an answer is simply random (a reply can win on its own merits)
SPAN = 0.25  # wider than this, the search is still searching
STABLE_WIDTH = 0.06  # ±0.03
STABLE_HOLD = 3  # arms the width must hold for
SHIFT = (0.01, 0.02)  # stable: how far either side of the centre an arm probes
CUSUM_K, CUSUM_H = 0.25, 2.0  # re-open when her answers lean one way this much (both directions)
WIDEN, FLOOR = 0.15, 0.2  # a re-open: the belief tempered (its shape kept), and a floor under it
MIN_TRY = 0.005  # a pull of 0 pulls nothing
PENDING_DAYS, PENDING_MAX = 14, 200  # arms waiting for her pick
_lock = threading.Lock()


def home() -> Path:
    root = Path(os.environ.get('PETAL_APP_DATA') or '~/Gardens/Documents/Petal-App-Data').expanduser()
    return root / 'petal-open-webui'


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _load() -> dict:
    try:
        doc = json.loads((home() / 'arms-search.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        doc = None
    if not isinstance(doc, dict) or doc.get('v') != 1:
        doc = {'v': 1, 'searches': {}, 'pending': {}}
    doc.setdefault('searches', {})
    doc.setdefault('pending', {})
    return doc


def _save(doc: dict) -> None:
    d = home()
    _private_dir(d)
    path, tmp = d / 'arms-search.json', d / 'arms-search.json.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(doc, f, separators=(',', ':'))
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _log(line: dict) -> None:
    d = home()
    _private_dir(d)
    fd = os.open(d / 'arms-search.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a', encoding='utf-8') as f:
        f.write(json.dumps(line, separators=(',', ':')) + '\n')


def pull_number(key: str) -> int:
    """the pull, as a number (the log never names it)"""
    return int(hashlib.sha1(key.encode('utf-8')).hexdigest()[:8], 16)


# ── the belief ───────────────────────────────────────────────────────────────────────────────────────────────
def _grid(cap: float) -> list[float]:
    n = int(round(cap / GRID)) + 1
    return [round(i * GRID, 3) for i in range(n)]


def _fresh(cap: float) -> dict:
    n = len(_grid(cap))
    return {'cap': cap, 'w': [1.0 / n] * n, 'phase': 'searching', 'held': 0, 'up': 0.0, 'dn': 0.0, 'steps': 0,
            'reopens': 0}


def _fit(s: dict, cap: float) -> dict:
    """a search whose cap moved (her card changed): its belief laid onto the new grid, as far as it reaches."""
    if abs(float(s.get('cap') or 0) - cap) < 1e-9 and isinstance(s.get('w'), list):
        return s
    old, xs = list(s.get('w') or []), _grid(cap)
    if not old:
        return {**_fresh(cap), 'steps': s.get('steps', 0), 'reopens': s.get('reopens', 0)}
    tail = min(old) if old else 1.0
    w = [old[i] if i < len(old) else tail for i in range(len(xs))]
    t = sum(w) or 1.0
    return {**s, 'cap': cap, 'w': [v / t for v in w], 'held': 0}


def _quantile(w: list, xs: list, a: float) -> float:
    c = 0.0
    for x, v in zip(xs, w):
        c += v
        if c >= a:
            return x
    return xs[-1]


def _p_steered(x: float, m: float) -> float:
    """how likely the pulled reply wins at strength m, if her edge sits at x"""
    z = (x - m) / TAU
    return LAPSE / 2 + (1 - LAPSE) / (1 + math.exp(-z)) if z > -60 else LAPSE / 2


def _view(key: str, s: dict) -> dict:
    xs, w = _grid(s['cap']), s['w']
    lo, hi, c = _quantile(w, xs, 0.05), _quantile(w, xs, 0.95), _quantile(w, xs, 0.5)
    if not s.get('steps'):  # untaught (an arm sent, her 💗 not yet): the search still starts wide, its whole reach
        lo, hi = xs[0], xs[-1]
    return {'pull': pull_number(key), 'cap': s['cap'], 'lo': lo, 'hi': hi, 'centre': c, 'width': round(hi - lo, 3),
            'phase': s['phase'], 'steps': s['steps'], 'reopens': s['reopens']}


# ── the doors ────────────────────────────────────────────────────────────────────────────────────────────────
def point(key: str, cap: float, rng: Any = None) -> float:
    """the strength this arm tries: the belief's centre (searching · narrowing), or a gentle probe 0.01–0.02
    either side of it (stable) · a free decimal, inside [0.005, cap], cap never above 0.5."""
    rng = rng or random
    cap = max(MIN_TRY, min(CAP, float(cap)))
    with _lock:
        s = _fit(_load()['searches'].get(key) or _fresh(cap), cap)
    m = _quantile(s['w'], _grid(cap), 0.5)
    if s['phase'] == 'stable':
        m += rng.choice((-1, 1)) * rng.uniform(*SHIFT)
    return round(min(cap, max(MIN_TRY, m)), 3)


def tried(key: str, cap: float, m: float, pair: list, side: int, now: float | None = None) -> None:
    """an arm left with strength m on `side`: it waits for her pick (both replies' ids name it)."""
    now = time.time() if now is None else now
    cap = max(MIN_TRY, min(CAP, float(cap)))
    with _lock:
        doc = _load()
        pending = {k: v for k, v in doc['pending'].items() if now - float(v.get('at') or 0) < PENDING_DAYS * 86400}
        trial = {'key': key, 'cap': cap, 'm': m, 'pair': list(pair), 'side': side, 'at': now}
        for mid in pair:
            pending[str(mid)] = trial
        if len(pending) > PENDING_MAX * 2:
            keep = sorted(pending.items(), key=lambda kv: kv[1]['at'])[-PENDING_MAX * 2 :]
            pending = dict(keep)
        doc['pending'] = pending
        doc['searches'].setdefault(key, _fresh(cap))
        _save(doc)


def _update(s: dict, m: float, steered_won: bool) -> tuple[dict, bool]:
    xs = _grid(s['cap'])
    P = [_p_steered(x, m) for x in xs]
    p_steered = sum(v * p for v, p in zip(s['w'], P))  # what the belief expected
    like = P if steered_won else [1 - p for p in P]
    w = [v * l for v, l in zip(s['w'], like)]
    t = sum(w) or 1.0
    n = len(xs)
    w = [(v / t) * (1 - 1e-6) + 1e-6 / n for v in w]  # never exactly nothing anywhere: a moved edge is findable
    r = (1.0 if steered_won else 0.0) - p_steered  # her answer's surprise, signed
    formed = s['phase'] != 'searching'  # surprise counts only against a belief that has formed
    up = max(0.0, float(s.get('up') or 0) + r - CUSUM_K) if formed else 0.0
    dn = max(0.0, float(s.get('dn') or 0) - r - CUSUM_K) if formed else 0.0
    s = {**s, 'w': w, 'steps': int(s.get('steps') or 0) + 1, 'up': up, 'dn': dn}
    if s['phase'] != 'searching' and (up > CUSUM_H or dn > CUSUM_H):
        tempered = [v**WIDEN for v in w]
        t = sum(tempered) or 1.0
        s['w'] = [(1 - FLOOR) * v / t + FLOOR / n for v in tempered]
        s.update({'phase': 'searching', 'held': 0, 'up': 0.0, 'dn': 0.0, 'reopens': int(s.get('reopens') or 0) + 1})
        return s, True
    lo, hi = _quantile(w, xs, 0.05), _quantile(w, xs, 0.95)
    s['held'] = int(s.get('held') or 0) + 1 if hi - lo <= STABLE_WIDTH else 0
    fits = max(up, dn) < CUSUM_H / 2  # her recent answers fit the belief
    s['phase'] = (
        'stable' if s['held'] >= STABLE_HOLD and fits else 'narrowing' if hi - lo <= SPAN else 'searching'
    )
    return s, False


def learn(message_id: str, steered_won: bool, now: float | None = None) -> dict | None:
    """her 💗 on an arm: the reply she chose was the pulled one (steered_won) or the unsteered one. the search
    moves, the step is logged (numbers only) · None when this reply was no arm of the search's (or was learned)."""
    now = time.time() if now is None else now
    with _lock:
        doc = _load()
        trial = doc['pending'].pop(str(message_id), None)
        if not isinstance(trial, dict):
            return None
        for mid in trial.get('pair') or []:
            doc['pending'].pop(str(mid), None)
        key, cap, m = str(trial['key']), float(trial['cap']), float(trial['m'])
        s = _fit(doc['searches'].get(key) or _fresh(cap), cap)
        s, reopened = _update(s, m, bool(steered_won))
        s['w'] = [float(f'{v:.6g}') for v in s['w']]
        doc['searches'][key] = s
        _save(doc)
        v = _view(key, s)
        _log({'t': round(now, 3), 'pull': v['pull'], 'step': s['steps'], 'm': m, 'steered': 1 if steered_won else 0,
              'lo': v['lo'], 'hi': v['hi'], 'centre': v['centre'], 'phase': v['phase'], 'reopened': 1 if reopened else 0})
    return v


def view(key: str) -> dict | None:
    with _lock:
        s = _load()['searches'].get(key)
    return _view(key, s) if isinstance(s, dict) and isinstance(s.get('w'), list) else None


def views() -> dict:
    """every search, by its pull's shelf key (`kind:id`), for her settings"""
    with _lock:
        searches = _load()['searches']
    return {k: _view(k, s) for k, s in searches.items() if isinstance(s, dict) and isinstance(s.get('w'), list)}
