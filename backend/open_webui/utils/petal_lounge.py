"""🌊 Petal Stream (slice A41) · the lounge: Petal speaks on her own, in a chat opened to it.

the core, stdlib only (its tests load it without a server). the door is routers/petal_lounge.py.
not the voice's growing stream (routers/audio/petal_stream.py): that one reads her words aloud, and it is
how a stream message is voiced.

  · her profiles · md files in Petal-App-Data/petal-open-webui/stream/<name>.md (hers, never in the repo):
    a little frontmatter (length · mean · spread · quiet · voice · typing · turns · place · tide …), then her
    words. the three demos (lounge · affirmations · sing) live in petal_stream_demos/ and reach her folder
    only when she asks for them (plant): nothing plants on its own
  · the rhythm · each gap is drawn the spiral way her other rhythms draw theirs (contracts ch11): a keyed
    uniform (HMAC-SHA256) → an exponential around her mean (spread 1 is that pure draw, 0 a steady beat) →
    a zero-mean tilt toward a key-derived spiral of two arms, read at the local phase of the gap's start and
    turned once per ring of 69 draws. the key is the stream's own (stream-rhythm.key beside her folder, or
    $PETAL_STREAM_KEY_FILE): only a 12-hex fingerprint ever travels
  · the slots · facts only, never a sentence of instruction (ANA-TONE): {{since_last_spoke}}
    {{since_she_wrote}} {{local_time}} {{her_date}} {{user}} {{min_words}} {{max_words}} {{in_a_row}}
    {{typing}} {{profile}}. a line whose fact is empty right now stays unsaid; a line holding an unknown
    slot is skipped and named; her card (with the chat's own system prompt, when it has one) is a part code
    places on top, which her words may place themselves ({{part:card}}) or decline ({{part:card|none}})
  · the state · which chats are open to her stream: saved chats in stream.json (600), temporary chats in
    memory only (contract 0). a numbers-only line per utterance in stream-spoken.jsonl (saved chats only:
    when, the draw, the gap, the fingerprint, the profile's name, a word count; never a chat id, never words)
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib.util
import json
import math
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

CALLER = 'petal-open-webui/stream'  # utils/headers.py names the worker at the wellspring
STAMP = 'petal_stream'  # top level on the message, never in meta: {profile, at, gap}
DEMOS_DIR = Path(__file__).with_name('petal_stream_demos')
DEMOS = ('lounge', 'affirmations', 'sing')

GRID = 256  # the tilted inverse CDF's resolution
TILT = 0.35  # the spiral's tilt (ch11's value)
RING = 69  # draws per turn of the spiral
MIN_RATIO = 3 / 69  # a gap's floor as a share of her mean (the 3 of her 69)
MAX_RATIO = 345 / 69  # its ceiling: five means
DAY_MIN = 1440.0

DEFAULTS = {  # numbers and switches only: a profile's words are never defaulted
    'length': (6, 40),
    'mean': 9.0,
    'spread': 1.0,
    'tide': DAY_MIN,
    'voice': 'on',
    'typing': ('wait', 12.0),
    'turns': 16,
    'place': 'end',
}
VOICES = ('on', 'off', 'always')
PLACES = ('end', 'system')
NAME_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _.-]{0,47}$')
FACTS = (
    'since_last_spoke',
    'since_she_wrote',
    'local_time',
    'her_date',
    'user',
    'min_words',
    'max_words',
    'in_a_row',
    'typing',
    'profile',
)
ALIASES = {'USER_NAME': 'user'}  # §11.10: an older spelling still speaks


# ── where her things live ─────────────────────────────────────────────────────────────────────────────
def app_data() -> Path:
    return Path(os.environ.get('PETAL_APP_DATA') or '~/Gardens/Documents/Petal-App-Data').expanduser()


def home() -> Path:
    return app_data() / 'petal-open-webui'


def profiles_dir() -> Path:
    return home() / 'stream'


def state_path() -> Path:
    return home() / 'stream.json'


def spoken_path() -> Path:
    return home() / 'stream-spoken.jsonl'


def _ready(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _write_private(p: Path, text: str) -> None:
    """atomic, 600, its folder 700"""
    _ready(p.parent)
    tmp = p.with_name(f'.{p.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


# ── durations, times, quiet hours ─────────────────────────────────────────────────────────────────────
_DUR = re.compile(
    r'^\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)?\s*$', re.I
)
_UNIT_MIN = {'s': 1 / 60, 'm': 1.0, 'h': 60.0, 'd': DAY_MIN}


def minutes_of(text) -> float | None:
    """'90s' · '7m' · '7 min' · '1.5h' · '1d' · '7' (minutes) → minutes, or None"""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text) if text >= 0 else None
    m = _DUR.match(str(text or ''))
    if not m:
        return None
    unit = (m.group(2) or 'm').lower()
    unit = 'm' if unit.startswith('mi') else unit[0]
    return float(m.group(1)) * _UNIT_MIN[unit]


_CLOCK = re.compile(r'^\s*(\d{1,2})(?::(\d{2}))?\s*$')


def _clock_min(text: str) -> int | None:
    m = _CLOCK.match(text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 24 or mi > 59 or (h == 24 and mi):
        return None
    return (h * 60 + mi) % 1440


def quiet_of(text) -> tuple[list, list]:
    """'23:30-09:30, 13:00-14:00' → ([(start_min, end_min)], problems) · 'none' or empty → no quiet hours"""
    s = str(text or '').strip()
    if not s or s.lower() in ('none', 'no', 'off', '-'):
        return [], []
    windows, problems = [], []
    for part in re.split(r'[,;]', s):
        part = part.strip()
        if not part:
            continue
        bits = re.split(r'\s*(?:-|–|—|to)\s*', part)
        a = _clock_min(bits[0]) if len(bits) == 2 else None
        b = _clock_min(bits[1]) if len(bits) == 2 else None
        if a is None or b is None or a == b:
            problems.append(f'quiet: "{part}" is not a window like 23:30-09:30')
            continue
        windows.append((a, b))
    return windows, problems


def _local(t: float) -> datetime:
    return datetime.fromtimestamp(t).astimezone()


def quiet_end(t: float, windows: list) -> float | None:
    """the moment the quiet window holding t ends (None: t is not inside one)"""
    if not windows:
        return None
    d = _local(t)
    mins = d.hour * 60 + d.minute + d.second / 60 + d.microsecond / 6e7
    midnight = d.replace(hour=0, minute=0, second=0, microsecond=0)
    for a, b in windows:
        if a < b and a <= mins < b:
            return (midnight + timedelta(minutes=b)).timestamp()
        if a > b and (mins >= a or mins < b):  # the window wraps past midnight
            day = midnight + timedelta(days=1) if mins >= a else midnight
            return (day + timedelta(minutes=b)).timestamp()
    return None


def since(seconds: float | None) -> str:
    """a fact in plain units: '42 seconds' · '7 minutes' · '3 hours 10 minutes' · '2 days 4 hours' · '' unknown"""
    if seconds is None or seconds != seconds or seconds < 0:
        return ''
    s = int(round(seconds))

    def unit(n, word):
        return f'{n} {word}' + ('' if n == 1 else 's')

    if s < 60:
        return unit(s, 'second')
    m = s // 60
    if m < 60:
        return unit(m, 'minute')
    h, m = divmod(m, 60)
    if h < 24:
        return unit(h, 'hour') + (f' {unit(m, "minute")}' if m else '')
    d, h = divmod(h, 24)
    return unit(d, 'day') + (f' {unit(h, "hour")}' if h else '')


def local_time(t: float, hidden: bool) -> str:
    """'21:14', or '' while the forge keeps the hour away"""
    return '' if hidden else _local(t).strftime('%H:%M')


_TURN_MEMO: dict = {'key': None, 'turn': None}


def day_turn() -> tuple[int, int]:
    """her day's turn: petal_names.TURN by path ($PETAL_NAMES_PY) when it can be read, else 05:00"""
    path = os.environ.get('PETAL_NAMES_PY')
    if path:
        try:
            p = Path(path).expanduser()
            st = p.stat()
            key = (str(p), st.st_mtime_ns, st.st_size)
            if _TURN_MEMO['key'] == key and _TURN_MEMO['turn']:
                return _TURN_MEMO['turn']
            spec = importlib.util.spec_from_file_location('_petal_lounge_names', p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules['_petal_lounge_names'] = mod
            try:
                spec.loader.exec_module(mod)
            finally:
                sys.modules.pop('_petal_lounge_names', None)
            turn = _turn_of(getattr(mod, 'TURN', None))
            if turn:
                _TURN_MEMO.update(key=key, turn=turn)
                return turn
        except Exception:
            pass
    return (5, 0)


def _turn_of(v) -> tuple[int, int] | None:
    if isinstance(v, str):
        m = _clock_min(v)
        return divmod(m, 60) if m is not None else None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and 0 <= v < 24:
        return int(v), int(round((v - int(v)) * 60)) % 60
    if isinstance(v, timedelta):
        m = int(v.total_seconds() // 60) % 1440
        return divmod(m, 60)
    if hasattr(v, 'hour') and hasattr(v, 'minute'):
        return int(v.hour), int(v.minute)
    return None


def her_date(t: float, turn: tuple[int, int] | None = None) -> str:
    """'sun nov 23' · the day turns at her day's turn (a late night belongs to the evening it grew from)"""
    h, m = turn or day_turn()
    d = _local(t) - timedelta(hours=h, minutes=m)
    return f'{d.strftime("%a").lower()} {d.strftime("%b").lower()} {d.day}'


# ── her names in time (§11.4c): today's name, or 'her' ────────────────────────────────────────────────
def names_path() -> Path:
    return Path(os.environ.get('PETAL_NAMES_JSON') or app_data() / 'petal-anamnesis-ii' / 'names.json').expanduser()


_DATE = re.compile(r'^(\d{4})(?:-(\d{2})(?:-(\d{2})(?:T(\d{2}):(\d{2}))?)?)?$')


def _span(text, turn, end: bool) -> float | None:
    """a day, a month, a year or a moment → its first moment (end=False) or the moment after it (end=True);
    a day-dated edge sits at her day's turn"""
    m = _DATE.match(str(text or '').strip())
    if not m:
        return None
    y, mo, d, hh, mi = m.groups()
    try:
        if hh is not None:
            return datetime(int(y), int(mo), int(d), int(hh), int(mi)).astimezone().timestamp()
        th, tm = turn
        if d is not None:
            day = datetime(int(y), int(mo), int(d), th, tm)
            return (day + timedelta(days=1) if end else day).astimezone().timestamp()
        if mo is not None:
            first = datetime(int(y), int(mo), 1, th, tm)
            if end:
                first = datetime(int(y) + (int(mo) == 12), int(mo) % 12 + 1, 1, th, tm)
            return first.astimezone().timestamp()
        return datetime(int(y) + (1 if end else 0), 1, 1, th, tm).astimezone().timestamp()
    except ValueError:
        return None


def today_name(t: float | None = None) -> str:
    """the name true now, read from names.json (read-only, never logged) · an overlap, a broken file or no
    file at all → 'her'"""
    try:
        doc = json.loads(names_path().read_text(encoding='utf-8'))
    except Exception:
        return 'her'
    entries = doc.get('self') if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return 'her'
    turn = day_turn()
    spans = []
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get('name'), str) or not e['name'].strip():
            return 'her'
        a = _span(e.get('from'), turn, end=False)
        b = _span(e.get('to'), turn, end=True) if e.get('to') else math.inf
        if a is None or b is None or b <= a:
            return 'her'
        spans.append((a, b, e['name'].strip()))
    spans.sort()
    for (a1, b1, _), (a2, _b2, _n) in zip(spans, spans[1:]):
        if b1 > a2:  # a day belongs to one name: an overlap makes the whole file read as absent
            return 'her'
    now = time.time() if t is None else t
    for a, b, name in spans:
        if a <= now < b:
            return name
    return 'her'


# ── her profiles ──────────────────────────────────────────────────────────────────────────────────────
_FRONT = re.compile(r'\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)', re.S)
_COMMENTS = re.compile(r'<!--.*?-->', re.S)


def _front(text: str) -> tuple[dict, str]:
    m = _FRONT.match(text)
    if not m:
        return {}, text
    keys = {}
    for line in m.group(1).splitlines():
        line = line.split(' #', 1)[0].rstrip() if not line.lstrip().startswith('#') else ''
        if not line.strip() or ':' not in line:
            continue
        k, v = line.split(':', 1)
        keys[k.strip().lower()] = v.strip().strip('"').strip("'")
    return keys, text[m.end():]


def parse(text: str, name: str) -> dict:
    """one profile, read from her md · knobs that don't read fall back to the default and are named"""
    keys, body = _front(text or '')
    problems: list[str] = []
    p: dict = {'name': name, 'title': keys.get('title') or name, 'emoji': keys.get('emoji') or '🌊'}

    lo, hi = DEFAULTS['length']
    if 'length' in keys:
        m = re.match(r'^\s*(\d+)\s*(?:-|–|—|to)\s*(\d+)\s*(?:words?)?\s*$', keys['length'], re.I)
        if m and 0 < int(m.group(1)) <= int(m.group(2)):
            lo, hi = int(m.group(1)), int(m.group(2))
        else:
            problems.append('length: write it as 6-40 (words)')
    p['length'] = (lo, hi)

    mean = minutes_of(keys['mean']) if 'mean' in keys else DEFAULTS['mean']
    if mean is None or mean <= 0:
        problems.append('mean: write it as 7m, 90s or 2h')
        mean = DEFAULTS['mean']
    spread = DEFAULTS['spread']
    if 'spread' in keys:
        try:
            spread = float(keys['spread'])
            if not 0 <= spread <= 1:
                raise ValueError
        except ValueError:
            problems.append('spread: a number from 0 (steady) to 1 (wild)')
            spread = DEFAULTS['spread']
    tide = minutes_of(keys['tide']) if 'tide' in keys else DEFAULTS['tide']
    if tide is None or tide <= 0:
        problems.append('tide: write it as 1d, 6h or 60m')
        tide = DEFAULTS['tide']
    lo_gap, hi_gap = mean * MIN_RATIO, mean * MAX_RATIO
    for k in ('min', 'max'):
        if k in keys:
            v = minutes_of(keys[k])
            if v is None:
                problems.append(f'{k}: write it as 30s, 5m or 1h')
            elif k == 'min':
                lo_gap = v
            else:
                hi_gap = v
    if hi_gap < lo_gap:
        problems.append('max is below min: both set back')
        lo_gap, hi_gap = mean * MIN_RATIO, mean * MAX_RATIO
    p['rhythm'] = {'mean': mean, 'spread': spread, 'min': lo_gap, 'max': hi_gap, 'tide': tide}

    p['quiet'], qp = quiet_of(keys.get('quiet', ''))
    problems += qp
    p['quiet_text'] = keys.get('quiet', '') if p['quiet'] else ''

    voice = (keys.get('voice') or DEFAULTS['voice']).lower()
    if voice not in VOICES:
        problems.append('voice: on · off · always')
        voice = DEFAULTS['voice']
    p['voice'] = voice

    typing = DEFAULTS['typing']
    if 'typing' in keys:
        m = re.match(r'^\s*(wait|speak)\b\s*(.*)$', keys['typing'], re.I)
        rest = minutes_of(m.group(2)) if m and m.group(2).strip() else None
        if not m or (m.group(2).strip() and rest is None):
            problems.append('typing: wait · wait 20s · speak')
        elif m.group(1).lower() == 'speak':
            typing = ('speak', 0.0)
        else:
            typing = ('wait', rest * 60 if rest is not None else DEFAULTS['typing'][1])
    p['typing'] = typing

    turns = DEFAULTS['turns']
    if 'turns' in keys:
        try:
            turns = int(keys['turns'])
            if not 0 <= turns <= 200:
                raise ValueError
        except ValueError:
            problems.append('turns: a number from 0 to 200')
            turns = DEFAULTS['turns']
    p['turns'] = turns

    place = (keys.get('place') or DEFAULTS['place']).lower()
    if place not in PLACES:
        problems.append('place: end · system')
        place = DEFAULTS['place']
    p['place'] = place

    for k, a, b in (('temperature', 0.0, 2.5), ('top_p', 0.0, 1.0)):
        p[k] = None
        if k in keys:
            try:
                v = float(keys[k])
                if not a <= v <= b:
                    raise ValueError
                p[k] = v
            except ValueError:
                problems.append(f'{k}: a number from {a:g} to {b:g}')

    words = _COMMENTS.sub('', body).strip('\n')
    p['words'] = words.strip() and words  # '' means silent: no words of hers, and none of code's either
    p['problems'] = problems
    return p


def _name_ok(name: str) -> bool:
    return bool(NAME_OK.match(name or '')) and not name.startswith('.')


def list_profiles() -> list[dict]:
    """her folder, *.md only (dotfiles and subfolders never read), by name"""
    d = profiles_dir()
    out = []
    try:
        files = sorted(d.glob('*.md'), key=lambda f: f.name.lower())
    except OSError:
        return []
    for f in files:
        name = f.stem
        if not _name_ok(name) or not f.is_file():
            continue
        try:
            out.append(parse(f.read_text(encoding='utf-8'), name))
        except Exception as e:
            out.append({'name': name, 'title': name, 'emoji': '🌊', 'broken': type(e).__name__, 'problems': []})
    return out


def load_profile(name: str) -> dict | None:
    if not _name_ok(name):
        return None
    f = profiles_dir() / f'{name}.md'
    try:
        return parse(f.read_text(encoding='utf-8'), name)
    except Exception:
        return None


def summary(p: dict) -> dict:
    """what the heart shows of a profile: names and numbers, never her words"""
    if p.get('broken'):
        return {'name': p['name'], 'title': p['title'], 'emoji': p['emoji'], 'ok': False, 'problems': [p['broken']]}
    return {
        'name': p['name'],
        'title': p['title'],
        'emoji': p['emoji'],
        'ok': True,
        'mean_min': round(p['rhythm']['mean'], 3),
        'spread': p['rhythm']['spread'],
        'length': list(p['length']),
        'quiet': p['quiet_text'],
        'voice': p['voice'],
        'typing': {'mode': p['typing'][0], 'rest_s': p['typing'][1]},
        'words': len(re.findall(r'\S+', p['words'] or '')),
        'problems': p['problems'],
    }


def demos() -> list[dict]:
    """the shipped demos, and whether her folder already holds a file of that name"""
    d = profiles_dir()
    out = []
    for name in DEMOS:
        f = DEMOS_DIR / f'{name}.md'
        if not f.is_file():
            continue
        p = parse(f.read_text(encoding='utf-8'), name)
        out.append({'name': name, 'title': p['title'], 'emoji': p['emoji'], 'planted': (d / f'{name}.md').exists()})
    return out


def plant(names: list[str] | None = None) -> dict:
    """copy the demos she asked for into her folder (600, the folder 700) · never over a file of hers"""
    wanted = [n for n in (names or DEMOS) if n in DEMOS]
    planted, kept = [], []
    d = _ready(profiles_dir())
    for name in wanted:
        src, dst = DEMOS_DIR / f'{name}.md', d / f'{name}.md'
        if not src.is_file():
            continue
        if dst.exists():
            kept.append(name)
            continue
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(src.read_text(encoding='utf-8'))
        planted.append(name)
    return {'planted': planted, 'kept': kept}


# ── the slots ─────────────────────────────────────────────────────────────────────────────────────────
_SLOT = re.compile(r'\{\{\s*([^{}]+?)\s*\}\}')


def render(words: str, facts: dict, card: str = '') -> tuple[str, str, list[str]]:
    """her words with today's facts → (text, card_by, debug) · card_by: 'code' (it goes on top) · 'her' (placed
    where she wrote {{part:card}}) · 'declined' ({{part:card|none}}) · 'none' (no card to place)"""
    debug: list[str] = []
    by = 'code' if card else 'none'
    if not words:
        return '', by, debug
    lines_out = []
    for line in words.split('\n'):
        out, drop = line, False
        for m in list(_SLOT.finditer(line)):
            raw = m.group(1)
            name = ALIASES.get(raw, raw)
            if name in ('part:card', 'part:card|none'):
                if name == 'part:card|none':
                    by = 'declined'
                    out = out.replace(m.group(0), '', 1)
                else:
                    if by != 'declined':
                        by = 'her' if card else by
                    out = out.replace(m.group(0), card if card else '', 1)
                continue
            if name not in FACTS:
                debug.append(f'skipped a line: {{{{{raw}}}}} is not a slot here')
                drop = True
                break
            value = facts.get(name, '')
            value = '' if value is None else str(value)
            if not value:
                debug.append(f'unsaid: {{{{{name}}}}} is empty right now')
                drop = True
                break
            out = out.replace(m.group(0), value, 1)
        if not drop:
            if out.strip() or not line.strip():
                lines_out.append(out)
    text = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines_out)).strip()
    return text, by, debug


