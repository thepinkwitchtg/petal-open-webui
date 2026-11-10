"""
petal_state 🌸👁 — what Petal sees of Lily's state (slice A8 · the seed of the state blocks).

one small place that assembles every live state line before a request goes to Petal:

  1 · the spill line   — after a message carrying a 🌊 spill (the `climax` kind), once Lily has
        replied after it: "**status update:** [sat 23:40] Lily just climaxed."   (saved chats only)
      the orbit line   — after a message carrying a ✧ orbit (slice A11):
        "**status update:** [sat 23:40] Lily circulated an orbit." (+ " She held it." once she says)
  2 · her thumbs       — after a rated reply: "**status update:** Lily 👍 this reply", plus her
        note when she left one. user setting `petalSight` (thumbs · notes), on by default
  3 · the trail        — in her system context, retention-first (slice A11):
        "retention: day 4" (since the last spill) · "orbits_7d: 2 held · 1 leaked · 0 open" ·
        "last_orbit: 5h ago" · the charges left / the next charge. a charge is spent by a spill,
        plus orbit_spends[outcome] of an orbit (knobs: trip-markers/settings.json → "climax")

the in-conversation lines are prepended to the user turn that answered the marked reply, so
they sit right after that message in the order Petal reads. nothing is ever written into the
chat itself: everything is built at request time from the markers and OWUI's feedback rows.

the words live in $PETAL_APP_DATA/petal-state/templates.json (planted once, never overwritten;
a key left empty is never shown). what Petal saw rides with the reply for the ledger:
`system` (her whole system context, the training stamp) and `petal_state` (these lines).
only a request bound for Petal's local vLLM ever carries any of it — never a cloud model.
"""

import asyncio
import copy
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from open_webui.utils import petal_eyes  # 👁 slice A10: what each line is, for her eyes' tint
from open_webui.utils import petal_markers_core as core
from open_webui.utils.chat_id import is_saved_chat_id

log = logging.getLogger(__name__)

H = 3600

TEMPLATES_DEFAULT: dict = {
    '_about': (
        'the words Petal reads about your state. {placeholders} are filled at request time '
        '({day} sat · {time} 23:40 · {date} 2026-11-07). a line left empty is never shown. '
        'planted once by OWUI, never overwritten: this file is yours.'
    ),
    '_about_trail': (
        'slice A11 · {trail} in system_block is retention-first: retention · orbits · last_orbit. '
        '{n} days since the last spill (day 1 = its first 24 h) · {held} {leaked} {open} orbits in the '
        'last {days} days · {hours} or {ago} since the last orbit. {spills} brings back the old list of '
        'spill times (spills_line). an older "trail" key in this file is retired: it rests here as yours.'
    ),
    'status_climax': '**status update:** [{day} {time}] Lily just climaxed.',
    'status_thumb_up': '**status update:** Lily 👍 this reply',
    'status_thumb_down': '**status update:** Lily 👎 this reply',
    'status_note': ' · her note: “{note}”',
    'system_block': '{framing}\n{trail}\n{charges}',
    'framing': 'quiet notes from the rig, for you alone: lines marked **status update:** in the conversation are never words to quote back.',
    'trail_item': '{day} {time}',
    'trail_join': ' · ',
    'trail_none': 'none',
    'charges_left': 'charges left: {left} of {total} today',
    'next_charge': 'next charge: {day} {time}',
    # slice A11 · ✧ orbits, retention-first
    'status_orbit': '**status update:** [{day} {time}] Lily circulated an orbit.{outcome}',
    'orbit_held': ' She held it.',
    'orbit_leaked': ' It leaked.',
    'retention': 'retention: day {n}',
    'retention_none': 'retention: no spill on record',
    'orbits': 'orbits_{days}d: {held} held · {leaked} leaked · {open} open',
    'last_orbit': 'last_orbit: {hours}h ago',
    'last_orbit_none': '',
    'spills_line': 'spills · last {days} days (local): {items}',
}
CLIMAX_DEFAULT: dict = core.CLIMAX_DEFAULT  # one source: the core's settings defaults
SIGHT_DEFAULT: dict = {'thumbs': True, 'notes': True, 'debug': False}


# ── the words ──────────────────────────────────────────────────
def home() -> Path:
    return core.app_data_root() / 'petal-state'


