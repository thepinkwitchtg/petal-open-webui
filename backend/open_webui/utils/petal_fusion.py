"""
petal_fusion 🌕 — the fusion check: how is a stretch of conversation going? (slice A34)

now and then, under a finished reply, a small card asks her *how is the fusion so far?* with three moons:
🌕 flowing · 🌗 ignore (the neutral pass, kept as `mixed`, never a signal: this moon is the dismissal) · 🌑 off.
one tap folds the card into a tiny moon on that reply, and she can change it later. it scores a **stretch** of
conversation, not one reply: what thumbs and picks can't see (a chat that slowly bloomed, or slowly drifted).

- **when it asks (v1, before petal-calibrate):** aggressive at first, calming as it learns. 1 in `start` (5)
  finished replies, its distance to the floor halving every HALF (10) of her answers, down to 1 in `floor` (25),
  never zero. only 🌕 and 🌑 are answers here: a 🌗 teaches nothing and counts for nothing. her two numbers (and an
  off switch) live in Settings → 🌸 Petal and ride with each ask
- **the rails** (held for any decider, calibrate's included): saved chats only (contract 0) · never in an internal
  chat, nor under an internal or subagent turn · never under a pick's reply (so never inside an open pick) · at most
  once per stretch (a reply regenerated beside an asked one is the same stretch) · never before the stretch holds
  MIN_REPLIES (3) replies
- **a stretch:** her turns in one chat, along the reply's branch, with no quiet gap of PAUSE_S (1 h) between two of
  her messages; at most STRETCH_MAX (24) replies long, a longer sitting goes on as a new stretch
- **one decider:** `fusion_should_ask(context) → (bool, why)`, registered in `petal_pick.FUSION_ASK` beside
  `petal_pick.OFFERS` and asked through `petal_pick.ask_fusion`. petal-calibrate's `offer:fusion` takes its place in
  v2: the page and the routes never change
- **an ask is stamped on its reply** as `petal_fusion`, a top-level key of the message (never in `meta`, so never
  replayed to the model): `{asked_at, why, stretch_from, stretch_replies, turn_index, mode, pull, arm, substrate}`.
  her moon adds `{score, feedback_id, answered_at, changes}`
- **her moon is a feedback row**, landed through the thumbs route (`POST /api/v1/petal/thumbs` with `fusion`):
  `type: petal_fusion`, `data: {score, chat_id, message_id, turn_index, stretch_from, stretch_replies, mode, pull,
  arm, substrate, asked_why, asked_at, answered_at, history, model_id}`, `meta: {chat_id, message_id, turn_index}`,
  no snapshot (references, never copied words). a change replaces the score and appends the one it replaced to
  `history` as `{score, at}`; the same moon tapped again changes nothing
- **provenance:** `mode` is the mode chip's pick stamped on the reply · `pull` the steer the reply was served with
  (its pick record's, else the first round 👁 kept), null when unsteered · `arm` its arm record when it had one ·
  `substrate` the adapter it was served on: the reply's `petal_substrate` once the substrate stamp lands, else
  `"none"`
- **Petal never sees it:** the stamp is not a replayed key (middleware's MESSAGE_REPLAY_KEYS), petal_state reads
  `rating` rows only, 👁 shows only what was sent, and a moon never takes a thank-you or a tag step
"""

import json
import logging
import random
import time
from typing import Any, Optional

from open_webui.utils.chat_id import is_saved_chat_id

log = logging.getLogger(__name__)

TYPE = 'petal_fusion'
SCORES = ('flowing', 'mixed', 'off')
SIGNAL = ('flowing', 'off')  # 🌗 mixed is the neutral pass: kept, never a signal
MOONS = {'flowing': '🌕', 'mixed': '🌗', 'off': '🌑'}
START, FLOOR = 5, 25  # 1 in START finished replies at first, calming to 1 in FLOOR
HALF = 10  # her answers that halve the distance to the floor
MIN_REPLIES = 3  # replies a stretch holds before it can be asked about
STRETCH_MAX = 24  # a stretch is at most this many replies; a longer sitting goes on as a new stretch
PAUSE_S = 3600  # a quiet gap this long between two of her messages begins a new stretch