def assemble(profile: dict, card: str, turns: list[dict], facts: dict) -> tuple[list[dict], dict]:
    """the request's messages: her card (a part code places on top) · the chat's recent turns · her words (at
    the end, or inside the system message with place: system) → (messages, peek)"""
    text, by, debug = render(profile.get('words') or '', facts, card)
    top = card if by == 'code' else ''
    msgs: list[dict] = []
    if profile.get('place') == 'system':
        system = '\n\n'.join(x for x in (top, text) if x)
        if system:
            msgs.append({'role': 'system', 'content': system})
        msgs += turns
    else:
        if top:
            msgs.append({'role': 'system', 'content': top})
        msgs += turns
        if text:
            msgs.append({'role': 'system', 'content': text})
    return msgs, {'card': by, 'words': bool(text), 'turns': len(turns), 'debug': debug}


# ── her words, measured ───────────────────────────────────────────────────────────────────────────────
_THINK = re.compile(r'<think>.*?</think>', re.S | re.I)
_DETAILS = re.compile(r'<details\b[^>]*>.*?</details>', re.S | re.I)
_END = re.compile(r'[.!?…~。！？]+[)"”’\]*_]*(?=\s|$)')
_WORD = re.compile(r'\S+')


def clean(raw) -> str:
    """what the model wrote, without a thought that leaked (thinking is off; this only measures)"""
    if not isinstance(raw, str):
        return ''
    text = raw
    if re.search(r'</think>', text, re.I):
        text = re.split(r'</think>', text, flags=re.I)[-1]
    elif re.match(r'\s*<think>', text, re.I):
        return ''  # a thought that never closed: no words of hers
    text = _DETAILS.sub('', _THINK.sub('', text))
    return text.strip()


