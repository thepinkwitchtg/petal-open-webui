"""
petal_state 🌸👁 — what Petal sees of Lily's state (slice A8 · the seed of the state blocks).

one small place that assembles every live state line before a request goes to Petal:

  1 · the climax line  — after a message carrying a 🌊 climax, once Lily has replied after it:
        "**status update:** [sat 23:40] Lily just climaxed."   (saved chats only · its quality and
        after-feel ride along only if her template asks for {quality} / {after})
      the orbit line   — after a message carrying a ✧ orbit (slice A11):
        "**status update:** [sat 23:40] Lily circulated an orbit." (+ " She held it." once she says)
  2 · her thumbs       — after a rated reply: "**status update:** Lily 👍 this reply", plus her
        note when she left one. user setting `petalSight` (thumbs · notes), on by default
  3 · the trail        — in her system context, retention-first (slice A11):
        "retention: day 4" (since the last climax) · "orbits_7d: 2 held · 1 leaked · 0 open" ·
        "last_orbit: 5h ago" · the charges left / the next charge. a charge is spent by a climax
        (spends[quality]) and by orbit_spends[outcome] of an orbit (knobs: trip-markers/settings.json
        → "climax")

      🔥 while a vow is alive (8b), retention lines take the trail's place: "retention: day 4 of
        her abstinence vow (14 days)" + "her words: “…”", and no charge is offered
  4 · the chips (9.4, slice A12) — under each reply, named `emoji · system · what it did`:
        "👍🏻 thumbs · 2 thumbs · 1 note" when her thumbs rode along, and "🦋 climax trail · day 4 ·
        1 charge left" whenever the trail did (led by retention), "🔥 abstinence vow · day 4 of 14"
        in its place during a vow. templates name them; tapping one shows the exact lines Petal got

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
        'the trail · {trail} in system_block is retention-first: retention · orbits · last_orbit. '
        '{n} days since the last climax (day 1 = its first 24 h) · {held} {leaked} {open} orbits in the '
        'last {days} days · {hours} or {ago} since the last orbit. {climaxes} brings back the list of '
        'climax times (climaxes_line). status_climax may carry {quality} and {after} (quality_* and '
        'after_* name them). an older "trail" key in this file is retired: it rests here as yours.'
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
    'retention_none': 'retention: no climax on record',
    'orbits': 'orbits_{days}d: {held} held · {leaked} leaked · {open} open',
    'last_orbit': 'last_orbit: {hours}h ago',
    'last_orbit_none': '',
    'climaxes_line': 'climaxes · last {days} days (local): {items}',
    # A11.1 · a climax's quality and after-feel, as {quality} / {after} in status_climax
    'quality_owned': '🔮 owned',
    'quality_received': '💗 received',
    'quality_hollow': '🕳 hollow',
    'after_fed': 'fed',
    'after_neutral': 'neutral',
    'after_hollow': 'hollow',
    # A12 · the 9.4 chips under each reply (the naming law: emoji · system · what it did)
    '_about_chips': (
        'the chips under a reply. chip_thumbs: {thumbs} "2 thumbs" · {notes} "1 note" (empty at 0) · '
        '{n_thumbs} {n_notes} as numbers. chip_trail: {retention} (chip_retention with {n}, or '
        'chip_retention_none) · {charges} "1 charge left", or chip_next_charge · {left} {total} {held} '
        '{leaked} {open} as numbers. an empty part never leaves a dangling dot.'
    ),
    'chip_thumbs': '👍🏻 thumbs · {thumbs} · {notes}',
    'chip_trail': '🦋 climax trail · {retention} · {charges}',
    'chip_retention': 'day {n}',
    'chip_retention_none': 'no climax yet',
    'chip_next_charge': 'next charge {day} {time}',
    # 8b · 🔥 while a vow is alive, these stand where the trail stood (and no charge is offered)
    '_about_vow': (
        'during a vow, {trail} reads vow_line + vow_words: {n} day (day 1 = its first 24 h) · {total} days '
        '· {vow} its name · {words} her why · {until_day} {until_time} when it ends. chip_vow names the chip.'
    ),
    'vow_line': 'retention: day {n} of her {vow} vow ({total} days)',
    'vow_words': 'her words: “{words}”',
    'chip_vow': '🔥 {vow} vow · day {n} of {total}',
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


def _at(e) -> int:
    return int(e['at']) if isinstance(e, dict) else int(e)


def spends(climaxes: list, orbits: list[dict], knobs: dict) -> list[tuple[int, float]]:
    """what each event spent of a charge: a climax spends[quality or 'unknown'] (a bare time counts
    as unknown), an orbit orbit_spends[outcome or 'unknown']."""
    cw, ow = knobs.get('spends') or {}, knobs.get('orbit_spends') or {}
    out = [(_at(c), float(cw.get((c.get('quality') if isinstance(c, dict) else None) or 'unknown', 1) or 0))
           for c in climaxes]
    for o in orbits:
        out.append((int(o['at']), float(ow.get(o.get('outcome') or 'unknown', 0) or 0)))
    return sorted(p for p in out if p[1] > 0)


def charges(spent: list, now: int, knobs: dict) -> dict:
    """→ {'total', 'left', 'next'}: `charges` per rolling `charge_window_h`, spent by climaxes and
    the leaked fraction of orbits (`spends`; plain times count 1), none until `cooldown_h` has
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
            q = fill(tpl, f"quality_{c['quality']}") if c.get('quality') in core.QUALITIES else ''
            a = fill(tpl, f"after_{c['after']}") if c.get('after') in core.AFTERS else ''
            lines.append(('🌊 climax line', fill(tpl, 'status_climax', quality=q, after=a, **when(int(c['at'])))))
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
            thumb = any(src == '👍🏻 thumbs' for src, _ in lines)
            out.append({'answer_from_end': len(users) - 1 - users.index(answer), 'message_id': m.get('id'),
                        'text': '\n'.join(l for _, l in lines),
                        'parts': [{'source': src, 'text': l} for src, l in lines],
                        'thumbs': int(thumb), 'noted': int(thumb and bool(see['notes'] and r and r.get('comment')))})
    return out


