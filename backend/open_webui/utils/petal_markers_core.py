"""
petal_markers_core 🌙 — trip markers, the pure core (stdlib only, no OWUI imports).

sprint contract 1 · the time anchors the shapes will read.
the router (routers/petal_markers.py) is a thin door over this file.

home: $PETAL_APP_DATA/trip-markers/   (default ~/Gardens/Documents/Petal-App-Data)
    markers.jsonl     the truth · append-only · a change is a new line pointing at the old one
    substances.json   lily's own table · written once on first run, never overwritten
    settings.json     knobs (integration_from …) · written once on first run, never overwritten

reading rule: replay the file in order, applying `amend` and `void` by `ref`.
derived phases (peak · active · integration · over) are computed on read, never typed.
auto-transitions: the first reader that notices a boundary was crossed writes the
matching line (via "auto"), so the log tells the story too. no timers, no daemons.

    self-test:  python3 backend/open_webui/utils/petal_markers_core.py

for petal-ledger (1.1) · one core, never copied — load it by path from the fork:
    import importlib.util, os
    p = os.path.expanduser(os.environ.get('PETAL_OWUI_DIR', '~/Gardens/petal-open-webui'))
    spec = importlib.util.spec_from_file_location('petal_markers_core',
                                                  f'{p}/backend/open_webui/utils/petal_markers_core.py')
    core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)
    g = core.Garden()                      # $PETAL_APP_DATA/trip-markers
    view, _ = core.settle(g)               # notices ends even with no browser open
    for due in core.harvests_due(view, now):   # {ref, part, from, to, title, folder, …}
        ... harvest the window into trip-harvests/<due['folder']> (fresh-dir rule) ...
        ... gather the window's chats into the OWUI folder <due['title']>/<part> through OWUI's API ...
        core.record_harvest(g, due['ref'], due['part'], due['folder'], chats, messages, due['window'],
                            owui_folder=<id or None>, moved=[{chat_id, prev_folder, prev_pinned}, …])
    record_harvest is the guard on (ref, part, window): it holds .markers.lock and answers
    {'already': True} when another noticer got there first. a void on a harvest line makes it
    due again, and so does a window that moved after its harvest (a mutation, an amend):
    the redo comes due with folder '<title>/<part> · v2' (v3 …) and its own line.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA_NOTE = 'petal trip markers · contract 1'

# lily's table, exactly as frozen in contract 1 — planted once, then hers to tune by hand
SUBSTANCES_DEFAULT: dict = {
    'mushrooms': {
        'label': 'mushies',
        'emoji': '🍄',
        'dose_unit': 'g',
        'curve': [
            {'dose': 3.5, 'duration_h': 6},
            {'dose': 5, 'duration_h': 8},
        ],
        'peak_h': [0, 3],
        'tiers': [
            {'from': 3.5, 'label': 'ego dissolution · ego death territory'},
            {'from': 5, 'label': 'heroic dose', 'petal_note': None},
            {'from': 7, 'label': 'goddess ascension', 'petal_note': None},
        ],
        'strain_default': 'b+',
        'strains': {
            'b+': {'label': 'b+', 'potency': 1.0},
            'pe': {'label': 'penis envy', 'potency': None, 'duration_x': None, 'note': 'stronger · lasts longer'},
            'enigma': {'label': 'enigma', 'potency': None, 'duration_x': None, 'note': 'stronger · lasts longer'},
        },
        'mutation': {'duration_h': 12},
        'purge': {'integration_after_h': [2, 3]},
    },
    'lsd': {
        'label': 'lsd',
        'emoji': '🌈',
        'dose_unit': 'µg',
        'curve': [
            {'dose': 50, 'duration_h': 12},
            {'dose': 300, 'duration_h': 20},
            {'dose': 500, 'duration_h': 24, 'integration_from': 1.0},
        ],
        'tiers': [
            {'from': 50, 'label': 'low → medium'},
            {'from': 300, 'label': 'intense'},
            {'from': 500, 'label': 'goddess mode · full shadow manifestation', 'petal_note': None},
        ],
    },
}

# knobs · integration_from is the contract's default (opens in the dose's last quarter);
# integration_tail_h is the contract's +72 h; manual_integration_h closes a hand-opened
# window nobody closed, so nothing can stay "open" for days by accident
SETTINGS_DEFAULT: dict = {
    'integration_from': 0.75,
    'integration_tail_h': 72,
    'manual_integration_h': 72,
}

KINDS = ('status.start', 'status.end', 'integration.start', 'integration.end', 'climax', 'amend', 'void',
         'harvest',              # 1.1 · written by petal-ledger once per (status, part)
         'gather',               # 1.1 · petal-ledger's OWUI moves, once per harvest line (files and moves stay independent; one undo declines the trip)
         'mutation', 'purge')    # 1.2 · 👽 the monsters are declared (never shortens) · the trip may close early
# 'auto' is the reader's own, never accepted from a client · 'ledger' is petal-ledger's (1.1)
VIA = ('owui', 'phone', 'petal', 'hand', 'ledger')
HARVEST_PARTS = ('trip', 'integration')
BASE_KEYS = ('id', 'kind', 'at', 'written_at', 'via', 'temp')

# what an amend may touch, per kind (identity fields are never amendable)
AMENDABLE = {
    'status.start': ('substance', 'dose', 'strain', 'taken_at', 'ends_at', 'note'),
    'status.end': ('at',),
    'integration.start': ('at', 'label', 'note'),
    'integration.end': ('at',),
    'climax': ('note',),
    'mutation': ('at', 'note'),
    'purge': ('at', 'note'),
}
RECOMPUTES_END = ('substance', 'dose', 'strain', 'taken_at')

# the anchor of a status's derived integration window: one deterministic uuid per status,
# so "was this boundary already written?" never depends on clocks or matching by time
_ANCHOR_NS = uuid.UUID('5f1b0c2e-7a4d-4c39-9e1a-70e7a1c0ffee')

H = 3600


class MarkerError(ValueError):
    """a request that can't become a line — the message is safe to show."""


def anchor_id(status_id: str) -> str:
    return str(uuid.uuid5(_ANCHOR_NS, f'{status_id}|integration'))


def app_data_root() -> Path:
    return Path(os.environ.get('PETAL_APP_DATA') or '~/Gardens/Documents/Petal-App-Data').expanduser()