def count_words(text: str) -> int:
    return len(_WORD.findall(text or ''))


def fit(text: str, lo: int, hi: int) -> tuple[str, dict]:
    """at most hi words, cut at the last sentence that ends inside them (else at the hi-th word) · fewer than lo
    is measured, never re-asked (a guard measures before it re-asks)"""
    n = count_words(text)
    info = {'words': n, 'fitted_from': None, 'short': n < lo}
    if n <= hi:
        return text, info
    cut = None
    for m in _END.finditer(text):
        if count_words(text[: m.end()]) <= hi:
            cut = m.end()
        else:
            break
    if cut is None:
        words = list(_WORD.finditer(text))
        cut = words[hi - 1].end()
    out = text[:cut].rstrip()
    info.update(words=count_words(out), fitted_from=n, short=count_words(out) < lo)
    return out, info


# ── the rhythm: the spiral way ────────────────────────────────────────────────────────────────────────
_KEY_MEMO: dict = {'key': None, 'path': None}
_KEY_LOCK = threading.Lock()


def key_path() -> Path:
    env = os.environ.get('PETAL_STREAM_KEY_FILE')
    return Path(env).expanduser() if env else home() / 'stream-rhythm.key'


def key_bytes() -> bytes:
    """the stream's own key (hex text, ≥ 16 bytes) · made once (600) when the default home has none · a key
    pointed at by $PETAL_STREAM_KEY_FILE is only ever read"""
    with _KEY_LOCK:
        p = key_path()
        if _KEY_MEMO['path'] == str(p) and _KEY_MEMO['key']:
            return _KEY_MEMO['key']
        key = None
        try:
            key = bytes.fromhex(p.read_text(encoding='utf-8').strip())
        except (OSError, ValueError):
            key = None
        if key is not None and len(key) < 16:
            key = None
        if key is None:
            if os.environ.get('PETAL_STREAM_KEY_FILE'):
                raise RuntimeError('the stream key named by PETAL_STREAM_KEY_FILE could not be read')
            _write_private(p, secrets.token_hex(32) + '\n')
            key = bytes.fromhex(p.read_text(encoding='utf-8').strip())
        _KEY_MEMO.update(key=key, path=str(p))
        return key


