"""
petal_state 🌸👁 — what Petal sees of Lily's state (slice A8 · the seed of the state blocks).

one small place that assembles every live state line before a request goes to Petal:

  1 · the climax line  — after a message carrying a climax flag, once Lily has replied after it:
        "**status update:** [sat 23:40] Lily just climaxed."      (saved chats only · contract 0)
  2 · her thumbs       — after a rated reply: "**status update:** Lily 👍 this reply", plus her
        note when she left one. user setting `petalSight` (thumbs · notes), on by default
  3 · the climax trail — in her system context: the last N days of climax times (local) and the
        charges left / the next charge (knobs: trip-markers/settings.json → "climax")

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
    'status_climax': '**status update:** [{day} {time}] Lily just climaxed.',
    'status_thumb_up': '**status update:** Lily 👍 this reply',
    'status_thumb_down': '**status update:** Lily 👎 this reply',
    'status_note': ' · her note: “{note}”',
    'system_block': '{framing}\n{trail}\n{charges}',
    'framing': 'quiet notes from the rig, for you alone: lines marked **status update:** in the conversation are never words to quote back.',
    'trail': 'climax trail · last {days} days (local): {items}',
    'trail_item': '{day} {time}',
    'trail_join': ' · ',
    'trail_none': 'none',
    'charges_left': 'charges left: {left} of {total} today',
    'next_charge': 'next charge: {day} {time}',
}
CLIMAX_DEFAULT: dict = {'trail_days': 3, 'charges': 1, 'charge_window_h': 24, 'cooldown_h': 0}
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
        c = garden.settings().get('climax')
    except core.MarkerError:
        c = None
    out = dict(CLIMAX_DEFAULT)
    if isinstance(c, dict):
        for k in CLIMAX_DEFAULT:
            v = c.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                out[k] = v
    return out


def sight(user) -> dict:
    ui = getattr(getattr(user, 'settings', None), 'ui', None) or {}
    mine = ui.get('petalSight') if isinstance(ui, dict) else None
    return {**SIGHT_DEFAULT, **({k: bool(v) for k, v in mine.items() if k in SIGHT_DEFAULT} if isinstance(mine, dict) else {})}


def charges(times: list[int], now: int, knobs: dict) -> dict:
    """→ {'total', 'left', 'next'}: `charges` climaxes per rolling `charge_window_h`, and none
    until `cooldown_h` has passed since the last one. 'next' = when the next charge returns."""
    total = int(knobs['charges'])
    window, cool = float(knobs['charge_window_h']) * H, float(knobs['cooldown_h']) * H
    recent = sorted(t for t in times if t > now - window)
    left = max(0, total - len(recent))
    last = max(times) if times else None
    cooling = last + cool if (last is not None and cool > 0 and now < last + cool) else None
    if cooling:
        left = 0
    nxt = None
    if left == 0 and total > 0:
        cands = []
        if len(recent) >= total:
            cands.append(recent[len(recent) - total] + window)  # when the count drops below the total
        if cooling:
            cands.append(cooling)
        nxt = int(max(cands)) if cands else None
    return {'total': total, 'left': left, 'next': nxt}


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


def conversation_notes(chain: list[dict], climaxes: dict, ratings: dict, tpl: dict, see: dict) -> list[dict]:
    """→ [{'answer_from_end': j, 'message_id', 'text'}] · j counts the user turns from the newest
    (0 = the message she's sending now), so a context trimmed at its start never misaligns."""
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
            lines.append(fill(tpl, 'status_climax', **when(int(c['at']))))
        r = ratings.get(m.get('id')) if see['thumbs'] else None
        if r and r.get('rating') in (1, -1):
            line = fill(tpl, 'status_thumb_up' if r['rating'] == 1 else 'status_thumb_down')
            if line and see['notes'] and r.get('comment'):
                line += fill(tpl, 'status_note', note=r['comment'])
            lines.append(line)
        lines = [l for l in lines if l.strip()]
        if lines:
            out.append({'answer_from_end': len(users) - 1 - users.index(answer), 'message_id': m.get('id'),
                        'text': '\n'.join(lines)})
    return out


def system_block(times: list[int], now: int, knobs: dict, tpl: dict) -> str:
    days = knobs['trail_days']
    trail = [t for t in sorted(times) if t >= now - days * 24 * H]
    items = fill(tpl, 'trail_join').join(fill(tpl, 'trail_item', **when(t)) for t in trail) or fill(tpl, 'trail_none')
    ch = charges(times, now, knobs)
    if ch['left'] > 0:
        charge_line = fill(tpl, 'charges_left', left=ch['left'], total=ch['total'])
    elif ch['next']:
        charge_line = fill(tpl, 'next_charge', **when(ch['next']))
    else:
        charge_line = ''
    block = fill(tpl, 'system_block', framing=fill(tpl, 'framing'),
                 trail=fill(tpl, 'trail', days=f'{days:g}', items=items), charges=charge_line)
    return '\n'.join(l for l in block.splitlines() if l.strip())


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
    climax_events = core.events_in(view, 0, now, kind='climax')  # live: voids honored, amends applied
    times = [int(e['at']) for e in climax_events]

    notes: list[dict] = []
    chat_id, user_mid = metadata.get('chat_id'), metadata.get('user_message_id')
    if is_saved_chat_id(chat_id) and user_mid:
        from open_webui.models.chats import Chats
        from open_webui.models.feedbacks import Feedbacks

        chain = get_message_list(await Chats.get_messages_map_by_chat_id(chat_id) or {}, user_mid) or []
        climaxes = {e.get('message_id'): e for e in climax_events if e.get('chat_id') == chat_id}
        ratings = _latest_ratings(await Feedbacks.get_feedbacks_by_chat_id(chat_id)) if see['thumbs'] else {}
        notes = conversation_notes(chain, climaxes, ratings, tpl, see)

    messages = form_data.get('messages') or []
    user_idx = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    placed = []
    for n in notes:
        j = n['answer_from_end']
        if j < len(user_idx):
            target = messages[user_idx[-1 - j]] = copy.deepcopy(messages[user_idx[-1 - j]])
            _prepend(target, n['text'])
            placed.append(n)

    block = system_block(times, now, knobs, tpl)
    if block:
        messages = add_or_update_system_message(block, messages, append=True)
    form_data['messages'] = messages

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