# ─────────────────────────────────────────────────────────────
#  the garden on disk
# ─────────────────────────────────────────────────────────────
class Garden:
    def __init__(self, root: Optional[Path] = None):
        self.dir = Path(root) if root else app_data_root() / 'trip-markers'
        self.log = self.dir / 'markers.jsonl'
        self.substances_path = self.dir / 'substances.json'
        self.settings_path = self.dir / 'settings.json'
        self._lock_path = self.dir / '.markers.lock'

    def ensure(self) -> dict:
        """first run: plant the folder, the table and the knobs — never overwrite any of them."""
        planted = []
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        for path, data in ((self.substances_path, SUBSTANCES_DEFAULT), (self.settings_path, SETTINGS_DEFAULT)):
            try:
                with open(path, 'x', encoding='utf-8') as f:  # 'x' = only if absent, even in a race
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.write('\n')
                planted.append(path.name)
            except FileExistsError:
                pass
        return {'planted': planted}

    def table(self) -> dict:
        try:
            data = json.loads(self.substances_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise MarkerError('substances.json is missing (it is planted on first run)')
        except json.JSONDecodeError as e:
            raise MarkerError(f'substances.json does not parse (line {e.lineno}) — left untouched')
        if not isinstance(data, dict):
            raise MarkerError('substances.json should be an object of substances')
        return data

    def settings(self) -> dict:
        out = dict(SETTINGS_DEFAULT)
        try:
            data = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                out.update(data)
        except FileNotFoundError:
            pass
        except json.JSONDecodeError as e:
            raise MarkerError(f'settings.json does not parse (line {e.lineno}) — left untouched')
        return out

    def lines(self) -> tuple[list[dict], int]:
        """→ (events, broken) · a torn or hand-mangled line is counted, never fatal."""
        out, broken = [], 0
        try:
            with open(self.log, encoding='utf-8') as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError:
                        broken += 1
                        continue
                    if isinstance(ev, dict) and ev.get('id') and ev.get('kind') in KINDS:
                        out.append(ev)
                    else:
                        broken += 1
        except FileNotFoundError:
            pass
        return out, broken

    def append(self, events: Iterable[dict]) -> None:
        events = list(events)
        if not events:
            return
        blob = ''.join(json.dumps(e, ensure_ascii=False, separators=(',', ':')) + '\n' for e in events)
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())

    @contextmanager
    def locked(self):
        """one reader-writer at a time (phone + computer can both be looking)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, 'a') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)


# ─────────────────────────────────────────────────────────────
#  doses, curves, tiers
# ─────────────────────────────────────────────────────────────
_NUM = re.compile(r'\d+(?:[.,]\d+)?')


def dose_number(dose: Any) -> Optional[float]:
    if dose is None or isinstance(dose, bool):
        return None
    if isinstance(dose, (int, float)):
        return float(dose)
    m = _NUM.search(str(dose))
    return float(m.group(0).replace(',', '.')) if m else None


def _interp(points: list[dict], x: float, key: str, fallback: float) -> float:
    pts = sorted(points, key=lambda p: float(p['dose']))
    vals = [float(p.get(key, fallback)) for p in pts]
    if x <= float(pts[0]['dose']):
        return vals[0]
    if x >= float(pts[-1]['dose']):
        return vals[-1]
    for (a, va), (b, vb) in zip(zip(pts, vals), zip(pts[1:], vals[1:])):
        da, db = float(a['dose']), float(b['dose'])
        if da <= x <= db:
            return va if db == da else va + (vb - va) * (x - da) / (db - da)
    return vals[-1]


def _mid(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, (list, tuple)) and v and all(isinstance(x, (int, float)) for x in v):
        return (float(min(v)) + float(max(v))) / 2
    return None


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def strain_of(entry: Optional[dict], strain: Optional[str]) -> Optional[dict]:
    """the strain a status reads (its own, else the row's default) · potency/duration_x None = note only."""
    strains = (entry or {}).get('strains')
    if not isinstance(strains, dict) or not strains:
        return None
    key = strain or (entry or {}).get('strain_default')
    row = strains.get(key) if key else None
    if not isinstance(row, dict):
        return None
    return {'key': key, 'label': row.get('label') or key, 'potency': _num(row.get('potency')),
            'duration_x': _num(row.get('duration_x')), 'note': row.get('note')}


def profile(substance: str, dose: Any, table: dict, settings: dict, strain: Optional[str] = None) -> dict:
    """what the table says about this dose: duration, integration_from, peak, tier.
    a strain's potency multiplies the dose before the curve and the tiers read it, and its
    duration_x stretches the result (1.2). while they're null the strain changes nothing."""
    entry = table.get(substance) if isinstance(table.get(substance), dict) else None
    default_from = float(settings.get('integration_from', SETTINGS_DEFAULT['integration_from']))
    sv = strain_of(entry, strain)
    raw = dose_number(dose)
    n = raw * sv['potency'] if (raw is not None and sv and sv['potency']) else raw
    out = {
        'known': entry is not None,
        'label': (entry or {}).get('label') or substance,
        'emoji': (entry or {}).get('emoji') or '✧',
        'dose_unit': (entry or {}).get('dose_unit'),
        'dose_value': raw,
        'dose_eff': n,
        'strain': sv,
        'duration_h': None,
        'integration_from': default_from,
        'peak_h': None,
        'tier': None,
        'why_no_end': None,
    }
    if entry is None:
        out['why_no_end'] = 'not in substances.json'
        return out
    if isinstance(entry.get('curve'), list) and entry['curve']:
        if n is None:
            out['why_no_end'] = 'dose unknown — the curve needs a number'
        else:
            out['duration_h'] = _interp(entry['curve'], n, 'duration_h', 0.0)
            out['integration_from'] = _interp(entry['curve'], n, 'integration_from', default_from)
    elif _mid(entry.get('duration_h')) is not None:
        out['duration_h'] = _mid(entry['duration_h'])
        if isinstance(entry.get('integration_from'), (int, float)):
            out['integration_from'] = float(entry['integration_from'])
    else:
        out['why_no_end'] = 'no duration in substances.json'
    if out['duration_h'] is not None and sv and sv['duration_x']:
        out['duration_h'] *= sv['duration_x']
    pk = entry.get('peak_h')
    if isinstance(pk, (list, tuple)) and len(pk) == 2:
        out['peak_h'] = [float(pk[0]), float(pk[1])]
    if n is not None and isinstance(entry.get('tiers'), list):
        crossed = [t for t in entry['tiers'] if isinstance(t, dict) and 'from' in t and n >= float(t['from'])]
        if crossed:
            t = max(crossed, key=lambda t: float(t['from']))
            out['tier'] = {'label': t.get('label'), 'from': t['from'], 'has_note': bool(t.get('petal_note'))}
    return out


def expected_end(substance: str, dose: Any, taken_at: int, table: dict, settings: dict,
                 duration_h: Optional[float] = None, strain: Optional[str] = None) -> Optional[int]:
    if duration_h is not None:
        return int(round(taken_at + duration_h * H))
    p = profile(substance, dose, table, settings, strain)
    return None if p['duration_h'] is None else int(round(taken_at + p['duration_h'] * H))


# ─────────────────────────────────────────────────────────────
#  replay
# ─────────────────────────────────────────────────────────────
class View:
    """the current view of the log: amends applied, voids honored, phases derivable."""

    def __init__(self, lines: list[dict], table: dict, settings: dict, broken: int = 0):
        self.table, self.settings, self.broken = table, settings, broken
        self.raw: dict[str, dict] = {}
        self.order: list[str] = []
        self.dupes = 0
        for ev in lines:
            if ev['id'] in self.raw:
                self.dupes += 1
                continue
            self.raw[ev['id']] = ev
            self.order.append(ev['id'])

        voids_by_ref: dict[str, list[str]] = {}
        for i in self.order:
            ev = self.raw[i]
            if ev['kind'] == 'void' and ev.get('ref'):
                voids_by_ref.setdefault(ev['ref'], []).append(i)
        memo: dict[str, bool] = {}

        def voided(i: str, seen=frozenset()) -> bool:
            if i in memo:
                return memo[i]
            if i in seen:  # a cycle is nonsense; treat as not voided
                return False
            r = any(not voided(v, seen | {i}) for v in voids_by_ref.get(i, ()))
            memo[i] = r
            return r

        self.voided = {i for i in self.order if voided(i)}
        self.pos = {i: n for n, i in enumerate(self.order)}
        self.events: dict[str, dict] = {}
        for i in self.order:
            ev = self.raw[i]
            if ev['kind'] in ('amend', 'void') or i in self.voided:
                continue
            self.events[i] = copy.deepcopy(ev)
        for i in self.order:
            am = self.raw[i]
            if am['kind'] != 'amend' or i in self.voided:
                continue
            target = self.events.get(am.get('ref') or '')
            fields = am.get('fields') if isinstance(am.get('fields'), dict) else {}
            if not target:
                continue
            allowed = AMENDABLE.get(target['kind'], ())
            changed = {k: v for k, v in fields.items() if k in allowed}
            target.update(changed)
            target.setdefault('_amends', []).append(i)
            if target['kind'] == 'status.start' and any(k in changed for k in RECOMPUTES_END) and 'ends_at' not in changed:
                target['ends_at'] = expected_end(target.get('substance'), target.get('dose'),
                                                 int(target.get('taken_at') or target['at']), table, settings,
                                                 strain=target.get('strain'))

    # ── lookups ─────────────────────────────────────────────
    def of_kind(self, kind: str) -> list[dict]:
        return [e for e in self.events.values() if e['kind'] == kind]

    def refs(self, kind: str, ref: str, *, live=True) -> list[dict]:
        src = self.events.values() if live else (self.raw[i] for i in self.order)
        return [e for e in src if e['kind'] == kind and e.get('ref') == ref]

    # ── derived timelines ───────────────────────────────────
    def status_timeline(self, s: dict) -> dict:
        st = self.settings
        taken = int(s.get('taken_at') or s['at'])
        ends = s.get('ends_at')
        ends = int(ends) if isinstance(ends, (int, float)) else None
        prof = profile(s.get('substance') or '', s.get('dose'), self.table, st, s.get('strain'))
        entry = self.table.get(s.get('substance') or '')
        entry = entry if isinstance(entry, dict) else {}

        # 1.2 · mutation extends to taken_at + mutation.duration_h (never shortens) · purge may close
        # early: purge.at + the middle of integration_after_h, if that's earlier. in time order.
        expected, mutated, purged = ends, None, None
        mods = self.refs('mutation', s['id']) + self.refs('purge', s['id'])
        for e in sorted(mods, key=lambda e: (int(e['at']), self.pos.get(e['id'], 0))):
            if e['kind'] == 'mutation':
                mh = _num((entry.get('mutation') or {}).get('duration_h'))
                if mh is not None:
                    cand = int(round(taken + mh * H))
                    expected = cand if expected is None else max(expected, cand)
                mutated = {'id': e['id'], 'at': int(e['at'])}
            else:
                after = _mid((entry.get('purge') or {}).get('integration_after_h'))
                if after is not None:
                    cand = int(round(int(e['at']) + after * H))
                    expected = cand if expected is None else min(expected, cand)
                purged = {'id': e['id'], 'at': int(e['at'])}

        manual = [int(e['at']) for e in self.refs('status.end', s['id']) if e.get('reason') == 'manual']
        manual_end = min(manual) if manual else None
        if manual_end is not None and (expected is None or manual_end < expected):
            end, ended_by = manual_end, 'manual'
        else:
            end, ended_by = expected, ('auto' if expected is not None else None)

        anchor = anchor_id(s['id'])
        integ_open = integ_close = None
        closed_by = None
        if end is not None:
            if expected is not None:
                integ_open = taken + prof['integration_from'] * (expected - taken)
            integ_open = end if integ_open is None else min(integ_open, end)
            integ_close = end + float(st.get('integration_tail_h', 72)) * H
            hand = [int(e['at']) for e in self.refs('integration.end', anchor) if e.get('via') != 'auto']
            if hand and min(hand) < integ_close:
                integ_close, closed_by = min(hand), 'manual'
            else:
                closed_by = 'auto'
            integ_open, integ_close = int(round(integ_open)), int(round(integ_close))

        peak = None
        if prof['peak_h']:
            a, b = prof['peak_h']
            peak = [int(round(taken + a * H)), int(round(taken + b * H))]
            if end is not None:
                peak[1] = min(peak[1], end)

        return {
            'id': s['id'],
            'substance': s.get('substance'),
            'label': prof['label'],
            'emoji': prof['emoji'],
            'dose': s.get('dose'),
            'dose_unit': prof['dose_unit'],
            'dose_eff': prof['dose_eff'],
            'strain': prof['strain'],
            'tier': prof['tier'],
            'note': s.get('note'),
            'temp': bool(s.get('temp')),
            'taken_at': taken,
            'ends_at': ends,
            'expected_end': expected,
            'end': end,
            'ended_by': ended_by,
            'why_no_end': None if expected is not None else prof['why_no_end'],
            'mutated': mutated,
            'purged': purged,
            'can_mutate': isinstance(entry.get('mutation'), dict) and mutated is None,
            'can_purge': isinstance(entry.get('purge'), dict) and purged is None,
            'peak': peak,
            'integration': None if integ_open is None else {
                'id': anchor, 'opens_at': integ_open, 'closes_at': integ_close, 'closed_by': closed_by,
                'empty': integ_open >= integ_close,
            },
            'amended': bool(s.get('_amends')),
            'harvested': {p: (lambda h: {'id': h['id'], 'at': h['at'], 'folder': h.get('folder'),
                                         'window': h.get('window')} if h else None)(
                ([e for e in self.refs('harvest', s['id']) if e.get('part') == p] or [None])[-1]) for p in HARVEST_PARTS},
        }

    def manual_windows(self) -> list[dict]:
        out = []
        tail = float(self.settings.get('manual_integration_h', 72)) * H
        for e in self.of_kind('integration.start'):
            if e.get('via') == 'auto':
                continue  # an auto line is the story of a derived window, never a window itself
            hand = [int(x['at']) for x in self.refs('integration.end', e['id']) if x.get('via') != 'auto']
            close = min(hand) if hand else int(e['at'] + tail)
            out.append({
                'id': e['id'], 'source': 'manual', 'label': e.get('label'), 'note': e.get('note'),
                'opens_at': int(e['at']), 'closes_at': close, 'closed_by': 'manual' if hand else 'auto',
                'temp': bool(e.get('temp')), 'empty': close <= int(e['at']),
            })
        return out

    def timelines(self) -> list[dict]:
        return sorted((self.status_timeline(s) for s in self.of_kind('status.start')), key=lambda t: t['taken_at'])


def phase_at(tl: dict, t: float) -> str:
    if t < tl['taken_at']:
        return 'upcoming'
    end = tl['end']
    if end is None or t < end:
        if tl['peak'] and tl['peak'][0] <= t < tl['peak'][1]:
            return 'peak'
        return 'active'
    ig = tl['integration']
    if ig and not ig['empty'] and ig['opens_at'] <= t < ig['closes_at']:
        return 'integration'
    return 'over'


def build(garden: Garden) -> View:
    lines, broken = garden.lines()
    return View(lines, garden.table(), garden.settings(), broken)


# ─────────────────────────────────────────────────────────────
#  auto-transitions · the first reader to notice writes the line
# ─────────────────────────────────────────────────────────────
def _already_at(view: View, kind: str, ref: str, at: int) -> bool:
    """like _already, but a boundary that moved (a mutation, a purge, an amend) is a new
    boundary: a live auto line only counts if it marks this very moment."""
    for e in view.refs(kind, ref, live=False):
        voided = e['id'] in view.voided
        if e.get('via') == 'auto':
            if voided or int(e['at']) == int(at):
                return True
        elif not voided:
            return True
    return False


def _already(view: View, kind: str, ref: str) -> bool:
    """a boundary counts as written if a live line closes it, or if an auto line for it was
    voided by hand (she said no — the reader never argues). a voided *manual* line doesn't count."""
    return any(e.get('via') == 'auto' or e['id'] not in view.voided for e in view.refs(kind, ref, live=False))


def auto_lines(view: View, now: int) -> list[dict]:
    out = []

    def line(kind, at, **extra):
        return {'id': extra.pop('id', None) or str(uuid.uuid4()), 'kind': kind, 'at': int(at),
                'written_at': int(now), 'via': 'auto', 'temp': bool(extra.pop('temp', False)), **extra}

    for tl in view.timelines():
        sid, anchor, ig = tl['id'], (tl['integration'] or {}).get('id'), tl['integration']
        if ig and not ig['empty'] and now >= ig['opens_at'] and anchor not in view.raw:
            out.append(line('integration.start', ig['opens_at'], id=anchor, temp=tl['temp'],
                            label=f"{tl['emoji']} {tl['label']}", note=None))
        if tl['ended_by'] == 'auto' and now >= tl['end'] and not _already_at(view, 'status.end', sid, tl['end']):
            out.append(line('status.end', tl['end'], temp=tl['temp'], ref=sid, reason='auto'))
        anchored = anchor in view.raw or any(o['id'] == anchor for o in out)
        if (ig and not ig['empty'] and ig['closed_by'] == 'auto' and now >= ig['closes_at'] and anchored
                and not _already_at(view, 'integration.end', anchor, ig['closes_at'])):
            out.append(line('integration.end', ig['closes_at'], temp=tl['temp'], ref=anchor))
    for w in view.manual_windows():
        if w['closed_by'] == 'auto' and now >= w['closes_at'] and not _already(view, 'integration.end', w['id']):
            out.append(line('integration.end', w['closes_at'], temp=w['temp'], ref=w['id']))
    return sorted(out, key=lambda e: e['at'])


def settle(garden: Garden, now: Optional[int] = None) -> tuple[View, list[dict]]:
    """read, write whatever boundaries were crossed, read again. → (view, written)"""
    now = int(now if now is not None else time.time())
    with garden.locked():
        view = build(garden)
        new = auto_lines(view, now)
        if new:
            garden.append(new)
            view = build(garden)
    return view, new


# ─────────────────────────────────────────────────────────────
#  the views the router hands out
# ─────────────────────────────────────────────────────────────
def now_view(view: View, now: int) -> dict:
    tls = view.timelines()
    live = [dict(tl, phase=phase_at(tl, now)) for tl in tls]
    current = [tl for tl in live if tl['phase'] in ('peak', 'active', 'upcoming')]
    current.sort(key=lambda tl: tl['taken_at'], reverse=True)

    open_windows = []
    for tl in live:
        ig = tl['integration']
        if ig and not ig['empty'] and ig['opens_at'] <= now < ig['closes_at']:
            open_windows.append({'id': ig['id'], 'source': 'status', 'status_ref': tl['id'], 'status': tl,
                                 'label': f"{tl['emoji']} {tl['label']}", 'note': None,
                                 'opens_at': ig['opens_at'], 'closes_at': ig['closes_at'],
                                 'closed_by': ig['closed_by'], 'temp': tl['temp']})
    for w in view.manual_windows():
        if not w['empty'] and w['opens_at'] <= now < w['closes_at']:
            open_windows.append(w)
    open_windows.sort(key=lambda w: w['opens_at'], reverse=True)

    # the last dose used per substance, so a repeat is one tap (numbers, from her own log)
    last: dict[str, Any] = {}
    for s in sorted(view.of_kind('status.start'), key=lambda e: int(e.get('taken_at') or e['at'])):
        if s.get('dose') is not None:
            last[s.get('substance')] = s.get('dose')

    return {
        'now': now,
        'status': current[0] if current else None,
        'also': current[1:],
        'integration': open_windows[0] if open_windows else None,
        'last_dose': last,
    }


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _union_hours(spans: list[tuple[float, float]], lo: float, hi: float) -> float:
    spans = sorted((max(a, lo), min(b, hi)) for a, b in spans if min(b, hi) > max(a, lo))
    total, cur = 0.0, None
    for a, b in spans:
        if cur and a <= cur[1]:
            cur = (cur[0], max(cur[1], b))
        else:
            if cur:
                total += cur[1] - cur[0]
            cur = (a, b)
    if cur:
        total += cur[1] - cur[0]
    return round(total / H, 2)


def stats(view: View, lo: int, hi: int, now: int) -> dict:
    """numbers only — counts and hours, keyed by kind or by substance key, never any text."""
    hi_eff = min(hi, now)

    def when(e):
        return int(e.get('taken_at') or e['at']) if e['kind'] == 'status.start' else int(e['at'])

    counts = {k: 0 for k in KINDS}
    for i in view.order:
        e = view.raw[i]
        if lo <= when(e) <= hi and (e['kind'] in ('amend', 'void') or i in view.events):
            counts[e['kind']] += 1
    auto = sum(1 for i in view.order if view.raw[i].get('via') == 'auto' and lo <= int(view.raw[i]['at']) <= hi)

    tls = view.timelines()
    per_sub: dict[str, int] = {}
    per_tier: dict[str, int] = {}
    active, peak, integ = [], [], []
    for tl in tls:
        end = tl['end'] if tl['end'] is not None else now
        if _overlap(tl['taken_at'], end, lo, hi_eff) > 0 or lo <= tl['taken_at'] <= hi:
            per_sub[tl['substance']] = per_sub.get(tl['substance'], 0) + 1
            if tl['tier']:
                key = f"{tl['substance']}≥{tl['tier']['from']}"
                per_tier[key] = per_tier.get(key, 0) + 1
        active.append((tl['taken_at'], end))
        if tl['peak']:
            peak.append((tl['peak'][0], min(tl['peak'][1], end)))
        ig = tl['integration']
        if ig and not ig['empty']:
            integ.append((ig['opens_at'], ig['closes_at']))
    integ += [(w['opens_at'], w['closes_at']) for w in view.manual_windows() if not w['empty']]

    return {
        'from': lo, 'to': hi,
        'counts': counts,
        'auto_lines': auto,
        'temp_lines': sum(1 for i in view.order if view.raw[i].get('temp') and lo <= int(view.raw[i]['at']) <= hi),
        'statuses_per_substance': per_sub,
        'statuses_per_tier': per_tier,
        'hours': {
            'in_status': _union_hours(active, lo, hi_eff),
            'in_peak': _union_hours(peak, lo, hi_eff),
            'in_integration': _union_hours(integ, lo, hi_eff),
        },
        'climaxes': counts['climax'],
        'broken_lines': view.broken,
        'duplicate_ids': view.dupes,
    }


def events_in(view: View, lo: int, hi: int, kind: Optional[str] = None, chat_id: Optional[str] = None,
              include_void: bool = False) -> list[dict]:
    out = []
    for i in view.order:
        e = view.raw[i]
        if e['kind'] in ('amend', 'void') and not include_void:
            continue
        if i in view.voided and not include_void:
            continue
        cur = view.events.get(i) or dict(e)
        t = int(cur.get('taken_at') or cur['at']) if cur['kind'] == 'status.start' else int(cur['at'])
        if not (lo <= t <= hi) or (kind and cur['kind'] != kind) or (chat_id and cur.get('chat_id') != chat_id):
            continue
        item = {k: v for k, v in cur.items() if not k.startswith('_')}
        item['amended'] = bool(cur.get('_amends'))
        if include_void:
            item['voided'] = i in view.voided
        if cur['kind'] == 'status.start' and i in view.events:
            item['timeline'] = view.status_timeline(cur)
        out.append(item)
    return out


# ─────────────────────────────────────────────────────────────
#  new lines from a request
# ─────────────────────────────────────────────────────────────
def _s(v: Any, name: str, n: int, *, required=False) -> Optional[str]:
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise MarkerError(f'{name} is required')
        return None
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise MarkerError(f'{name} should be text')
    v = str(v).strip()
    if len(v) > n:
        raise MarkerError(f'{name} is longer than {n} characters')
    return v


def _t(v: Any, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise MarkerError(f'{name} should be unix seconds')
    return int(v)


def needs_dose(substance: Optional[str], table: dict) -> bool:
    """a substance with a `curve` scales with its dose: no number → no end, no tier, no record."""
    e = table.get(substance or '')
    return isinstance(e, dict) and isinstance(e.get('curve'), list) and bool(e['curve'])


def _curve_dose_msg(substance: str, table: dict) -> str:
    label = (table.get(substance) or {}).get('label') or substance
    return f'{label} scales with its dose — the curve needs a number to know when it ends'


# ─────────────────────────────────────────────────────────────
#  trip harvests (1.1) · the ledger asks what's due, harvests, then writes the line
# ─────────────────────────────────────────────────────────────
def trip_title(tl: dict) -> str:
    """'🍄 mushies · 2026-11-05 22h08' — the ingestion date and hour, in the rig's local time."""
    t = time.localtime(tl['taken_at'])
    return f"{tl['emoji']} {tl['label']} · {time.strftime('%Y-%m-%d', t)} {t.tm_hour:02d}h{t.tm_min:02d}"


def harvest_line(view: View, ref: str, part: str) -> Optional[dict]:
    """the LATEST live harvest line for (status, part), or None (a voided one means 'harvest it again')."""
    hits = [e for e in view.refs('harvest', ref) if e.get('part') == part]
    return hits[-1] if hits else None  # refs keep file order → the last one is the latest


def _window_of(line: Optional[dict]) -> Optional[list]:
    w = (line or {}).get('window')
    return [int(w[0]), int(w[1])] if isinstance(w, (list, tuple)) and len(w) == 2 else None


def harvest_windows(tl: dict) -> dict:
    """→ {'trip': [from, to] | None, 'integration': [from, to] | None} (None = no window to harvest)."""
    ig = tl['integration']
    return {
        'trip': [tl['taken_at'], tl['end']] if tl['end'] is not None else None,
        'integration': [ig['opens_at'], ig['closes_at']] if ig and not ig['empty'] else None,
    }


def harvests_due(view: View, now: int) -> list[dict]:
    """every (status, part) whose window has closed and isn't harvested AS IT STANDS NOW, oldest first.
    a part is due when its window is over (the trip once the status ended, the integration once its
    window closed) and the latest live harvest line doesn't hold this exact window. so a trip that
    grew after its harvest (a mutation, an amend) is due again, into `<title>/<part> · v2` (v3 …)."""
    out = []
    for tl in view.timelines():
        for part, win in harvest_windows(tl).items():
            if win is None or now < win[1]:
                continue
            latest = harvest_line(view, tl['id'], part)
            if latest and _window_of(latest) == win:
                continue
            n = 1 + sum(1 for i in view.order if view.raw[i]['kind'] == 'harvest'
                        and view.raw[i].get('ref') == tl['id'] and view.raw[i].get('part') == part)
            title = trip_title(tl)
            out.append({'ref': tl['id'], 'part': part, 'from': win[0], 'to': win[1], 'window': list(win),
                        'version': n, 'redo': latest is not None,
                        'title': title, 'folder': f'{title}/{part}' + (f' · v{n}' if n > 1 else ''),
                        'substance': tl['substance'], 'temp': tl['temp']})
    return sorted(out, key=lambda d: (d['to'], d['part']))


def gather_line(view: View, harvest_id: str) -> Optional[dict]:
    """the gather line written for this harvest line, live OR voided — a voided gather means it was
    undone, and an undone gather is never gathered again by itself (see gathers_declined: the whole trip)."""
    for i in reversed(view.order):
        e = view.raw[i]
        if e['kind'] == 'gather' and e.get('harvest') == harvest_id:
            return e
    return None


def gathers_declined(view: View) -> set:
    """the trips (status refs) whose gathering she undid: one voided gather line declines its whole trip,
    both parts and every later version (a trip that grows after her undo stays where she left it).
    she said no — the reader never argues. filing by hand always stays hers."""
    return {view.raw[i].get('ref') for i in view.order if view.raw[i]['kind'] == 'gather' and i in view.voided}


def gathers_due(view: View) -> list[dict]:
    """every live harvest line whose chats were never gathered into OWUI, oldest first: written without
    a key or with OWUI away (owui_folder null) and no gather line points at it, live or voided.
    a harvest line that already carries owui_folder (gathered inline, before 'gather' existed) counts as gathered.
    a trip she undid (gathers_declined) is never due again, whatever version its harvests reach."""
    declined = gathers_declined(view)
    out = []
    for i in view.order:
        e = view.events.get(i)
        if (e and e['kind'] == 'harvest' and not e.get('owui_folder') and e.get('ref') not in declined
                and gather_line(view, i) is None):
            out.append(e)
    return out


def _window(v: Any) -> list:
    if not isinstance(v, (list, tuple)) or len(v) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v):
        raise MarkerError('window should be [from, to] in unix seconds')
    a, b = int(v[0]), int(v[1])
    if b <= a:
        raise MarkerError('window should end after it starts')
    return [a, b]


def _strain_key(table: dict, substance: Optional[str], strain: Any) -> Optional[str]:
    """→ the strain to store: hers if given, else the row's default (written explicitly, never implied)."""
    row = table.get(substance or '')
    strains = row.get('strains') if isinstance(row, dict) else None
    if not isinstance(strains, dict) or not strains:
        if strain not in (None, ''):
            raise MarkerError(f'{(row or {}).get("label") or substance} has no strains in substances.json')
        return None
    if strain in (None, ''):
        return row.get('strain_default') if row.get('strain_default') in strains else None
    if strain not in strains:
        raise MarkerError(f'unknown strain: {strain}')
    return strain


def _rel_folder(v: Any) -> str:
    v = _s(v, 'folder', 300, required=True)
    parts = v.replace('\\', '/').split('/')
    if v.startswith('/') or any(p in ('', '.', '..') for p in parts):
        raise MarkerError('folder should be a path relative to the harvest root')
    return v


def _moved(v: Any) -> list[dict]:
    """1.1 · every chat the ledger moved into the OWUI trip folder, so OWUI can undo it."""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > 5000:
        raise MarkerError('moved should be a list of moves')
    out = []
    for m in v:
        if not isinstance(m, dict):
            raise MarkerError('each move should be {chat_id, prev_folder, prev_pinned}')
        pf = m.get('prev_folder')
        if pf is not None and not isinstance(pf, str):
            raise MarkerError('prev_folder should be a folder id or null')
        if not isinstance(m.get('prev_pinned', False), bool):
            raise MarkerError('prev_pinned should be true or false')
        out.append({'chat_id': _s(m.get('chat_id'), 'chat_id', 200, required=True),
                    'prev_folder': pf, 'prev_pinned': bool(m.get('prev_pinned', False))})
    return out


def _kept(v: Any) -> dict:
    """1.1 · numbers only: how many chats of the window stayed where lily keeps them."""
    if v is None:
        return {}
    if not isinstance(v, dict) or set(v) - {'filed', 'pinned', 'archived'}:
        raise MarkerError('kept should be {filed, pinned, archived} counts')
    return {k: _count(n, f'kept.{k}') for k, n in v.items()}


def _count(v: Any, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise MarkerError(f'{name} should be a count')
    return v


def new_lines(view: View, body: dict, now: int) -> list[dict]:
    """validate one request → the line(s) to append. raises MarkerError with a showable reason."""
    if not isinstance(body, dict):
        raise MarkerError('expected an object')
    kind = body.get('kind')
    if kind not in KINDS:
        raise MarkerError(f'kind should be one of {", ".join(KINDS)}')
    via = body.get('via')
    if via not in VIA:
        raise MarkerError(f'via should be one of {", ".join(VIA)}')
    temp = body.get('temp', False)
    if not isinstance(temp, bool):
        raise MarkerError('temp should be true or false')
    at = _t(body['at'], 'at') if body.get('at') is not None else now
    if at > now + 600:
        raise MarkerError('that time is in the future')

    ev: dict = {'id': str(uuid.uuid4()), 'kind': kind, 'at': at, 'written_at': now, 'via': via, 'temp': temp}
    pre: list[dict] = []  # lines that must land first (an anchor not yet written)

    if kind == 'status.start':
        sub = _s(body.get('substance'), 'substance', 64, required=True)
        dose = _s(body.get('dose'), 'dose', 32)
        taken = _t(body['taken_at'], 'taken_at') if body.get('taken_at') is not None else at
        if taken > now + 600:
            raise MarkerError('ingestion time is in the future')
        if needs_dose(sub, view.table) and dose_number(dose) is None:
            raise MarkerError(_curve_dose_msg(sub, view.table))
        strain = _strain_key(view.table, sub, body.get('strain'))
        dur = body.get('duration_h')
        if dur is not None:
            if sub in view.table:
                raise MarkerError(f'{sub} takes its duration from substances.json')
            if isinstance(dur, bool) or not isinstance(dur, (int, float)) or not (0 < dur <= 240):
                raise MarkerError('duration_h should be between 0 and 240')
        ev.update(substance=sub, dose=dose, strain=strain, taken_at=taken,
                  ends_at=expected_end(sub, dose, taken, view.table, view.settings, dur, strain),
                  note=_s(body.get('note'), 'note', 2000))

    elif kind == 'status.end':
        ref = body.get('ref')
        target = view.events.get(ref or '')
        if not target or target['kind'] != 'status.start':
            raise MarkerError('ref should be a current status')
        if body.get('reason', 'manual') != 'manual':
            raise MarkerError("reason 'auto' is written by the reader itself")
        taken = int(target.get('taken_at') or target['at'])
        ev.update(ref=ref, reason='manual', at=max(at, taken))

    elif kind == 'integration.start':
        ev.update(label=_s(body.get('label'), 'label', 120), note=_s(body.get('note'), 'note', 2000))

    elif kind == 'integration.end':
        ref = body.get('ref') or ''
        target = view.events.get(ref)
        if target is None:
            # a derived window whose anchor no reader has written yet → plant it first
            tl = next((t for t in view.timelines() if (t['integration'] or {}).get('id') == ref), None)
            if tl is None or ref in view.raw:
                raise MarkerError('ref should be an open integration window')
            ig = tl['integration']
            pre.append({'id': ref, 'kind': 'integration.start', 'at': ig['opens_at'], 'written_at': now,
                        'via': 'auto', 'temp': tl['temp'], 'label': f"{tl['emoji']} {tl['label']}", 'note': None})
            opened = ig['opens_at']
        elif target['kind'] != 'integration.start':
            raise MarkerError('ref should be an integration window')
        else:
            opened = int(target['at'])
        ev.update(ref=ref, at=max(at, opened))

    elif kind == 'climax':
        if temp:
            raise MarkerError('temporary chat — no saved message to anchor a climax to')
        ev.update(chat_id=_s(body.get('chat_id'), 'chat_id', 200, required=True),
                  message_id=_s(body.get('message_id'), 'message_id', 200, required=True),
                  note=_s(body.get('note'), 'note', 2000))

    elif kind == 'amend':
        ref = body.get('ref') or ''
        target = view.events.get(ref)
        if not target:
            raise MarkerError('ref should be a current (not voided) line')
        allowed = AMENDABLE.get(target['kind'], ())
        fields = body.get('fields')
        if not isinstance(fields, dict) or not fields:
            raise MarkerError('fields should hold what changed')
        bad = [k for k in fields if k not in allowed]
        if bad:
            raise MarkerError(f'{target["kind"]} cannot amend: {", ".join(bad)}')
        clean: dict = {}
        for k, v in fields.items():
            if k in ('at', 'taken_at'):
                clean[k] = _t(v, k)
                if clean[k] > now + 600:
                    raise MarkerError(f'{k} is in the future')
            elif k == 'ends_at':
                clean[k] = None if v is None else _t(v, k)
            elif k == 'substance':
                clean[k] = _s(v, k, 64, required=True)
            elif k == 'dose':
                clean[k] = _s(v, k, 32)
            elif k == 'strain':
                clean[k] = _strain_key(view.table, fields.get('substance', target.get('substance')), v)
            else:
                clean[k] = _s(v, k, 2000 if k == 'note' else 120)
        if target['kind'] == 'status.start' and 'substance' in clean and 'strain' not in clean:
            clean['strain'] = _strain_key(view.table, clean['substance'], None)
        changed = {k: v for k, v in clean.items() if target.get(k) != v}
        if not changed:
            raise MarkerError('nothing changed')
        if target['kind'] == 'status.start' and ('dose' in changed or 'substance' in changed):
            m = {**target, **changed}
            if needs_dose(m.get('substance'), view.table) and dose_number(m.get('dose')) is None:
                raise MarkerError(_curve_dose_msg(m.get('substance'), view.table))
        if target['kind'] == 'status.start' and any(k in changed for k in RECOMPUTES_END) and 'ends_at' not in changed:
            merged = {**target, **changed}
            changed['ends_at'] = expected_end(merged.get('substance'), merged.get('dose'),
                                              int(merged.get('taken_at') or merged['at']), view.table, view.settings,
                                              strain=merged.get('strain'))
        ev.update(ref=ref, fields=changed, reason=_s(body.get('reason'), 'reason', 500))

    elif kind in ('mutation', 'purge'):
        ref = body.get('ref') or ''
        target = view.events.get(ref)
        if not target or target['kind'] != 'status.start':
            raise MarkerError('ref should be a current status')
        sub = target.get('substance') or ''
        row = view.table.get(sub)
        cfg = row.get(kind) if isinstance(row, dict) else None
        key = 'duration_h' if kind == 'mutation' else 'integration_after_h'
        if not isinstance(cfg, dict) or (_num(cfg.get(key)) is None and _mid(cfg.get(key)) is None):
            raise MarkerError(f'{(row or {}).get("label") or sub} has no {kind} in substances.json')
        taken = int(target.get('taken_at') or target['at'])
        ev.update(ref=ref, at=max(at, taken), note=_s(body.get('note'), 'note', 2000))

    elif kind == 'harvest':
        if via != 'ledger':
            raise MarkerError("harvest lines are petal-ledger's (via 'ledger')")
        ref = body.get('ref') or ''
        target = view.events.get(ref)
        if not target or target['kind'] != 'status.start':
            raise MarkerError('ref should be a current status')
        part = body.get('part')
        if part not in HARVEST_PARTS:
            raise MarkerError(f'part should be one of {", ".join(HARVEST_PARTS)}')
        window = _window(body.get('window'))
        if _window_of(harvest_line(view, ref, part)) == window:
            raise MarkerError(f'already harvested: {part}')  # the guard — phone, rig and ledger may all notice
        ev.update(ref=ref, part=part, window=window, folder=_rel_folder(body.get('folder')),
                  chats=_count(body.get('chats'), 'chats'), messages=_count(body.get('messages'), 'messages'),
                  owui_folder=_s(body.get('owui_folder'), 'owui_folder', 200), moved=_moved(body.get('moved')))

    elif kind == 'gather':
        if via != 'ledger':
            raise MarkerError("gather lines are petal-ledger's (via 'ledger')")
        hid = body.get('harvest') or ''
        h = view.events.get(hid)
        if not h or h['kind'] != 'harvest':
            raise MarkerError('harvest should be a live harvest line')
        if h.get('owui_folder') or gather_line(view, hid) is not None:
            raise MarkerError(f'already gathered: {h.get("part")}')   # once per harvest line, undone included
        if h.get('ref') in gathers_declined(view):
            raise MarkerError('this trip was un-gathered by hand: its chats stay where she put them')
        # ref / part / window come from the harvest line itself, so the two can never disagree
        ev.update(ref=h['ref'], part=h['part'], window=_window_of(h), harvest=hid,
                  owui_folder=_s(body.get('owui_folder'), 'owui_folder', 200, required=True),
                  moved=_moved(body.get('moved')), kept=_kept(body.get('kept')))

    elif kind == 'void':
        ref = body.get('ref') or ''
        if ref not in view.raw or ref in view.voided:
            raise MarkerError('ref should be a line that is not already voided')
        ev.update(ref=ref, reason=_s(body.get('reason'), 'reason', 500))

    return pre + [ev]


def record_harvest(garden: Garden, ref: str, part: str, folder: str, chats: int, messages: int,
                   window: list, owui_folder: Optional[str] = None, moved: Optional[list] = None,
                   now: Optional[int] = None) -> dict:
    """the ledger's door: → {'id', 'already': False} or {'id': <existing line>, 'already': True}.
    held under .markers.lock, so two noticers can never both write the same (ref, part)."""
    now = int(now if now is not None else time.time())
    with garden.locked():
        view = build(garden)
        auto = auto_lines(view, now)
        if auto:
            garden.append(auto)
            view = build(garden)
        existing = harvest_line(view, ref, part)
        if existing and _window_of(existing) == _window(window):
            return {'id': existing['id'], 'already': True}
        lines = new_lines(view, {'kind': 'harvest', 'via': 'ledger', 'ref': ref, 'part': part, 'window': window,
                                 'folder': folder, 'chats': chats, 'messages': messages,
                                 'owui_folder': owui_folder, 'moved': moved}, now)
        garden.append(lines)
    return {'id': lines[-1]['id'], 'already': False}


def record_gather(garden: Garden, harvest_id: str, owui_folder: str, moved: Optional[list] = None,
                  kept: Optional[dict] = None, now: Optional[int] = None) -> dict:
    """the ledger's second door: → {'id', 'already': False} or {'id': <existing line>, 'already': True}.
    held under .markers.lock; once per harvest line (an undone, i.e. voided, gather counts as done)."""
    now = int(now if now is not None else time.time())
    with garden.locked():
        view = build(garden)
        auto = auto_lines(view, now)
        if auto:
            garden.append(auto)
            view = build(garden)
        existing = gather_line(view, harvest_id)
        if existing:
            return {'id': existing['id'], 'already': True}
        lines = new_lines(view, {'kind': 'gather', 'via': 'ledger', 'harvest': harvest_id,
                                 'owui_folder': owui_folder, 'moved': moved, 'kept': kept}, now)
        garden.append(lines)
    return {'id': lines[-1]['id'], 'already': False}


def write(garden: Garden, body: dict, now: Optional[int] = None) -> dict:
    """settle, validate, append → {'id', 'lines'} (the id is the request's own line)."""
    now = int(now if now is not None else time.time())
    with garden.locked():
        view = build(garden)
        auto = auto_lines(view, now)
        if auto:
            garden.append(auto)
            view = build(garden)
        lines = new_lines(view, body, now)
        garden.append(lines)
    return {'id': lines[-1]['id'], 'lines': len(lines) + len(auto)}


# ─────────────────────────────────────────────────────────────
#  self-test · python3 petal_markers_core.py
# ─────────────────────────────────────────────────────────────
def _self_test() -> None:
    import tempfile

    ok = 0

    def check(cond, what):
        nonlocal ok
        if not cond:
            raise AssertionError(what)
        ok += 1

    with tempfile.TemporaryDirectory() as d:
        g = Garden(Path(d) / 'trip-markers')
        check(g.ensure()['planted'] == ['substances.json', 'settings.json'], 'first run plants both files')
        check(json.loads(g.substances_path.read_text()) == SUBSTANCES_DEFAULT, 'table is exactly the contract')
        g.substances_path.write_text(g.substances_path.read_text().replace('"mushies"', '"shrooms"'))
        check(g.ensure()['planted'] == [], 'second run plants nothing')
        check('shrooms' in g.substances_path.read_text(), 'her hand-tuning survives')
        TEST_TABLE = {**SUBSTANCES_DEFAULT,
                      'tea': {'label': 'tea', 'emoji': '🍵', 'dose_unit': 'cups', 'duration_h': [2, 4]}}
        g.substances_path.write_text(json.dumps(TEST_TABLE))
        T, S = g.table(), g.settings()

        def dur(x):
            return profile('lsd', x, T, S)['duration_h']

        check(dur(20) == 12 and dur(50) == 12 and dur(175) == 16 and dur(300) == 20, 'lsd curve below/at/between')
        check(dur(500) == 24 and dur(900) == 24, 'lsd curve held flat beyond the last point')
        check(profile('lsd', '300µg', T, S)['integration_from'] == 0.75, 'integration_from defaults below 500')
        check(profile('lsd', 400, T, S)['integration_from'] == 0.875, 'integration_from interpolates')
        check(profile('lsd', 650, T, S)['integration_from'] == 1.0, 'integration_from from 500 µg')
        check(profile('tea', '2', T, S)['duration_h'] == 3, 'range → its middle')
        check(profile('mushrooms', '3,5 g', T, S)['duration_h'] == 6, 'mushies ≤ 3.5 g hold 6 h')
        check(profile('mushrooms', 4.25, T, S)['duration_h'] == 7 and profile('mushrooms', 9, T, S)['duration_h'] == 8,
              'mushies curve between and flat beyond')
        check(profile('mushrooms', 5, T, S)['tier']['label'] == 'heroic dose', 'heroic from 5 g')
        check(profile('mushrooms', 7, T, S)['tier']['label'] == 'goddess ascension', 'goddess from 7 g')
        p_pe = profile('mushrooms', 4, T, S, 'pe')
        check(p_pe['dose_eff'] == 4 and p_pe['duration_h'] == profile('mushrooms', 4, T, S)['duration_h']
              and p_pe['strain']['note'], 'a null-potency strain is a note only')
        check(profile('mushrooms', 4, T, S)['strain']['key'] == 'b+', 'no strain → the row default')
        T2 = json.loads(json.dumps(T))
        T2['mushrooms']['strains']['pe'].update(potency=1.4, duration_x=1.25)
        p2 = profile('mushrooms', 4, T2, S, 'pe')
        check(abs(p2['dose_eff'] - 5.6) < 1e-9 and p2['duration_h'] == 10, 'potency feeds the curve, duration_x stretches')
        check(p2['tier']['label'] == 'heroic dose', 'tiers read the potent dose')
        check(profile('lsd', 49, T, S)['tier'] is None, 'no tier below the first')
        check(profile('lsd', 300, T, S)['tier']['label'] == 'intense', 'tier at its threshold')
        check(profile('lsd', None, T, S)['duration_h'] is None, 'unknown dose → no invented end')

        t0 = 1_000_000_000
        r = write(g, {'kind': 'status.start', 'via': 'owui', 'substance': 'lsd', 'dose': '300', 'taken_at': t0}, now=t0)
        lsd = r['id']
        v, w = settle(g, t0 + H)
        n = now_view(v, t0 + H)
        check(n['status']['phase'] == 'active' and n['integration'] is None and not w, 'hour one: active, quiet log')
        check(n['status']['ends_at'] == t0 + 20 * H, 'ends_at = taken_at + 20 h')
        v, w = settle(g, t0 + 16 * H)
        check([e['kind'] for e in w] == ['integration.start'] and w[0]['at'] == t0 + 15 * H, 'integration opens at 15 h')
        check(w[0]['id'] == anchor_id(lsd), 'auto integration.start is the status anchor')
        n = now_view(v, t0 + 16 * H)
        check(n['status']['phase'] == 'active' and n['integration']['id'] == anchor_id(lsd), 'overlap: active + integration')
        check(settle(g, t0 + 17 * H)[1] == [], 'a boundary is written only once')
        v, w = settle(g, t0 + 21 * H)
        check([(e['kind'], e.get('reason')) for e in w] == [('status.end', 'auto')], 'auto status.end')
        n = now_view(v, t0 + 21 * H)
        check(n['status'] is None and n['integration']['closes_at'] == t0 + 92 * H, 'chip clears, integration +72 h')
        v, w = settle(g, t0 + 93 * H)
        check([e['kind'] for e in w] == ['integration.end'] and w[0]['ref'] == anchor_id(lsd), 'auto integration.end')
        n = now_view(v, t0 + 93 * H)
        check(n['status'] is None and n['integration'] is None, 'all quiet after')
        check(n['last_dose'] == {'lsd': '300'}, 'last dose remembered for a one-tap repeat')

        # amend: dose 300 → 500 recomputes the end and moves integration to the very end
        t1 = t0 + 200 * H
        s2 = write(g, {'kind': 'status.start', 'via': 'phone', 'substance': 'lsd', 'dose': '300', 'taken_at': t1}, now=t1)['id']
        write(g, {'kind': 'amend', 'via': 'phone', 'ref': s2, 'fields': {'dose': '500'}, 'reason': 'misread the blotter'}, now=t1 + H)
        last = g.lines()[0][-1]
        check(last['fields'] == {'dose': '500', 'ends_at': t1 + 24 * H}, 'amend carries the recomputed end')
        tl = build(g).status_timeline(build(g).events[s2])
        check(tl['ends_at'] == t1 + 24 * H and tl['integration']['opens_at'] == t1 + 24 * H, 'integration_from 1.0 at 500')
        check(tl['tier']['label'].startswith('goddess') and tl['amended'], 'tier follows the amended dose')
        check(len([e for e in g.lines()[0] if e['id'] == s2]) == 1, 'the original line is never rewritten')

        # manual end wins early, integration opens at once
        write(g, {'kind': 'status.end', 'via': 'owui', 'ref': s2}, now=t1 + 5 * H)
        v, w = settle(g, t1 + 6 * H)
        n = now_view(v, t1 + 6 * H)
        check(n['status'] is None and n['integration']['opens_at'] == t1 + 5 * H, 'manual end → integration now')
        check(n['integration']['closes_at'] == t1 + 77 * H, 'closes 72 h after the manual end')
        check(not [e for e in w if e['kind'] == 'status.end'], 'no auto end after a manual one')
        write(g, {'kind': 'integration.end', 'via': 'owui', 'ref': n['integration']['id']}, now=t1 + 30 * H)
        v, w = settle(g, t1 + 100 * H)
        check(now_view(v, t1 + 30 * H + 1)['integration'] is None, 'manual integration close wins')
        check(not w, 'nothing left to auto-write after manual closes')

        # a voided manual end: the status resumes, and its real end is still written later
        t5 = t0 + 300 * H
        s5 = write(g, {'kind': 'status.start', 'via': 'owui', 'substance': 'mushrooms', 'dose': '1g', 'taken_at': t5}, now=t5)['id']
        e5 = write(g, {'kind': 'status.end', 'via': 'owui', 'ref': s5}, now=t5 + H)['id']
        write(g, {'kind': 'void', 'via': 'owui', 'ref': e5, 'reason': 'tapped by accident'}, now=t5 + H + 60)
        check(now_view(settle(g, t5 + 2 * H)[0], t5 + 2 * H)['status']['id'] == s5, 'voided end → status resumes')
        w = settle(g, t5 + 8 * H)[1]
        check(('status.end', 'auto') in [(e['kind'], e.get('reason')) for e in w], 'its real end still lands')
        auto_end = next(e for e in w if e['kind'] == 'status.end')
        write(g, {'kind': 'void', 'via': 'hand', 'ref': auto_end['id']}, now=t5 + 9 * H)
        check(not [e for e in settle(g, t5 + 10 * H)[1] if e['kind'] == 'status.end'], 'a hand-voided auto line never returns')

        # void: it never happened
        t2 = t0 + 400 * H
        s3 = write(g, {'kind': 'status.start', 'via': 'owui', 'substance': 'mushrooms', 'dose': '2g', 'taken_at': t2}, now=t2)['id']
        n = now_view(settle(g, t2 + H)[0], t2 + H)
        check(n['status']['phase'] == 'peak' and n['status']['emoji'] == '🍄', 'mushies peak in the first 3 h')
        check(now_view(build(g), t2 + 4 * H)['status']['phase'] == 'active', 'then active')
        write(g, {'kind': 'void', 'via': 'owui', 'ref': s3, 'reason': 'test'}, now=t2 + 2 * H)
        v, w = settle(g, t2 + 200 * H)
        check(now_view(v, t2 + 3 * H)['status'] is None and not w, 'a voided status writes nothing, shows nothing')
        check(any(e['id'] == s3 for e in g.lines()[0]), 'voided lines are kept')

        # hand-opened window closes itself after manual_integration_h
        t3 = t0 + 700 * H
        m = write(g, {'kind': 'integration.start', 'via': 'owui', 'label': 'sound bath'}, now=t3)['id']
        check(now_view(build(g), t3 + H)['integration']['id'] == m, 'manual window open')
        v, w = settle(g, t3 + 73 * H)
        check([e['ref'] for e in w] == [m], 'manual window auto-closes at +72 h')

        # a curve substance refuses a start (or an amend) without a dose number
        t4 = t0 + 900 * H
        for bad in ({'kind': 'status.start', 'via': 'owui', 'substance': 'lsd', 'dose': None, 'taken_at': t4},
                    {'kind': 'status.start', 'via': 'owui', 'substance': 'lsd', 'dose': 'a tab', 'taken_at': t4},
                    {'kind': 'amend', 'via': 'owui', 'ref': s2, 'fields': {'dose': None}}):
            try:
                write(g, bad, now=t4)
                check(False, 'curve without a dose should be refused')
            except MarkerError as e:
                check('scales with its dose' in str(e), 'the refusal says why')
        check(write(g, {'kind': 'status.start', 'via': 'owui', 'substance': 'tea', 'dose': None, 'taken_at': t4 - 99 * H}, now=t4 - 99 * H)['id'],
              'a range substance still accepts an unknown dose')
        settle(g, t4)  # let that tea window write its own story before the next check
        # a hand-written line with no dose still reads honestly: no invented end, nothing auto-written
        g.append([{'id': str(uuid.uuid4()), 'kind': 'status.start', 'at': t4, 'written_at': t4, 'via': 'hand',
                   'temp': False, 'substance': 'lsd', 'dose': None, 'taken_at': t4, 'ends_at': None, 'note': None}])
        v, w = settle(g, t4 + 500 * H)
        n = now_view(v, t4 + 500 * H)
        check(n['status']['phase'] == 'active' and n['status']['why_no_end'], 'unknown dose stays active, says why')
        check(not w, 'and writes no boundary it cannot know')

        # refusals
        for bad, why in (({'kind': 'climax', 'via': 'owui', 'temp': True, 'chat_id': 'x', 'message_id': 'y'}, 'temp climax'),
                         ({'kind': 'status.end', 'via': 'owui', 'ref': 'nope'}, 'unknown ref'),
                         ({'kind': 'status.start', 'via': 'auto', 'substance': 'lsd'}, 'auto from a client'),
                         ({'kind': 'status.start', 'via': 'owui', 'substance': 'lsd', 'duration_h': 3}, 'duration on a table substance'),
                         ({'kind': 'amend', 'via': 'owui', 'ref': s2, 'fields': {'kind': 'void'}}, 'amend identity')):
            try:
                write(g, bad, now=t4 + 501 * H)
                check(False, f'should refuse: {why}')
            except MarkerError:
                ok += 1

        # 1.2 · strains stored explicitly, mutation never shortens, purge may close early
        t6 = t0 + 1200 * H
        m6 = write(g, {'kind': 'status.start', 'via': 'phone', 'substance': 'mushrooms', 'dose': '3', 'taken_at': t6}, now=t6)['id']
        check(build(g).events[m6]['strain'] == 'b+', 'the default strain is written, not implied')
        check(now_view(settle(g, t6 + H)[0], t6 + H)['status']['end'] == t6 + 6 * H, 'mushies 3 g → 6 h')
        w = settle(g, t6 + 6 * H + 60)[1]
        check(('status.end', t6 + 6 * H) in [(e['kind'], e['at']) for e in w], 'auto end at 6 h')
        mu = write(g, {'kind': 'mutation', 'via': 'phone', 'ref': m6, 'note': None}, now=t6 + 7 * H)['id']
        n = now_view(settle(g, t6 + 7 * H)[0], t6 + 7 * H)
        check(n['status'] and n['status']['end'] == t6 + 12 * H and n['status']['mutated']['id'] == mu,
              '👽 monsters declared → on until taken + 12 h, even after an auto end')
        check(not n['status']['can_mutate'] and n['status']['can_purge'], 'one mutation; purge still offered')
        w = settle(g, t6 + 12 * H + 60)[1]
        check(('status.end', t6 + 12 * H) in [(e['kind'], e['at']) for e in w], 'the moved boundary gets its own line')
        write(g, {'kind': 'void', 'via': 'phone', 'ref': mu, 'reason': 'test'}, now=t6 + 13 * H)
        check(build(g).status_timeline(build(g).events[m6])['end'] == t6 + 6 * H, 'a void undoes the mutation')
        t7 = t0 + 1300 * H
        m7 = write(g, {'kind': 'status.start', 'via': 'phone', 'substance': 'mushrooms', 'dose': '5', 'strain': 'pe', 'taken_at': t7}, now=t7)['id']
        check(build(g).events[m7]['strain'] == 'pe', 'a chosen strain is kept')
        write(g, {'kind': 'purge', 'via': 'phone', 'ref': m7}, now=t7 + 3 * H)
        tl = build(g).status_timeline(build(g).events[m7])
        check(tl['end'] == t7 + int(5.5 * H) and tl['integration']['opens_at'] <= tl['end'], 'purge → end at +2.5 h, integration open by then')
        check(phase_at(tl, t7 + 6 * H) == 'integration', 'and integration carries on from there')
        write(g, {'kind': 'mutation', 'via': 'phone', 'ref': m7}, now=t7 + 4 * H)
        check(build(g).status_timeline(build(g).events[m7])['end'] == t7 + 12 * H, 'a mutation after a purge extends again (time order)')
        for bad in ({'kind': 'purge', 'via': 'owui', 'ref': s2},
                    {'kind': 'mutation', 'via': 'owui', 'ref': s2},
                    {'kind': 'status.start', 'via': 'owui', 'substance': 'mushrooms', 'dose': '3', 'strain': 'nope'},
                    {'kind': 'status.start', 'via': 'owui', 'substance': 'lsd', 'dose': '100', 'strain': 'pe'}):
            try:
                write(g, bad, now=t7 + 5 * H)
                check(False, f'should refuse {bad}')
            except MarkerError:
                ok += 1
        am = write(g, {'kind': 'amend', 'via': 'phone', 'ref': m6, 'fields': {'strain': 'enigma'}}, now=t7 + 6 * H)
        check(g.lines()[0][-1]['fields'].get('strain') == 'enigma', 'strain is amendable')

        # 1.1 · harvests: due once a window is over, written once per (ref, part), void = again
        due = harvests_due(build(g), t0 + 100 * H)
        first = [d for d in due if d['ref'] == lsd]
        check([d['part'] for d in first] == ['trip', 'integration'], 'both parts of the first trip are due')
        check(first[0]['from'] == t0 and first[0]['to'] == t0 + 20 * H, 'trip window = taken_at → end')
        check(first[0]['folder'].endswith('/trip') and first[0]['title'].startswith('🌈 lsd · '), 'folder from the title')
        r1 = record_harvest(g, lsd, 'trip', first[0]['folder'], 3, 41, first[0]['window'], owui_folder='f-1',
                            moved=[{'chat_id': 'c1', 'prev_folder': None, 'prev_pinned': True},
                                   {'chat_id': 'c2', 'prev_folder': 'f-0', 'prev_pinned': False}], now=t0 + 100 * H)
        hl = harvest_line(build(g), lsd, 'trip')
        check(hl['owui_folder'] == 'f-1' and hl['moved'][0] == {'chat_id': 'c1', 'prev_folder': None, 'prev_pinned': True},
              'the line keeps every move, so OWUI can undo it')
        r2 = record_harvest(g, lsd, 'trip', first[0]['folder'], 3, 41, first[0]['window'], now=t0 + 100 * H)
        check(not r1['already'] and r2['already'] and r2['id'] == r1['id'], 'the guard: a second noticer writes nothing')
        check([d['part'] for d in harvests_due(build(g), t0 + 100 * H) if d['ref'] == lsd] == ['integration'], 'trip no longer due')
        check(build(g).status_timeline(build(g).events[lsd])['harvested']['trip']['id'] == r1['id'], 'the timeline knows')
        write(g, {'kind': 'void', 'via': 'hand', 'ref': r1['id'], 'reason': 'again please'}, now=t0 + 101 * H)
        check([d['part'] for d in harvests_due(build(g), t0 + 101 * H) if d['ref'] == lsd] == ['trip', 'integration'],
              'a voided harvest is due again')
        for bad in ({'kind': 'harvest', 'via': 'owui', 'ref': lsd, 'part': 'trip', 'folder': 'x/trip', 'chats': 1, 'messages': 1, 'window': [1, 2]},
                    {'kind': 'harvest', 'via': 'ledger', 'ref': lsd, 'part': 'trip', 'folder': 'x/trip', 'chats': 1, 'messages': 1},
                    {'kind': 'harvest', 'via': 'ledger', 'ref': lsd, 'part': 'trip', 'folder': 'x/trip', 'chats': 1, 'messages': 1, 'window': [5, 2]},
                    {'kind': 'harvest', 'via': 'ledger', 'ref': lsd, 'part': 'trip', 'folder': '../x', 'chats': 1, 'messages': 1},
                    {'kind': 'harvest', 'via': 'ledger', 'ref': lsd, 'part': 'peak', 'folder': 'x', 'chats': 1, 'messages': 1},
                    {'kind': 'harvest', 'via': 'ledger', 'ref': lsd, 'part': 'integration', 'folder': 'x', 'chats': 1,
                     'messages': 1, 'moved': [{'chat_id': 'c', 'prev_pinned': 'yes'}]}):
            try:
                write(g, bad, now=t0 + 102 * H)
                check(False, 'bad harvest should be refused')
            except MarkerError:
                ok += 1
        check(not any(d['ref'] == s3 for d in harvests_due(build(g), t2 + 900 * H)), 'a voided status is never harvested')

        # a trip that grows after its harvest is due again (lily's repro): mushies 3.5 g, trip
        # harvested at 6.2 h (0 → 6 h), 👽 at 6.5 h moves the end to 12 h and integration to 9 h
        t8 = t0 + 2000 * H
        m8 = write(g, {'kind': 'status.start', 'via': 'phone', 'substance': 'mushrooms', 'dose': '3.5', 'taken_at': t8}, now=t8)['id']
        d8 = [d for d in harvests_due(settle(g, t8 + int(6.2 * H))[0], t8 + int(6.2 * H)) if d['ref'] == m8]
        check([(d['part'], d['window'], d['version']) for d in d8] == [('trip', [t8, t8 + 6 * H], 1)], 'trip due at 6.2 h: 0 → 6 h')
        v1 = record_harvest(g, m8, 'trip', d8[0]['folder'], 2, 30, d8[0]['window'], now=t8 + int(6.2 * H))
        write(g, {'kind': 'mutation', 'via': 'phone', 'ref': m8}, now=t8 + int(6.5 * H))
        tl8 = build(g).status_timeline(build(g).events[m8])
        check(tl8['end'] == t8 + 12 * H and tl8['integration']['opens_at'] == t8 + 9 * H, 'mutation → end 12 h, integration from 9 h')
        check(not [d for d in harvests_due(build(g), t8 + 7 * H) if d['ref'] == m8], 'nothing due while the trip runs again')
        d8 = [d for d in harvests_due(settle(g, t8 + int(12.5 * H))[0], t8 + int(12.5 * H)) if d['ref'] == m8]
        check([(d['part'], d['window'], d['version'], d['redo']) for d in d8] == [('trip', [t8, t8 + 12 * H], 2, True)],
              'the grown trip is due again, 0 → 12 h (6–9 h no longer falls between the harvests)')
        check(d8[0]['folder'].endswith('/trip · v2'), 'the redo lands in <title>/trip · v2')
        v2 = record_harvest(g, m8, 'trip', d8[0]['folder'], 4, 70, d8[0]['window'], now=t8 + int(12.5 * H))
        again = record_harvest(g, m8, 'trip', d8[0]['folder'], 4, 70, d8[0]['window'], now=t8 + int(12.5 * H))
        check(not v2['already'] and again['already'] and again['id'] == v2['id'], 'guarded on (ref, part, window)')
        check(build(g).status_timeline(build(g).events[m8])['harvested']['trip']['id'] == v2['id'], 'harvested reads the latest line')
        check(v1['id'] != v2['id'] and not [d for d in harvests_due(build(g), t8 + 13 * H) if d['ref'] == m8 and d['part'] == 'trip'],
              'v1 stays in the log, the trip is settled at v2')

        # 1.1 · gather later: files first, moves in their own line, once per harvest line
        check([h['id'] for h in gathers_due(build(g)) if h['ref'] == m8] == [v1['id'], v2['id']],
              'harvests written without moves are due for a gather (v1 and v2 alike)')
        check(not [h for h in gathers_due(build(g)) if h['id'] == r1['id']], 'a voided harvest is never gathered')
        g2 = record_gather(g, v2['id'], 'f-9', moved=[{'chat_id': 'c9', 'prev_folder': None, 'prev_pinned': False}],
                           kept={'filed': 3, 'pinned': 1, 'archived': 0}, now=t8 + 13 * H)
        gl = gather_line(build(g), v2['id'])
        check(not g2['already'] and gl['ref'] == m8 and gl['part'] == 'trip' and gl['window'] == [t8, t8 + 12 * H]
              and gl['harvest'] == v2['id'] and gl['owui_folder'] == 'f-9' and gl['kept']['filed'] == 3,
              'the gather line carries the harvest line\'s own ref, part and window')
        check(record_gather(g, v2['id'], 'f-9', now=t8 + 13 * H) == {'id': g2['id'], 'already': True}, 'gathered once')
        write(g, {'kind': 'void', 'via': 'owui', 'ref': g2['id'], 'reason': 'undo'}, now=t8 + 14 * H)
        check(not [h for h in gathers_due(build(g)) if h['id'] == v2['id']], 'an undone gather is never gathered again by itself')
        check(gathers_declined(build(g)) == {m8} and not [h for h in gathers_due(build(g)) if h['ref'] == m8],
              'one undo declines the whole trip: v1 and every later version stay ungathered')
        try:
            record_gather(g, v1['id'], 'f-9', now=t8 + 14 * H)
            check(False, 'a declined trip should refuse a gather')
        except MarkerError:
            ok += 1
        ri = record_harvest(g, lsd, 'trip', first[0]['folder'] + ' · v2', 3, 41, first[0]['window'], owui_folder='f-1',
                            now=t8 + 14 * H)
        check(not ri['already'] and not [h for h in gathers_due(build(g)) if h['id'] == ri['id']],
              'a harvest that carries owui_folder (gathered inline) is never due for a gather')
        for bad in ({'kind': 'gather', 'via': 'owui', 'harvest': v1['id'], 'owui_folder': 'f'},
                    {'kind': 'gather', 'via': 'ledger', 'harvest': v1['id']},
                    {'kind': 'gather', 'via': 'ledger', 'harvest': lsd, 'owui_folder': 'f'},
                    {'kind': 'gather', 'via': 'ledger', 'harvest': v2['id'], 'owui_folder': 'f'},
                    {'kind': 'gather', 'via': 'ledger', 'harvest': v1['id'], 'owui_folder': 'f', 'kept': {'filed': -1}}):
            try:
                write(g, bad, now=t8 + 15 * H)
                check(False, 'bad gather should be refused')
            except MarkerError:
                ok += 1

        # a torn line never breaks a read
        with open(g.log, 'a') as f:
            f.write('{"torn": \n')
        st = stats(build(g), 0, t4 + 600 * H, t4 + 600 * H)
        check(st['broken_lines'] == 1, 'torn line counted')

        def numbers_only(x):
            if isinstance(x, dict):
                return all(isinstance(k, str) and numbers_only(v) for k, v in x.items())
            return isinstance(x, (int, float)) and not isinstance(x, bool) or isinstance(x, bool)

        check(numbers_only(st), 'stats are numbers only')
        check(st['counts']['status.start'] == 7 and st['counts']['void'] == 5 and st['counts']['harvest'] == 0
              and st['counts']['mutation'] == 1 and st['counts']['purge'] == 1, 'stats count the live view')
        check(st['statuses_per_tier'].get('lsd≥500') == 1, 'tiers counted by threshold, not by text')

    print(f'🌙 petal markers core · self-test · {ok} checks bloomed, none wilted')


if __name__ == '__main__':
    _self_test()