def fingerprint(key: bytes) -> str:
    return hmac.new(key, b'stream:fingerprint', hashlib.sha256).hexdigest()[:12]


def u(key: bytes, label: str) -> float:
    """the keyed uniform: (0, 1), never 0 or 1"""
    d = hmac.new(key, label.encode('utf-8'), hashlib.sha256).digest()
    return (int.from_bytes(d[:8], 'big') + 0.5) / 2**64


def figure(key: bytes) -> dict:
    """the spiral of two arms, turned by the key, its twist per ring drawn by the key (about half twist mirrored)"""
    sign = 1.0 if u(key, 'stream:spiral:direction') < 0.5 else -1.0
    return {
        'kind': 'spiral',
        'petals': 2,
        'turn': u(key, 'stream:spiral:turn'),
        'twist': round(sign * (0.03 + 0.09 * u(key, 'stream:spiral:twist')), 6),
    }


def ring_of(n: int) -> int:
    return (n - 1) // RING


def phase(t: float, tide: float = DAY_MIN) -> float:
    """where t sits in her tide, local time (a day by default: the hour of the day as a fraction)"""
    d = _local(t)
    minutes = (t + d.utcoffset().total_seconds()) / 60.0
    return (minutes % tide) / tide


def gap_of(uu: float, r: dict) -> float:
    """minutes · spread 1: the pure exponential around her mean; 0: her mean, steady; between: a floor of
    mean × (1 − spread) and the same mean · inside her min and max"""
    e = -math.log(1.0 - uu)
    g = r['mean'] * ((1.0 - r['spread']) + r['spread'] * e)
    return max(r['min'], min(r['max'], g))