# ── her rate ────────────────────────────────────────────────────────────────────────────────────────────────


def rules(raw: Any) -> dict:
    """her settings as the page sends them (Settings → 🌸 Petal), kept inside their ranges · {on, start, floor}"""
    out = {'on': True, 'start': START, 'floor': FLOOR}
    if isinstance(raw, dict):
        if raw.get('on') is False:
            out['on'] = False
        for key, lo, hi in (('start', 1, 100), ('floor', 1, 500)):
            v = raw.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
                out[key] = v
    out['floor'] = max(out['floor'], out['start'])  # the floor never asks more often than the start
    return out


def rate(answers: int, start: int = START, floor: int = FLOOR) -> float:
    """the chance a finished reply asks once she has given `answers` moons (🌕 or 🌑): 1/start, its distance to
    1/floor halving every HALF answers, never below 1/floor"""
    n = max(0, int(answers or 0))
    hi = 1.0 / max(1, int(start or START))
    lo = min(hi, 1.0 / max(1, int(floor or FLOOR)))
    return lo + (hi - lo) * 0.5 ** (n / HALF)


def every(p: float) -> int:
    """a chance as she reads it: 1 in N"""
    return max(1, round(1.0 / p)) if p > 0 else 0


# ── the stretch ─────────────────────────────────────────────────────────────────────────────────────────────


def _seconds(ts: Any) -> Optional[float]:
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts <= 0:
        return None
    return ts / 1000.0 if ts > 1e12 else float(ts)  # a millisecond stamp read as seconds


def path_to(messages: dict, message_id: str) -> list:
    """the reply's branch, root first: [(id, message)] (the map's own keys, a cycle never loops)"""
    out, seen, cur = [], set(), message_id
    while cur and cur not in seen and isinstance(messages.get(cur), dict):
        seen.add(cur)
        out.append((cur, messages[cur]))
        cur = messages[cur].get('parentId')
    return out[::-1]


def stretch_of(messages: dict, message_id: str) -> Optional[dict]:
    """the stretch the reply sits in · {from: her first message's id, replies, turns, turn_index, ids}
    turn_index counts her messages along the branch up to this reply (1 = the first exchange)"""
    path = path_to(messages or {}, message_id)
    if not path or path[-1][0] != message_id:
        return None
    begin, start, replies, turns, turn_index, last = None, 0, 0, 0, 0, None
    for i, (mid, m) in enumerate(path):
        role = m.get('role')
        if role == 'user':
            t = _seconds(m.get('timestamp'))
            turn_index += 1
            paused = last is not None and t is not None and t - last >= PAUSE_S
            if begin is None or paused or replies >= STRETCH_MAX:
                begin, start, replies, turns = mid, i, 0, 0
            turns += 1
            if t is not None:
                last = t
        elif role == 'assistant' and begin is not None:
            replies += 1
    if begin is None:
        return None
    return {
        'from': begin,
        'replies': replies,
        'turns': turns,
        'turn_index': turn_index,
        'ids': [mid for mid, _ in path[start:]],
    }


def asked_in_stretch(messages: dict, stretch: Optional[dict], message_id: str) -> bool:
    """was the stretch already asked about? along its branch, or under a reply regenerated beside one of its replies
    (a regeneration is the same stretch: it never earns a second ask)"""
    for mid in (stretch or {}).get('ids') or []:
        m = messages.get(mid) if isinstance(messages.get(mid), dict) else {}
        if mid != message_id and isinstance(m.get('petal_fusion'), dict):
            return True
        if m.get('role') == 'user':
            for child in m.get('childrenIds') or []:
                if child != message_id and isinstance((messages.get(child) or {}).get('petal_fusion'), dict):
                    return True
    return False


# ── the rails and the v1 decider ────────────────────────────────────────────────────────────────────────────


