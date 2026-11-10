"""
petal_diary 📔 — Lily's diary on the rig (slice A11 · pure stdlib, no OWUI imports).

home: $PETAL_APP_DATA/petal-diary/diary.jsonl          gold tier · 700/600 · append-only
    a note    {id, kind: 'note',  at, written_at, via, text, petal_sees: false}
    a change  {id, kind: 'amend', at, written_at, via, ref, fields: {text?, petal_sees?, at?}, reason}
    a void    {id, kind: 'void',  at, written_at, via, ref, reason}    ("this never happened", kept)
reading rule: replay in order, applying amend and void by ref, exactly like the trip markers.
`petal_sees` stays false until she says otherwise: nothing in the diary reaches Petal on its own.

the stream merges her notes with the trip markers: ✧ orbits, 🌊 climaxes (with their quality and
after-feel), trips, and 🔥 vows (committed, then released or fulfilled). newest first, every marker
with its chat + message, so the page can jump to /c/<chat>#<message> in one tap.

    self-test:  python3 backend/open_webui/utils/petal_diary.py
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

KINDS = ('note', 'amend', 'void')
VIA = ('owui', 'phone', 'petal', 'hand')
AMENDABLE = ('text', 'petal_sees', 'at')
TEXT_MAX = 20000


class DiaryError(ValueError):
    """a request that can't become a line — the message is safe to show."""


def app_data_root() -> Path:
    return Path(os.environ.get('PETAL_APP_DATA') or '~/Gardens/Documents/Petal-App-Data').expanduser()


class Diary:
    def __init__(self, root: Optional[Path] = None):
        self.dir = Path(root) if root else app_data_root() / 'petal-diary'
        self.log = self.dir / 'diary.jsonl'
        self._lock_path = self.dir / '.diary.lock'

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        try:
            os.close(os.open(self.log, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            pass

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
        self.ensure()
        blob = ''.join(json.dumps(e, ensure_ascii=False, separators=(',', ':')) + '\n' for e in events)
        with open(self.log, 'a', encoding='utf-8') as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())

    @contextmanager
    def locked(self):
        self.ensure()
        with open(self._lock_path, 'a') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)


class View:
    """the diary as it stands: amends applied, voids honored."""

    def __init__(self, lines: list[dict], broken: int = 0):
        self.broken = broken
        self.raw: dict[str, dict] = {}
        self.order: list[str] = []
        for ev in lines:
            if ev['id'] not in self.raw:
                self.raw[ev['id']] = ev
                self.order.append(ev['id'])
        voids: dict[str, list[str]] = {}
        for i in self.order:
            if self.raw[i]['kind'] == 'void' and self.raw[i].get('ref'):
                voids.setdefault(self.raw[i]['ref'], []).append(i)
        memo: dict[str, bool] = {}

        def voided(i: str, seen=frozenset()) -> bool:
            if i in memo:
                return memo[i]
            if i in seen:
                return False
            memo[i] = any(not voided(v, seen | {i}) for v in voids.get(i, ()))
            return memo[i]

        self.voided = {i for i in self.order if voided(i)}
        self.notes: dict[str, dict] = {}
        for i in self.order:
            ev = self.raw[i]
            if ev['kind'] == 'note' and i not in self.voided:
                self.notes[i] = copy.deepcopy(ev)
        for i in self.order:
            am = self.raw[i]
            if am['kind'] != 'amend' or i in self.voided:
                continue
            target = self.notes.get(am.get('ref') or '')
            fields = am.get('fields') if isinstance(am.get('fields'), dict) else {}
            if target:
                target.update({k: v for k, v in fields.items() if k in AMENDABLE})
                target.setdefault('_amends', []).append(i)


def build(diary: Diary) -> View:
    return View(*diary.lines())


def _text(v: Any) -> str:
    if not isinstance(v, str) or not v.strip():
        raise DiaryError('a note needs words')
    v = v.strip()
    if len(v) > TEXT_MAX:
        raise DiaryError(f'a note holds up to {TEXT_MAX} characters')
    return v