def _ago(seconds: float) -> str:
    m = max(0, int(seconds // 60))
    return f'{m}m' if m < 60 else f'{m // 60}h' if m < 48 * 60 else f'{m // (24 * 60)}d'


def trail_facts(climaxes: list, orbits: list[dict], now: int, knobs: dict) -> dict:
    """one reading of the trail, shared by Petal's lines and the chip under the reply."""
    last = max(_at(c) for c in climaxes) if climaxes else None
    days = knobs['orbit_trail_days']
    recent = [o for o in orbits if int(o['at']) >= now - days * 24 * H]
    count = {k: sum(1 for o in recent if (o.get('outcome') if o.get('outcome') in core.OUTCOMES else 'open') == k)
             for k in ('held', 'leaked', 'open')}
    return {
        'last': last,
        'n': int(max(0, now - last) // (24 * H)) + 1 if last is not None else None,  # day 1 = its first 24 h
        'hours': int(max(0, now - last) // H) if last is not None else None,
        'orbit_days': days, **count,
        'last_orbit': max(int(o['at']) for o in orbits) if orbits else None,
        'charges': charges(spends(climaxes, orbits, knobs), now, knobs),
    }


def trail_lines(climaxes: list, orbits: list[dict], now: int, knobs: dict, tpl: dict,
                facts: Optional[dict] = None) -> list[str]:
    """the trail, retention-first (slice A11): retention · orbits in the last N days · the last orbit."""
    f = facts or trail_facts(climaxes, orbits, now, knobs)
    out = [fill(tpl, 'retention', n=f['n'], hours=f['hours'], **when(f['last'])) if f['last'] is not None
           else fill(tpl, 'retention_none')]
    out.append(fill(tpl, 'orbits', days=f"{f['orbit_days']:g}", held=f['held'], leaked=f['leaked'], open=f['open']))
    lo = f['last_orbit']
    out.append(fill(tpl, 'last_orbit', hours=int(max(0, now - lo) // H), ago=_ago(now - lo), **when(lo))
               if lo is not None else fill(tpl, 'last_orbit_none'))
    return [l for l in out if l.strip()]


def vow_lines(vow: dict, tpl: dict) -> list[str]:
    """8b · what stands where the trail stood while a vow is alive."""
    u = when(vow['until'])
    kw = {'n': vow['day'], 'total': vow['total_days'], 'vow': vow.get('vow') or '', 'words': vow.get('words') or '',
          'until_day': u['day'], 'until_time': u['time']}
    return [l for l in (fill(tpl, 'vow_line', **kw), fill(tpl, 'vow_words', **kw)) if l.strip()]


def system_block(climaxes: list, now: int, knobs: dict, tpl: dict, orbits: tuple = (),
                 vow: Optional[dict] = None) -> tuple[str, list]:
    """→ (the block for her system context, its parts by source for her eyes) · `climaxes` are the
    live climax events (or bare times), `orbits` the live orbit events, `vow` the vow alive now."""
    orbits = list(orbits)
    days = knobs['trail_days']
    recent = [t for t in sorted(_at(c) for c in climaxes) if t >= now - days * 24 * H]
    items = fill(tpl, 'trail_join').join(fill(tpl, 'trail_item', **when(t)) for t in recent) or fill(tpl, 'trail_none')
    facts = trail_facts(climaxes, orbits, now, knobs)
    ch = facts['charges']
    if ch['left'] > 0:
        charge_line = fill(tpl, 'charges_left', left=ch['left'], total=ch['total'])
    elif ch['next']:
        charge_line = fill(tpl, 'next_charge', **when(ch['next']))
    else:
        charge_line = ''
    trail = trail_lines(climaxes, orbits, now, knobs, tpl, facts)
    if vow:  # 8b · retention lines in place of the trail, and no charge is offered
        trail, charge_line = vow_lines(vow, tpl), ''
    framing, climaxes_line = fill(tpl, 'framing'), fill(tpl, 'climaxes_line', days=f'{days:g}', items=items)
    block = fill(tpl, 'system_block', framing=framing, trail='\n'.join(trail), climaxes=climaxes_line, charges=charge_line)
    block = '\n'.join(l for l in block.splitlines() if l.strip())
    parts = [{'source': '🌸 petal-state', 'text': framing}] + [{'source': '🔥 vow' if vow else '🦋 climax trail', 'text': t} for t in trail]
    if '{climaxes}' in (tpl.get('system_block') or ''):
        parts.append({'source': '🦋 climax trail', 'text': climaxes_line})
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
    climax_events = core.events_in(view, 0, now, kind='climax')  # 🌊 climaxes · live: voids honored, amends applied
    orbit_events = core.events_in(view, 0, now, kind='orbit')  # ✧ orbits (slice A11)

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

    vow = view.vow_at(now)  # 8b · 🔥 a vow alive now takes the trail's place
    block, block_parts = system_block(climax_events, now, knobs, tpl, orbit_events, vow)
    facts = trail_facts(climax_events, orbit_events, now, knobs)
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

    # A12 · the 9.4 chips: what rode along, named; tapping one shows the exact lines
    names = chip_names(facts, sum(n['thumbs'] for n in placed), sum(n['noted'] for n in placed), tpl, vow)
    thumb_lines = []
    for n in placed:
        lines = [q['text'] for q in n['parts'] if q['source'] == '👍🏻 thumbs']
        if lines:
            where = 'the message you just sent' if n['answer_from_end'] == 0 else f"{n['answer_from_end']} turn(s) back"
            thumb_lines.append(f'── before {where} ──\n' + '\n'.join(lines))
    trail_doc = '\n'.join(q['text'] for q in block_parts if q['source'] in ('🦋 climax trail', '🔥 vow')) if block else ''
    await _chips(metadata, names, {'thumbs': '\n\n'.join(thumb_lines), 'trail': trail_doc})

    if see['debug']:
        await _debug_chip(metadata, added)
    return {**added, 'chips': names}  # the captured petal_state (for the ledger) keeps its shape


def _plural(n, one: str) -> str:
    return f'{_n(n)} {one}' + ('' if n == 1 else 's')


def _tidy(name: str) -> str:
    """an empty part never leaves a dangling dot: 'a ·  · b · ' → 'a · b'"""
    return ' · '.join(p for p in name.split(' · ') if p.strip())


def chip_names(facts: dict, n_thumbs: int, n_notes: int, tpl: dict, vow: Optional[dict] = None) -> dict:
    """the 9.4 names (A12): '👍🏻 thumbs · 2 thumbs · 1 note' · '🦋 climax trail · day 4 · 1 charge left'
    (· '🔥 abstinence vow · day 4 of 14' in the trail's place during a vow, 8b)"""
    ch = facts['charges']
    retention = fill(tpl, 'chip_retention', n=facts['n']) if facts['n'] else fill(tpl, 'chip_retention_none')
    if ch['left'] > 0:
        charge = f"{_plural(ch['left'], 'charge')} left"
    elif ch['next']:
        charge = fill(tpl, 'chip_next_charge', **when(ch['next']))
    else:
        charge = ''
    trail = _tidy(fill(tpl, 'chip_trail', retention=retention, charges=charge, n=facts['n'] or '',
                       left=ch['left'], total=ch['total'], held=facts['held'], leaked=facts['leaked'], open=facts['open']))
    thumbs = _tidy(fill(tpl, 'chip_thumbs', thumbs=_plural(n_thumbs, 'thumb'), notes=_plural(n_notes, 'note') if n_notes else '',
                        n_thumbs=n_thumbs, n_notes=n_notes)) if n_thumbs else ''
    if vow:
        trail = _tidy(fill(tpl, 'chip_vow', vow=vow.get('vow') or '', n=vow['day'], total=vow['total_days']))
    return {'thumbs': thumbs, 'trail': trail}


async def _chips(metadata: dict, names: dict, docs: dict) -> None:
    """the 9.4 chips under her reply: an attachment each, its document the exact lines Petal got."""
    try:
        from open_webui.socket.main import get_event_emitter

        if not (metadata.get('chat_id') and metadata.get('message_id')):
            return
        emit = await get_event_emitter(metadata)
        for key in ('thumbs', 'trail'):
            name, doc = names.get(key), docs.get(key)
            if not (name and doc):
                continue
            sid = f"petal-{key}-{metadata['message_id']}"
            await emit({'type': 'source', 'data': {
                'source': {'name': name, 'id': sid},
                'document': [doc],
                'metadata': [{'source': sid, 'name': name}],
            }})
    except Exception as e:
        log.warning(f'🌸 petal state: chips skipped ({e!r})')


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