def templates() -> dict:
    """her templates (planted once, never overwritten), missing keys filled from the defaults."""
    p = home() / 'templates.json'
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'x', encoding='utf-8') as f:
            json.dump(TEMPLATES_DEFAULT, f, ensure_ascii=False, indent=2)
            f.write('\n')
    except FileExistsError:
        pass
    except OSError as e:
        log.warning(f'🌸 petal state: could not plant templates.json ({e.strerror or e})')
    try:
        mine = json.loads(p.read_text(encoding='utf-8'))
        return {**TEMPLATES_DEFAULT, **(mine if isinstance(mine, dict) else {})}
    except Exception:
        log.warning('🌸 petal state: templates.json does not parse — reading the defaults, file left untouched')
        return dict(TEMPLATES_DEFAULT)


class _Blank(dict):
    def __missing__(self, key):
        return ''


def fill(tpl: dict, key: str, **kw) -> str:
    """one template line · a broken template falls back to the default line, never to an error."""
    for source in (tpl.get(key), TEMPLATES_DEFAULT.get(key)):
        if not isinstance(source, str):
            continue
        try:
            return source.format_map(_Blank(kw))
        except (ValueError, IndexError, KeyError, AttributeError):
            continue
    return ''


def when(ts: float) -> dict:
    t = time.localtime(ts)
    return {'time': f'{t.tm_hour:02d}:{t.tm_min:02d}', 'day': time.strftime('%a', t).lower(), 'date': time.strftime('%Y-%m-%d', t)}


# ── the knobs ──────────────────────────────────────────────────
def climax_knobs(garden: core.Garden) -> dict:
    try:
        return core.climax_knobs(garden.settings())
    except core.MarkerError:
        return core.climax_knobs(None)


def sight(user) -> dict:
    ui = getattr(getattr(user, 'settings', None), 'ui', None) or {}
    mine = ui.get('petalSight') if isinstance(ui, dict) else None
    return {**SIGHT_DEFAULT, **({k: bool(v) for k, v in mine.items() if k in SIGHT_DEFAULT} if isinstance(mine, dict) else {})}


def _n(x: float):
    """2.0 → 2 · 0.5 → 0.5 (how a count reads in her words)."""
    x = round(float(x), 2)
    return int(x) if x == int(x) else x


def spends(spills: list[int], orbits: list[dict], knobs: dict) -> list[tuple[int, float]]:
    """what each event spent of a charge: a spill 1, an orbit orbit_spends[outcome or 'unknown']."""
    w = knobs.get('orbit_spends') or {}
    out = [(int(t), 1.0) for t in spills]
    for o in orbits:
        out.append((int(o['at']), float(w.get(o.get('outcome') or 'unknown', 0) or 0)))
    return sorted(p for p in out if p[1] > 0)


def charges(spent: list, now: int, knobs: dict) -> dict:
    """→ {'total', 'left', 'next'}: `charges` per rolling `charge_window_h`, spent by spills (1 each)
    and the leaked fraction of orbits (`spends`; plain times count 1), none until `cooldown_h` has
    passed since the last spend. 'next' = when a charge returns."""
    items = sorted((int(p), 1.0) if isinstance(p, (int, float)) else (int(p[0]), float(p[1])) for p in spent)
    items = [p for p in items if p[1] > 0]
    total = float(knobs['charges'])
    window, cool = float(knobs['charge_window_h']) * H, float(knobs['cooldown_h']) * H
    recent = [p for p in items if p[0] > now - window]
    used = sum(w for _, w in recent)
    left = max(0.0, total - used)
    last = items[-1][0] if items else None
    cooling = last + cool if (last is not None and cool > 0 and now < last + cool) else None
    if cooling:
        left = 0.0
    nxt = None
    if left < 1e-9 and total > 0:
        cands = []
        if used >= total - 1e-9:
            acc = used
            for t, w in recent:  # oldest first: the moment enough has rolled out of the window
                acc -= w
                if acc < total - 1e-9:
                    cands.append(t + window)
                    break
        if cooling:
            cands.append(cooling)
        nxt = int(max(cands)) if cands else None
    return {'total': _n(total), 'left': _n(left), 'next': nxt}


# ── the lines ──────────────────────────────────────────────────
def _latest_ratings(feedbacks) -> dict:
    """message_id → {'rating', 'comment'} from OWUI's feedback rows (newest row per message wins)."""
    out: dict = {}
    for fb in feedbacks or []:  # get_feedbacks_by_chat_id answers newest first
        meta, data = (fb.meta or {}), (fb.data or {})
        mid = meta.get('message_id')
        if fb.type != 'rating' or not mid or mid in out:
            continue
        out[mid] = {'rating': data.get('rating'), 'comment': (data.get('comment') or '').strip()}
    return out