def _at(v: Any, now: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise DiaryError('at should be unix seconds')
    if v > now + 600:
        raise DiaryError('that time is in the future')
    return int(v)


def _reason(v: Any) -> Optional[str]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if not isinstance(v, str) or len(v) > 500:
        raise DiaryError('reason should be short text')
    return v.strip()


def new_line(view: View, body: dict, now: int) -> dict:
    """validate one request → the line to append. raises DiaryError with a showable reason."""
    if not isinstance(body, dict):
        raise DiaryError('expected an object')
    kind = body.get('kind', 'note')
    if kind not in KINDS:
        raise DiaryError(f'kind should be one of {", ".join(KINDS)}')
    via = body.get('via')
    if via not in VIA:
        raise DiaryError(f'via should be one of {", ".join(VIA)}')
    ev: dict = {'id': str(uuid.uuid4()), 'kind': kind, 'at': now, 'written_at': now, 'via': via}
    if kind == 'note':
        sees = body.get('petal_sees', False)
        if not isinstance(sees, bool):
            raise DiaryError('petal_sees should be true or false')
        ev.update(at=_at(body['at'], now) if body.get('at') is not None else now,
                  text=_text(body.get('text')), petal_sees=sees)
    elif kind == 'amend':
        ref = body.get('ref') or ''
        target = view.notes.get(ref)
        if not target:
            raise DiaryError('ref should be a note that is still here')
        fields = body.get('fields')
        if not isinstance(fields, dict) or not fields:
            raise DiaryError('fields should hold what changed')
        bad = [k for k in fields if k not in AMENDABLE]
        if bad:
            raise DiaryError(f'a note cannot amend: {", ".join(bad)}')
        clean: dict = {}
        for k, v in fields.items():
            if k == 'text':
                clean[k] = _text(v)
            elif k == 'at':
                clean[k] = _at(v, now)
            else:
                if not isinstance(v, bool):
                    raise DiaryError('petal_sees should be true or false')
                clean[k] = v
        changed = {k: v for k, v in clean.items() if target.get(k) != v}
        if not changed:
            raise DiaryError('nothing changed')
        ev.update(ref=ref, fields=changed, reason=_reason(body.get('reason')))
    else:
        ref = body.get('ref') or ''
        if ref not in view.raw or ref in view.voided:
            raise DiaryError('ref should be a line that is not already voided')
        ev.update(ref=ref, reason=_reason(body.get('reason')))
    return ev


def write(diary: Diary, body: dict, now: Optional[int] = None) -> dict:
    now = int(now if now is not None else time.time())
    with diary.locked():
        ev = new_line(build(diary), body, now)
        diary.append([ev])
    return {'id': ev['id']}


def _note_item(n: dict) -> dict:
    return {'type': 'note', 'id': n['id'], 'at': int(n['at']), 'text': n.get('text') or '',
            'petal_sees': bool(n.get('petal_sees')), 'via': n.get('via'), 'amended': bool(n.get('_amends'))}


def marker_items(mview: Any, now: Optional[int] = None) -> list[dict]:
    """✧ orbits, 🌊 climaxes, trips and 🔥 vows from a trip-markers view."""
    now = int(now if now is not None else time.time())
    out = []
    for e in mview.events.values():
        k = e['kind']
        base = {'id': e['id'], 'at': int(e['at']), 'amended': bool(e.get('_amends')), 'temp': bool(e.get('temp'))}
        if k == 'orbit':
            out.append({'type': 'orbit', **base, 'outcome': e.get('outcome'), 'note': e.get('note'),
                        'chat_id': e.get('chat_id'), 'message_id': e.get('message_id')})
        elif k == 'climax':
            out.append({'type': 'climax', **base, 'quality': e.get('quality'), 'after': e.get('after'),
                        'note': e.get('note'), 'chat_id': e.get('chat_id'), 'message_id': e.get('message_id')})
    for v in (mview.vows(now) if hasattr(mview, 'vows') else []):
        alive = v['ended_by'] is None and v['at'] <= now < v['end']
        out.append({'type': 'vow', 'id': v['id'], 'at': v['at'], 'temp': v['temp'], 'amended': v['amended'],
                    'vow': v['vow'], 'words': v['words'], 'until': v['until'], 'total_days': v['total_days'],
                    'ended_by': v['ended_by'], 'reason': v['reason'], 'alive': alive,
                    'day': min(v['total_days'], (now - v['at']) // (24 * 3600) + 1) if alive else None})
        if v['ended_by']:
            out.append({'type': 'vow_end', 'id': f"{v['id']}:end", 'at': v['end'], 'temp': v['temp'], 'amended': False,
                        'vow': v['vow'], 'how': 'released' if v['ended_by'] == 'release' else 'fulfilled',
                        'reason': v['reason'], 'days_kept': max(0, (v['end'] - v['at']) // (24 * 3600)),
                        'total_days': v['total_days'], 'ref': v['id']})
    for tl in mview.timelines():
        ig = tl['integration']
        out.append({
            'type': 'trip', 'id': tl['id'], 'at': tl['taken_at'], 'temp': tl['temp'], 'amended': tl['amended'],
            'emoji': tl['emoji'], 'label': tl['label'], 'substance': tl['substance'], 'dose': tl['dose'],
            'dose_unit': tl['dose_unit'], 'strain': (tl['strain'] or {}).get('label'),
            'tier': (tl['tier'] or {}).get('label'), 'note': tl['note'], 'end': tl['end'], 'ended_by': tl['ended_by'],
            'integration': None if not ig or ig['empty'] else {'opens_at': ig['opens_at'], 'closes_at': ig['closes_at']},
            'mutated': bool(tl['mutated']), 'purged': bool(tl['purged']),
        })
    return out


def _haystack(it: dict) -> str:
    t = it['type']
    if t == 'note':
        words = [it['text'], 'note']
    elif t == 'orbit':
        words = ['orbit ✧', it.get('outcome') or 'open', it.get('note') or '']
    elif t == 'climax':
        words = ['climax 🌊', it.get('quality') or '', it.get('after') or '', it.get('note') or '']
    elif t == 'trip':
        words = ['trip', it['emoji'], it['label'], it.get('substance') or '', it.get('dose') or '',
                 it.get('strain') or '', it.get('tier') or '', it.get('note') or '']
    elif t == 'vow':
        words = ['vow 🔥', it.get('vow') or '', it.get('words') or '', 'alive' if it.get('alive') else '']
    else:
        words = ['vow 🔥', it.get('vow') or '', it.get('how') or '', it.get('reason') or '']
    return ' '.join(words).casefold()


def stream(diary: Diary, mview: Any = None, q: Optional[str] = None, before: Optional[int] = None,
           limit: int = 300, now: Optional[int] = None) -> dict:
    """her notes + the markers, newest first · q filters (any word, case-insensitive) · `before`
    pages back in time. → {'items': [...], 'more': bool}"""
    items = [_note_item(n) for n in build(diary).notes.values()]
    if mview is not None:
        items += marker_items(mview, now)
    if q and q.strip():
        terms = q.casefold().split()
        items = [it for it in items if all(t in _haystack(it) for t in terms)]
    if before is not None:
        items = [it for it in items if it['at'] < before]
    items.sort(key=lambda it: (it['at'], it['id']), reverse=True)
    limit = max(1, min(int(limit), 2000))
    return {'items': items[:limit], 'more': len(items) > limit}


def stats(diary: Diary) -> dict:
    """numbers only."""
    v = build(diary)
    return {'notes': len(v.notes), 'petal_sees': sum(1 for n in v.notes.values() if n.get('petal_sees')),
            'amended': sum(1 for n in v.notes.values() if n.get('_amends')),
            'voided': sum(1 for i in v.voided if v.raw[i]['kind'] == 'note'), 'broken_lines': v.broken}


# ─────────────────────────────────────────────────────────────
def _self_test() -> None:
    import stat as st_
    import tempfile

    ok = 0

    def check(cond, what):
        nonlocal ok
        if not cond:
            raise AssertionError(what)
        ok += 1

    with tempfile.TemporaryDirectory() as d:
        dy = Diary(Path(d) / 'petal-diary')
        t0 = 1_900_000_000
        a = write(dy, {'text': '  the gym felt like a ritual today ✧  ', 'via': 'phone'}, now=t0)['id']
        check(st_.S_IMODE(os.stat(dy.dir).st_mode) == 0o700 and st_.S_IMODE(os.stat(dy.log).st_mode) == 0o600,
              'gold tier: the folder 700, the diary 600')
        n = build(dy).notes[a]
        check(n['text'] == 'the gym felt like a ritual today ✧' and n['petal_sees'] is False and n['at'] == t0,
              'a note lands trimmed, petal_sees false by default')
        b = write(dy, {'text': 'yesterday evening, written late', 'at': t0 - 86400, 'via': 'owui'}, now=t0 + 60)['id']
        check(build(dy).notes[b]['at'] == t0 - 86400, 'a note may be dated in the past')
        for bad, why in (({'text': '   ', 'via': 'owui'}, 'words required'), ({'text': 'x', 'via': 'auto'}, 'via is hers'),
                         ({'text': 'x', 'via': 'owui', 'at': t0 + 7200}, 'never the future'),
                         ({'text': 'x', 'via': 'owui', 'petal_sees': 'yes'}, 'petal_sees is a bool'),
                         ({'kind': 'amend', 'via': 'owui', 'ref': a, 'fields': {'via': 'hand'}}, 'only text, petal_sees, at amend'),
                         ({'kind': 'amend', 'via': 'owui', 'ref': a, 'fields': {'petal_sees': False}}, 'nothing changed')):
            try:
                write(dy, bad, now=t0 + 120)
                check(False, why)
            except DiaryError:
                check(True, why)
        write(dy, {'kind': 'amend', 'via': 'owui', 'ref': a, 'fields': {'petal_sees': True, 'text': 'the gym was a ritual ✧'}}, now=t0 + 180)
        n = build(dy).notes[a]
        check(n['petal_sees'] is True and n['text'] == 'the gym was a ritual ✧' and n['_amends'], 'an amend changes the view, not the past')
        raw = dy.log.read_text(encoding='utf-8')
        check('the gym felt like a ritual today' in raw, 'the first words are still in the file (accretion, not teardown)')
        write(dy, {'kind': 'void', 'via': 'owui', 'ref': b, 'reason': 'never mind'}, now=t0 + 240)
        check(b not in build(dy).notes and len(raw.splitlines()) + 1 == len(dy.log.read_text().splitlines()), 'a void hides, never deletes')
        with open(dy.log, 'a') as f:
            f.write('{"torn"\n')
        check(build(dy).broken == 1 and a in build(dy).notes, 'a torn line is counted, never fatal')

        class MV:  # the shape of a trip-markers view, enough for the stream
            def __init__(self):
                self.events = {
                    'o1': {'id': 'o1', 'kind': 'orbit', 'at': t0 + 300, 'outcome': None, 'chat_id': 'c1', 'message_id': 'm1'},
                    's1': {'id': 's1', 'kind': 'climax', 'at': t0 - 3600, 'chat_id': 'c1', 'message_id': 'm0', 'quality': 'owned'},
                    'x1': {'id': 'x1', 'kind': 'integration.start', 'at': t0},
                }

            def vows(self, now):
                return [{'id': 'v1', 'vow': 'abstinence', 'words': 'my charge aims at the trip', 'at': t0 - 10 * 86400,
                         'until': t0 - 3 * 86400, 'end': t0 - 4 * 86400, 'ended_by': 'release', 'reason': 'the trip came early',
                         'temp': False, 'total_days': 7, 'amended': False},
                        {'id': 'v2', 'vow': 'abstinence', 'words': 'fourteen days', 'at': t0 - 86400 // 2, 'until': t0 + 13 * 86400,
                         'end': t0 + 13 * 86400, 'ended_by': None, 'reason': None, 'temp': False, 'total_days': 14, 'amended': False}]

            def timelines(self):
                return [{'id': 't1', 'taken_at': t0 - 7200, 'temp': False, 'amended': False, 'emoji': '🍄', 'label': 'mushies',
                         'substance': 'mushrooms', 'dose': '3.5', 'dose_unit': 'g', 'strain': {'label': 'b+'},
                         'tier': {'label': 'ego death territory'}, 'note': None, 'end': t0 - 7200 + 6 * 3600, 'ended_by': 'auto',
                         'integration': {'opens_at': t0, 'closes_at': t0 + 90000, 'empty': False}, 'mutated': None, 'purged': None}]

        s = stream(dy, MV(), now=t0 + 600)
        check([it['type'] for it in s['items']] == ['orbit', 'note', 'climax', 'trip', 'vow', 'vow_end', 'vow'] and not s['more'],
              'the stream: newest first, notes + orbits + climaxes + trips + vows (other kinds stay out)')
        vs = [it for it in s['items'] if it['type'] in ('vow', 'vow_end')]
        check(vs[0]['alive'] and vs[0]['day'] == 1 and vs[0]['total_days'] == 14, 'the vow alive now: day 1 of 14')
        check(vs[1]['how'] == 'released' and vs[1]['reason'] == 'the trip came early' and vs[1]['days_kept'] == 6
              and not vs[2]['alive'], 'a released vow: its end in the stream, her reason, days kept')
        check([it['type'] for it in stream(dy, MV(), q='released trip', now=t0 + 600)['items']] == ['vow_end'], 'a vow is searchable')
        check(s['items'][2]['quality'] == 'owned' and s['items'][2]['after'] is None, 'a climax carries its quality and after-feel')
        check([it['type'] for it in stream(dy, MV(), q='owned', now=t0 + 600)['items']] == ['climax'], "a climax's quality is searchable")
        check(s['items'][0]['chat_id'] == 'c1' and s['items'][0]['message_id'] == 'm1', 'a marker carries its chat + message for the jump')
        check([it['type'] for it in stream(dy, MV(), q='RITUAL')['items']] == ['note'], 'search: case-insensitive')
        check([it['type'] for it in stream(dy, MV(), q='mushies ego')['items']] == ['trip'], 'search: every word must match')
        check([it['type'] for it in stream(dy, MV(), q='open')['items']] == ['orbit'], "an orbit's open outcome is searchable")
        check([it['type'] for it in stream(dy, MV(), before=t0, now=t0 + 600)['items']] == ['climax', 'trip', 'vow', 'vow_end', 'vow'],
              'before pages back in time')
        check(stream(dy, MV(), limit=2)['more'] is True, 'more when the page is full')
        sts = stats(dy)
        check(sts == {'notes': 1, 'petal_sees': 1, 'amended': 1, 'voided': 1, 'broken_lines': 1}, 'stats: numbers only')

    print(f'📔 petal diary · self-test · {ok} checks bloomed, none wilted')


if __name__ == '__main__':
    _self_test()