def rails(context: dict) -> Optional[str]:
    """why this reply can't be asked about, whoever decides · None: it may be"""
    if not context.get('saved'):
        return 'temporary chats never ask'
    if context.get('internal'):
        return 'internal chats and turns never ask'
    reply = context.get('reply') if isinstance(context.get('reply'), dict) else None
    if not reply or reply.get('role') != 'assistant':
        return 'only a reply is asked about'
    if reply.get('done') is not True or reply.get('error'):
        return 'only a finished reply'
    if isinstance(reply.get('petal_pick'), dict):
        return 'never inside a pick'
    if isinstance(reply.get('petal_fusion'), dict):
        return 'already asked here'
    stretch = context.get('stretch')
    if not isinstance(stretch, dict):
        return 'no stretch to ask about'
    if context.get('asked_in_stretch'):
        return 'already asked in this stretch'
    if int(stretch.get('replies') or 0) < MIN_REPLIES:
        return f"the stretch is still young ({stretch.get('replies') or 0} of {MIN_REPLIES} replies)"
    return None


def fusion_should_ask(context: dict) -> tuple[bool, str]:
    """🌕 v1 · should this finished reply ask how the fusion is going? her rate, aggressive at first and calming as
    her moons accumulate, inside the rails. (context: built by context_for; `rng` may be handed in)"""
    r = context.get('rules') if isinstance(context.get('rules'), dict) else rules(None)
    if not r.get('on', True):
        return False, 'the fusion check is off'
    why = rails(context)
    if why:
        return False, why
    answers = int(context.get('answers') or 0)
    p = rate(answers, r.get('start', START), r.get('floor', FLOOR))
    rng = context.get('rng') or random
    if rng.random() < p:
        return True, f"1 in {every(p)} · {answers} {'moon' if answers == 1 else 'moons'} so far"
    return False, f'not this time (1 in {every(p)})'


# ── context, stamp, row ─────────────────────────────────────────────────────────────────────────────────────


def _internal_turn(message: Any) -> bool:
    meta = message.get('meta') if isinstance(message, dict) else None
    return isinstance(meta, dict) and meta.get('internal') is True


async def answers(user_id: str, db: Any = None) -> dict:
    """her moons so far, counted by score (the newest row per reply): {flowing, mixed, off}"""
    from sqlalchemy import select

    from open_webui.internal.db import get_async_db_context
    from open_webui.models.feedbacks import Feedback

    counts = {s: 0 for s in SCORES}
    try:
        async with get_async_db_context(db) as session:
            result = await session.execute(
                select(Feedback.data, Feedback.meta)
                .filter(Feedback.user_id == user_id, Feedback.type == TYPE)
                .order_by(Feedback.created_at.desc())
            )
            seen = set()
            for data, meta in result.all():
                mid = (meta or {}).get('message_id')
                if mid in seen:
                    continue
                seen.add(mid)
                score = (data or {}).get('score')
                if score in counts:
                    counts[score] += 1
    except Exception as e:  # her rate never costs her the turn: no count reads as none yet
        log.warning(f'🌕 petal fusion: her moons could not be counted ({e!r})')
    return counts


async def context_for(user: Any, chat: Any, message_id: str, raw_rules: Any = None, *, rng: Any = None, db: Any = None) -> dict:
    """everything the rails and a decider read, from the chat as the rig keeps it"""
    from open_webui.models.chats import is_internal_chat

    messages = (((getattr(chat, 'chat', None) or {}).get('history') or {}).get('messages')) or {}
    reply = messages.get(message_id) if isinstance(messages.get(message_id), dict) else None
    parent = messages.get(reply.get('parentId')) if reply and reply.get('parentId') else None
    stretch = stretch_of(messages, message_id) if reply else None
    asked = bool(stretch) and asked_in_stretch(messages, stretch, message_id)
    counts = await answers(user.id, db=db)
    return {
        'user_id': user.id,
        'chat_id': chat.id,
        'message_id': message_id,
        'saved': is_saved_chat_id(chat.id),
        'internal': is_internal_chat(getattr(chat, 'meta', None)) or _internal_turn(parent),
        'reply': reply,
        'stretch': stretch,
        'asked_in_stretch': asked,
        'answers': counts['flowing'] + counts['off'],
        'counts': counts,
        'rules': rules(raw_rules),
        'rng': rng,
        'now': time.time(),
    }