def tilted(v: float, ph: float, fig: dict, r: dict, ring: int = 0, tilt: float = TILT) -> float:
    """the zero-mean tilt: v moved through an inverse CDF weighted toward gaps that land on the spiral's arms"""
    if tilt <= 0:
        return v
    turn = fig['turn'] + ring * fig.get('twist', 0.0)
    xs = [gap_of((i + 0.5) / GRID, r) / r['tide'] for i in range(GRID)]
    cs = [math.cos(2 * math.pi * fig['petals'] * (ph + x - turn)) for x in xs]
    m = sum(cs) / GRID
    w = [1.0 + tilt * (c - m) for c in cs]
    tot = sum(w)
    acc = 0.0
    for i, wi in enumerate(w):
        step = wi / tot
        if acc + step >= v:
            return min(1 - 1e-12, (i + (v - acc) / step) / GRID)
        acc += step
    return 1 - 1e-12


def keyed_gap(key: bytes, n: int, from_t: float, r: dict, label: str = 'stream:gap') -> dict:
    """the gap after utterance n (leading to n + 1), drawn from from_t"""
    ph = round(phase(from_t, r['tide']), 6)
    fig = figure(key)
    uu = tilted(u(key, f'{label}:{n}'), ph, fig, r, ring_of(n + 1))
    return {'n': n, 'ph': ph, 'min': round(gap_of(uu, r), 6), 'fig': fig['kind'], 'tilt': TILT, 'fp': fingerprint(key)}