def conversation_notes(chain: list[dict], climaxes: dict, ratings: dict, tpl: dict, see: dict,
                       orbits: Optional[dict] = None) -> list[dict]:
    """→ [{'answer_from_end': j, 'message_id', 'text', 'parts'}] · j counts the user turns from the
    newest (0 = the message she's sending now), so a context trimmed at its start never misaligns.
    `parts` names each line's source for her eyes."""
    users = [i for i, m in enumerate(chain) if m.get('role') == 'user']
    out = []
    for i, m in enumerate(chain):
        if m.get('role') != 'assistant':
            continue
        answer = next((u for u in users if u > i), None)
        if answer is None:
            continue  # she hasn't replied after it yet
        lines = []
        c = climaxes.get(m.get('id'))
        if c:
            lines.append(('🌊 spill line', fill(tpl, 'status_climax', **when(int(c['at'])))))
        o = (orbits or {}).get(m.get('id'))
        if o:
            outcome = fill(tpl, f"orbit_{o['outcome']}") if o.get('outcome') in core.OUTCOMES else ''
            lines.append(('✧ orbit line', fill(tpl, 'status_orbit', outcome=outcome, **when(int(o['at'])))))
        r = ratings.get(m.get('id')) if see['thumbs'] else None
        if r and r.get('rating') in (1, -1):
            line = fill(tpl, 'status_thumb_up' if r['rating'] == 1 else 'status_thumb_down')
            if line and see['notes'] and r.get('comment'):
                line += fill(tpl, 'status_note', note=r['comment'])
            lines.append(('👍🏻 thumbs', line))
        lines = [(src, l) for src, l in lines if l.strip()]
        if lines:
            out.append({'answer_from_end': len(users) - 1 - users.index(answer), 'message_id': m.get('id'),
                        'text': '\n'.join(l for _, l in lines),
                        'parts': [{'source': src, 'text': l} for src, l in lines]})
    return out