def served_pull(chat_id: str, message_id: str) -> Any:
    """the steer the reply's first request carried, as 👁 kept it (a JSON string on the wire, an object here) ·
    None: unsteered, or nothing kept"""
    try:
        from open_webui.utils import petal_eyes

        rounds = petal_eyes.get(chat_id, message_id)
        payload = (rounds[0] or {}).get('payload') if rounds else None
        xargs = payload.get('vllm_xargs') if isinstance(payload, dict) else None
        steer = xargs.get('petal_steer') if isinstance(xargs, dict) else None
        if isinstance(steer, str):
            try:
                steer = json.loads(steer)
            except Exception:
                pass
        return steer
    except Exception:
        return None


def provenance(chat_id: str, message_id: str, reply: dict) -> dict:
    """{mode, pull, arm, substrate} of the reply the ask sits under"""
    pick = reply.get('petal_pick') if isinstance(reply.get('petal_pick'), dict) else None
    arm = pick.get('arm') if pick and isinstance(pick.get('arm'), dict) else None
    pull = pick.get('pull') if pick else served_pull(chat_id, message_id)
    mode = reply.get('petal_mode') if isinstance(reply.get('petal_mode'), str) and reply.get('petal_mode') else None
    substrate = reply.get('petal_substrate')
    return {
        'mode': mode,
        'pull': pull,
        'arm': arm,
        'substrate': substrate if isinstance(substrate, str) and substrate else 'none',
    }


def stamp_for(context: dict, why: str) -> dict:
    """what the reply keeps of the ask (provenance read once, when it's asked)"""
    stretch = context['stretch']
    return {
        'asked_at': int(context.get('now') or time.time()),
        'why': str(why or '')[:200],
        'stretch_from': stretch.get('from'),
        'stretch_replies': stretch.get('replies'),
        'turn_index': stretch.get('turn_index'),
        **provenance(context['chat_id'], context['message_id'], context['reply']),
    }


def row_data(stamp: dict, score: str, chat_id: str, message_id: str, prior: Optional[dict], model_id: Any = None) -> dict:
    """the row her moon writes · a change keeps the moon it replaced in `history` ({score, at})"""
    now = int(time.time())
    history = [h for h in (prior or {}).get('history') or [] if isinstance(h, dict)]
    before = (prior or {}).get('score')
    if before in SCORES and before != score:
        history.append({'score': before, 'at': (prior or {}).get('answered_at')})
    same = before == score
    return {
        'score': score,
        'chat_id': chat_id,
        'message_id': message_id,
        'turn_index': stamp.get('turn_index'),
        'stretch_from': stamp.get('stretch_from'),
        'stretch_replies': stamp.get('stretch_replies'),
        'mode': stamp.get('mode'),
        'pull': stamp.get('pull'),
        'arm': stamp.get('arm'),
        'substrate': stamp.get('substrate') or 'none',
        'asked_why': stamp.get('why'),
        'asked_at': stamp.get('asked_at'),
        'answered_at': (prior or {}).get('answered_at') if same and prior else now,
        'history': history,
        'model_id': model_id if isinstance(model_id, str) else None,
    }


async def row_for(user_id: str, message_id: str, db: Any = None) -> Any:
    """the reply's fusion row (the newest, should two ever exist), or None"""
    from sqlalchemy import select

    from open_webui.internal.db import get_async_db_context
    from open_webui.models.feedbacks import Feedback, Feedbacks

    async with get_async_db_context(db) as session:
        result = await session.execute(
            select(Feedback.id)
            .filter(
                Feedback.user_id == user_id,
                Feedback.type == TYPE,
                Feedback.meta['message_id'].as_string() == message_id,
            )
            .order_by(Feedback.created_at.desc())
            .limit(1)
        )
        found = result.scalars().first()
    return await Feedbacks.get_feedback_by_id(id=found, db=db) if found else None