def due(key: bytes, n: int, anchor: float, profile: dict, label: str = 'stream:gap') -> dict:
    """when she may speak next: her gap after the chat's last word, carried past any quiet window it lands in
    (a fresh gap drawn from the window's end)"""
    r = profile['rhythm']
    g = keyed_gap(key, n, anchor, r, label)
    at = anchor + g['min'] * 60
    hops = 0
    while hops < 4:
        q = quiet_end(at, profile.get('quiet') or [])
        if q is None:
            break
        g = keyed_gap(key, n, q, r, label)
        at = q + g['min'] * 60
        hops += 1
    return {'due_at': at, 'gap': round(g['min'], 3), 'n': n, 'ph': g['ph'], 'fp': g['fp']}


# ── the state: which chats are open to her stream ─────────────────────────────────────────────────────
_LOCK = threading.Lock()
_TEMP: dict = {}  # temporary chats: never on disk
_TEMP_N = {'n': 0}  # their draws, in memory
_MEMO: dict = {'key': None, 'doc': None}


def _fresh() -> dict:
    return {'v': 1, 'n': 0, 'chats': {}}


def _read() -> dict:
    p = state_path()
    try:
        st = p.stat()
    except OSError:
        return _fresh()
    key = (st.st_mtime_ns, st.st_size)
    if _MEMO['key'] == key and _MEMO['doc'] is not None:
        return copy.deepcopy(_MEMO['doc'])
    try:
        doc = json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(doc, dict) or not isinstance(doc.get('chats'), dict):
            raise ValueError
        doc.setdefault('n', 0)
    except Exception:
        doc = _fresh()
    _MEMO.update(key=key, doc=copy.deepcopy(doc))
    return doc