def _ago(seconds: float) -> str:
    m = max(0, int(seconds // 60))
    return f'{m}m' if m < 60 else f'{m // 60}h' if m < 48 * 60 else f'{m // (24 * 60)}d'


def trail_lines(spills: list[int], orbits: list[dict], now: int, knobs: dict, tpl: dict) -> list[str]:
    """the trail, retention-first (slice A11): retention · orbits in the last N days · the last orbit."""
    out = []
    last = max(spills) if spills else None
    if last is not None:
        out.append(fill(tpl, 'retention', n=int(max(0, now - last) // (24 * H)) + 1,
                        hours=int(max(0, now - last) // H), **when(last)))
    else:
        out.append(fill(tpl, 'retention_none'))
    days = knobs['orbit_trail_days']
    recent = [o for o in orbits if int(o['at']) >= now - days * 24 * H]
    count = {k: sum(1 for o in recent if (o.get('outcome') if o.get('outcome') in core.OUTCOMES else 'open') == k)
             for k in ('held', 'leaked', 'open')}
    out.append(fill(tpl, 'orbits', days=f'{days:g}', **count))
    if orbits:
        lo = max(int(o['at']) for o in orbits)
        out.append(fill(tpl, 'last_orbit', hours=int(max(0, now - lo) // H), ago=_ago(now - lo), **when(lo)))
    else:
        out.append(fill(tpl, 'last_orbit_none'))
    return [l for l in out if l.strip()]


def system_block(times: list[int], now: int, knobs: dict, tpl: dict, orbits: tuple = ()) -> tuple[str, list]:
    """→ (the block for her system context, its parts by source for her eyes) · `times` are the
    spills (the climax kind), `orbits` the live orbit events."""
    orbits = list(orbits)
    days = knobs['trail_days']
    recent = [t for t in sorted(times) if t >= now - days * 24 * H]
    items = fill(tpl, 'trail_join').join(fill(tpl, 'trail_item', **when(t)) for t in recent) or fill(tpl, 'trail_none')
    ch = charges(spends(times, orbits, knobs), now, knobs)
    if ch['left'] > 0:
        charge_line = fill(tpl, 'charges_left', left=ch['left'], total=ch['total'])
    elif ch['next']:
        charge_line = fill(tpl, 'next_charge', **when(ch['next']))
    else:
        charge_line = ''
    trail = trail_lines(times, orbits, now, knobs, tpl)
    framing, spills_line = fill(tpl, 'framing'), fill(tpl, 'spills_line', days=f'{days:g}', items=items)
    block = fill(tpl, 'system_block', framing=framing, trail='\n'.join(trail), spills=spills_line, charges=charge_line)
    block = '\n'.join(l for l in block.splitlines() if l.strip())
    parts = [{'source': '🌸 petal-state', 'text': framing}] + [{'source': '🦋 climax trail', 'text': t} for t in trail]
    if '{spills}' in (tpl.get('system_block') or ''):
        parts.append({'source': '🦋 climax trail', 'text': spills_line})
    parts.append({'source': '🦋 climax trail', 'text': charge_line})
    return block, [p for p in parts if p['text'].strip() and p['text'] in block]


def _prepend(message: dict, text: str) -> None:
    c = message.get('content')
    if isinstance(c, list):
        for part in c:
            if isinstance(part, dict) and part.get('type') == 'text':
                part['text'] = f"{text}\n\n{part.get('text') or ''}"
                return
        c.insert(0, {'type': 'text', 'text': f'{text}\n\n'})
    else:
        message['content'] = f"{text}\n\n{c or ''}"


# ── the door ───────────────────────────────────────────────────
async def apply(request, form_data: dict, user, metadata: dict, model: Optional[dict]) -> Optional[dict]:
    """add Petal's state to this request, in place. → what was added (None when nothing applies).
    a request bound anywhere but Petal's local vLLM is left exactly as it was."""
    from open_webui.utils.misc import add_or_update_system_message, get_message_list
    from open_webui.utils.petal_gentle_stop import petal_base_url

    if await petal_base_url(request, model) is None:
        return None
    see = sight(user)
    tpl = await asyncio.to_thread(templates)
    garden = core.Garden()

    def read_markers():
        garden.ensure()
        view, _ = core.settle(garden)
        return view, climax_knobs(garden)

    view, knobs = await asyncio.to_thread(read_markers)
    now = int(time.time())
    climax_events = core.events_in(view, 0, now, kind='climax')  # 🌊 spills · live: voids honored, amends applied
    orbit_events = core.events_in(view, 0, now, kind='orbit')  # ✧ orbits (slice A11)
    times = [int(e['at']) for e in climax_events]

    notes: list[dict] = []
    chat_id, user_mid = metadata.get('chat_id'), metadata.get('user_message_id')
    if is_saved_chat_id(chat_id) and user_mid:
        from open_webui.models.chats import Chats
        from open_webui.models.feedbacks import Feedbacks

        chain = get_message_list(await Chats.get_messages_map_by_chat_id(chat_id) or {}, user_mid) or []
        climaxes = {e.get('message_id'): e for e in climax_events if e.get('chat_id') == chat_id}
        orbits = {e.get('message_id'): e for e in orbit_events if e.get('chat_id') == chat_id and e.get('message_id')}
        ratings = _latest_ratings(await Feedbacks.get_feedbacks_by_chat_id(chat_id)) if see['thumbs'] else {}
        notes = conversation_notes(chain, climaxes, ratings, tpl, see, orbits)

    messages = form_data.get('messages') or []
    user_idx = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    placed = []
    for n in notes:
        j = n['answer_from_end']
        if j < len(user_idx):
            target = messages[user_idx[-1 - j]] = copy.deepcopy(messages[user_idx[-1 - j]])
            _prepend(target, n['text'])
            placed.append(n)

    block, block_parts = system_block(times, now, knobs, tpl, orbit_events)
    if block:
        messages = add_or_update_system_message(block, messages, append=True)
    form_data['messages'] = messages
    for p in (block_parts if block else []) + [q for n in placed for q in n['parts']]:
        petal_eyes.part(metadata, p['source'], p['text'])

    # what she saw rides with the reply (the ledger's capture): her whole system + these lines
    system_now = messages[0].get('content') if messages and messages[0].get('role') == 'system' else None
    if isinstance(system_now, str):
        metadata['system_prompt'] = system_now
    added = {'system': block, 'notes': [{'answer_from_end': n['answer_from_end'], 'text': n['text']} for n in placed]}
    metadata['petal_state'] = added

    if see['debug']:
        await _debug_chip(metadata, added)
    return added


async def _debug_chip(metadata: dict, added: dict) -> None:
    """with debug on: a source chip under her reply showing exactly what was added."""
    try:
        from open_webui.socket.main import get_event_emitter

        if not (metadata.get('chat_id') and metadata.get('message_id')):
            return
        emit = await get_event_emitter(metadata)
        doc = '── in her system context ──\n' + (added['system'] or '(nothing)')
        for n in added['notes']:
            where = 'the message you just sent' if n['answer_from_end'] == 0 else f"{n['answer_from_end']} turn(s) back"
            doc += f'\n\n── before {where} ──\n{n["text"]}'
        sid = f"petal-state-{metadata['message_id']}"
        await emit({'type': 'source', 'data': {
            'source': {'name': '🌸 what Petal saw', 'id': sid},
            'document': [doc],
            'metadata': [{'source': sid, 'name': '🌸 what Petal saw'}],
        }})
    except Exception as e:
        log.warning(f'🌸 petal state: debug chip skipped ({e!r})')