def _save(doc: dict) -> None:
    _write_private(state_path(), json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
    try:
        st = state_path().stat()
        _MEMO.update(key=(st.st_mtime_ns, st.st_size), doc=copy.deepcopy(doc))
    except OSError:
        _MEMO.update(key=None, doc=None)


def chat_state(chat_id: str, saved: bool) -> dict | None:
    with _LOCK:
        if not saved:
            s = _TEMP.get(chat_id)
            return dict(s) if s else None
        s = _read()['chats'].get(chat_id)
        return dict(s) if isinstance(s, dict) else None


def turn_on(chat_id: str, profile: str, saved: bool) -> dict:
    entry = {'profile': profile, 'on_at': int(time.time()), 'spoke': 0}
    with _LOCK:
        if not saved:
            _TEMP[chat_id] = entry
            return dict(entry)
        doc = _read()
        old = doc['chats'].get(chat_id) or {}
        entry['spoke'] = int(old.get('spoke') or 0) if old.get('profile') == profile else 0
        doc['chats'][chat_id] = entry
        _save(doc)
        return dict(entry)


def turn_off(chat_id: str, saved: bool) -> bool:
    with _LOCK:
        if not saved:
            return _TEMP.pop(chat_id, None) is not None
        doc = _read()
        if chat_id not in doc['chats']:
            return False
        doc['chats'].pop(chat_id)
        _save(doc)
        return True


def draw_n(saved: bool) -> tuple[int, str]:
    """(utterances so far, the label her next gap is drawn under)"""
    with _LOCK:
        if not saved:
            return _TEMP_N['n'], 'stream:t:gap'
        return int(_read().get('n') or 0), 'stream:gap'


def spoke(chat_id: str, saved: bool, record: dict) -> int:
    """one utterance landed: the draw advances (and, for a saved chat, one numbers-only line is kept)"""
    with _LOCK:
        if not saved:
            _TEMP_N['n'] += 1
            s = _TEMP.get(chat_id)
            if s:
                s['spoke'] = int(s.get('spoke') or 0) + 1
            return _TEMP_N['n']
        doc = _read()
        doc['n'] = int(doc.get('n') or 0) + 1
        s = doc['chats'].get(chat_id)
        if isinstance(s, dict):
            s['spoke'] = int(s.get('spoke') or 0) + 1
        _save(doc)
        n = doc['n']
    line = {k: record.get(k) for k in ('at', 'gap', 'ph', 'fp', 'profile', 'words', 'fitted_from', 'short')}
    line['n'] = n
    try:
        _ready(spoken_path().parent)
        fd = os.open(spoken_path(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as f:
            f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + '\n')
    except OSError:
        pass
    return n


def forget_temp() -> None:
    """tests only: the in-memory side, cleared"""
    with _LOCK:
        _TEMP.clear()
        _TEMP_N['n'] = 0


# ── the chat's recent turns, as text ──────────────────────────────────────────────────────────────────
def text_of(message: dict) -> str:
    content = message.get('content')
    if isinstance(content, list):
        content = ''.join(
            str(p.get('text', '')) for p in content if isinstance(p, dict) and p.get('type') in ('text', 'input_text')
        )
    if not isinstance(content, str):
        return ''
    return _DETAILS.sub('', _THINK.sub('', content)).strip()


def recent_turns(branch: list[dict], count: int) -> list[dict]:
    """the last `count` messages of the branch, user and assistant only, as text (stream messages included:
    they are hers too)"""
    if count <= 0:
        return []
    out = []
    for m in branch:
        role = m.get('role')
        if role not in ('user', 'assistant'):
            continue
        text = text_of(m)
        if text:
            out.append({'role': role, 'content': text})
    return out[-count:]


def in_a_row(branch: list[dict]) -> int:
    """stream messages at the end of the branch, since her last word"""
    n = 0
    for m in reversed(branch):
        if m.get('role') == 'user':
            break
        if m.get('role') == 'assistant' and isinstance(m.get(STAMP), dict):
            n += 1
        elif m.get('role') == 'assistant':
            break
    return n


def last_times(branch: list[dict]) -> tuple[float | None, float | None]:
    """(when Petal last spoke, when she last wrote) along the branch"""
    spoke_at = wrote_at = None
    for m in reversed(branch):
        ts = m.get('timestamp')
        if not isinstance(ts, (int, float)):
            continue
        if m.get('role') == 'assistant' and spoke_at is None:
            spoke_at = float(ts)
        if m.get('role') == 'user' and wrote_at is None:
            wrote_at = float(ts)
        if spoke_at is not None and wrote_at is not None:
            break
    return spoke_at, wrote_at


def facts_for(profile: dict, branch: list[dict], now: float, *, hidden_hour: bool, typing: bool) -> dict:
    spoke_at, wrote_at = last_times(branch)
    lo, hi = profile['length']
    return {
        'since_last_spoke': since(now - spoke_at) if spoke_at else '',
        'since_she_wrote': since(now - wrote_at) if wrote_at else '',
        'local_time': local_time(now, hidden_hour),
        'her_date': her_date(now),
        'user': today_name(now),
        'min_words': str(lo),
        'max_words': str(hi),
        'in_a_row': str(in_a_row(branch)),
        'typing': 'typing' if typing else '',
        'profile': profile.get('title') or profile.get('name') or '',
    }


def stamp(profile: dict, at: float, gap: float) -> dict:
    return {'profile': profile['name'], 'at': int(at), 'gap': round(float(gap), 3)}
