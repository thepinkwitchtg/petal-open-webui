"""
petal_lounge 🌊 — Petal Stream (slice A41 · the lounge): Petal speaks on her own, in a chat opened to it.

the core lives in utils/petal_lounge.py (her profiles, the spiral rhythm, the slots, the state). this door:

    GET  /api/v1/petal/stream/profiles            → { profiles: [summary…], demos: [{name, title, emoji, planted}], folder }
    POST /api/v1/petal/stream/plant  { names? }   → the demos she asked for, copied into her folder (never over hers)
    POST /api/v1/petal/stream/state  { chat_id, page, visible, leaf }        → this chat's stream (+ when she may speak)
    POST /api/v1/petal/stream/on     { chat_id, profile, page, visible, leaf } → on, for this chat only
    POST /api/v1/petal/stream/off    { chat_id }                               → off
    POST /api/v1/petal/stream/speak  { chat_id, page, visible, leaf, model, typing, turns? }
         → { status: 'spoke', message, parent_id, state } · or { status, state? } with status one of
           wait (not yet: her rhythm) · quiet (a quiet window) · busy (a reply runs, or one is owed) · speaking
           (she is already writing here) · not_lead (another page leads) · resting (the gentle stop) · yielded (the
           chat moved on while she wrote: her next message ends the turn) · empty · error · off · gone

- **the page asks, the rig decides.** the page (src/lib/utils/petal-lounge.ts) keeps a timer to `due_at` and
  holds while she types (when the profile says wait), while a reply runs, while her voice plays; the rig checks
  everything again before a word is written
- **one page leads a chat:** the last page she looked at (a visible page claims the lead with any call). a hidden
  page speaks only while it leads, so the PC in the other room never speaks for a phone she just looked at.
  in memory only: after a restart a visible page claims it again
- **the request names itself** (`User-Agent: petal-open-webui/stream`, through utils/headers.py) and asks with
  thinking off (`chat_template_kwargs.enable_thinking: false`: the card's params never override a key the
  request sets). her ground is her card's system prompt and the chat's own (§11.10), rendered as hush and thanks
  render the card (forge slots stripped, the hour hidden when the forge hides it); her filters don't run for a
  stream utterance
- **the utterance lands as an assistant message** under the chat's current leaf, stamped at the top level
  `petal_stream: {profile, at, gap}` (never in meta, never replayed to the model: OWUI replays only its own
  keys). a saved chat gets it in its history and its message rows, then every open page reloads that chat
  (`chat:reload`, the way upstream's timers land theirs). a temporary chat lives on the page: the asking page
  lands it, the rig keeps nothing (contract 0)
- **her next message ends the turn naturally:** if the chat moved while she wrote (a send, a reply), her words
  are let go (`yielded`) and nothing is inserted
"""

import asyncio
import json
import copy
import logging
import re
import time
from typing import Optional
from uuid import uuid4

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from open_webui.utils import petal_lounge as L
from open_webui.utils.auth import get_admin_user
from open_webui.utils.chat_id import is_saved_chat_id, is_temporary_chat_id

log = logging.getLogger(__name__)
router = APIRouter()

PAGE_OK = re.compile(r'^[A-Za-z0-9_-]{4,48}$')
TURNS_MAX = 200
TURN_CHARS = 20000

_LEADS: dict = {}  # chat_id → (page, at): the last page she looked at
_SPEAKING: set = set()  # chats she is writing in right now
_LOCKS: dict = {}  # chat_id → asyncio.Lock for the insert


class Leaf(BaseModel):
    id: Optional[str] = None
    at: Optional[float] = None  # the page's anchor: the leaf's time, or later (when it saw it finish, or began watching)
    role: Optional[str] = None
    done: Optional[bool] = None


class StateForm(BaseModel):
    chat_id: str
    page: str = ''
    visible: bool = False
    leaf: Optional[Leaf] = None


class OnForm(StateForm):
    profile: str


class SpeakForm(StateForm):
    model: Optional[str] = None
    typing: bool = False
    turns: Optional[list] = None  # temporary chats only: the page holds their messages


class PlantForm(BaseModel):
    names: Optional[list[str]] = None


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────────
def _chat_ok(chat_id: str) -> bool:
    return bool(chat_id) and (is_saved_chat_id(chat_id) or is_temporary_chat_id(chat_id)) and len(chat_id) <= 200


def _lead(chat_id: str, page: str, visible: bool) -> bool:
    """a visible page takes the lead · a hidden one keeps it only if it already had it"""
    if not PAGE_OK.match(page or ''):
        return False
    if visible:
        _LEADS[chat_id] = (page, time.time())
        return True
    cur = _LEADS.get(chat_id)
    return bool(cur and cur[0] == page)


def _leaf_ready(leaf: Optional[Leaf]) -> bool:
    return bool(leaf and leaf.id and leaf.role == 'assistant' and leaf.done is not False)


def _folder() -> str:
    return 'Petal-App-Data/petal-open-webui/stream/'


async def _owned(chat_id: str, user) -> bool:
    if not is_saved_chat_id(chat_id):
        return True
    from open_webui.models.chats import Chats

    return (await Chats.get_chat_by_id_and_user_id(chat_id, user.id)) is not None


def _state_out(chat_id: str, saved: bool, st: Optional[dict], prof: Optional[dict], leaf: Optional[Leaf],
               lead: bool, now: Optional[float] = None) -> dict:
    out: dict = {'chat_id': chat_id, 'on': bool(st), 'lead': lead}
    if not st:
        return out
    if not prof:
        return {**out, 'on': False, 'gone': st.get('profile')}
    s = L.summary(prof)
    out.update(
        profile=prof['name'],
        title=prof['title'],
        emoji=prof['emoji'],
        voice=prof['voice'],
        typing=s['typing'],
        turns=prof['turns'],
        spoke=int(st.get('spoke') or 0),
        problems=prof['problems'],
    )
    now = time.time() if now is None else now
    key = L.key_bytes()
    n, label = L.draw_n(saved)
    out.update(n=n, fp=L.fingerprint(key))
    q = L.quiet_end(now, prof['quiet'])
    out['quiet_until'] = q
    if not _leaf_ready(leaf):
        out.update(due_at=None, waiting='a reply' if leaf and leaf.id else 'a message')
        return out
    anchor = max(float(leaf.at or 0), float(st.get('on_at') or 0))
    d = L.due(key, n, anchor, prof, label)
    due_at, gap = d['due_at'], d['gap']
    if q:  # inside a quiet window now: never before it ends, and then a fresh gap
        d2 = L.due(key, n, q, prof, label)
        if d2['due_at'] > due_at:
            due_at, gap = d2['due_at'], d2['gap']
    out.update(due_at=due_at, gap=gap)
    return out


def _worker_request(app) -> Request:
    """a request of its own, so OWUI's model door names the worker and nothing of a page's request rides along"""
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.0'},
        'method': 'POST',
        'path': '/api/v1/petal/stream/speak',
        'raw_path': b'/api/v1/petal/stream/speak',
        'query_string': b'',
        'headers': [],
        'client': ('127.0.0.1', 0),
        'server': ('127.0.0.1', 80),
        'scheme': 'http',
        'app': app,
    }
    request = Request(scope)
    request.state.petal_caller = L.CALLER  # utils/headers.py: User-Agent petal-open-webui/stream
    return request


async def _render_ground(template: str, user, hidden: bool) -> str:
    from open_webui.utils import petal_thanks as T
    from open_webui.utils.payload import resolve_system_prompt

    if not template or not template.strip():
        return ''
    template = T._FORGE_SLOTS.sub('', template)
    if hidden:
        template = T._hide_hour(template)
    return ((await resolve_system_prompt(template, {'variables': {}, 'chat_variables': {}}, user)) or '').strip()


async def _card(model_id: str, user, hidden: bool, chat_system: str = '') -> str:
    """her ground: the card's system prompt, then this chat's own system prompt when it has one (§11.10: the card +
    her chat system), rendered as hush and thanks render the card (forge slots stripped, the hour per the forge)"""
    from open_webui.models.models import Models

    card = await Models.get_model_by_id(model_id)
    params = card.params.model_dump() if card and card.params else {}
    template = params.get('system') if isinstance(params.get('system'), str) else ''
    parts = [await _render_ground(template, user, hidden), await _render_ground(chat_system or '', user, hidden)]
    return '\n\n'.join(p for p in parts if p)


def _temp_branch(turns: Optional[list]) -> list[dict]:
    """a temporary chat's messages as the page holds them (role, content, timestamp, the stamp's presence)"""
    out = []
    for t in (turns or [])[-TURNS_MAX:]:
        if not isinstance(t, dict) or t.get('role') not in ('user', 'assistant'):
            continue
        content = t.get('content')
        if not isinstance(content, str):
            continue
        m = {'role': t['role'], 'content': content[:TURN_CHARS]}
        if isinstance(t.get('timestamp'), (int, float)):
            m['timestamp'] = float(t['timestamp'])
        if t.get('stream'):
            m[L.STAMP] = {'profile': '', 'at': 0, 'gap': 0}
        out.append(m)
    return out


async def _insert(app, chat_id: str, user, leaf_id: str, message: dict) -> bool:
    """her words under the leaf she answered, if the chat is still where she left it (the timers' way)"""
    from open_webui.internal.db import get_async_db
    from open_webui.models.chat_messages import ChatMessages
    from open_webui.models.chats import Chat
    from open_webui.tasks import has_active_tasks
    from sqlalchemy import select

    lock = _LOCKS.setdefault(chat_id, asyncio.Lock())
    async with lock:
        async with get_async_db() as db:
            stmt = select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id)
            if db.bind.dialect.name == 'postgresql':
                stmt = stmt.with_for_update()
            row = (await db.execute(stmt)).scalar_one_or_none()
            if not row:
                return False
            if await has_active_tasks(app.state.redis, chat_id):
                return False
            chat = copy.deepcopy(row.chat or {})
            history = chat.setdefault('history', {})
            messages = history.setdefault('messages', {})
            current = row.current_message_id if row.current_message_id in messages else history.get('currentId')
            if current != leaf_id or leaf_id not in messages:
                return False
            messages[message['id']] = message
            children = messages[leaf_id].setdefault('childrenIds', [])
            if message['id'] not in children:
                children.append(message['id'])
            history['currentId'] = message['id']
            row.chat = chat
            row.current_message_id = message['id']
            row.updated_at = int(time.time())
            await db.commit()
        await ChatMessages.upsert_message(message['id'], chat_id, user.id, message)
    return True


async def _reload(chat_id: str, message_id: str, user) -> None:
    try:
        from open_webui.socket.main import sio

        await sio.emit(
            'events',
            {'chat_id': chat_id, 'message_id': message_id, 'data': {'type': 'chat:reload'}},
            room=f'user:{user.id}',
        )
    except Exception as e:  # the asking page has her words already; the others see them on their next open
        log.warning(f'🌊 stream: the reload did not go out ({type(e).__name__})')


def _reason_of(body) -> str:
    """the error's own reason (vLLM / OWUI shapes), one line, never the request"""
    try:
        if isinstance(body, (bytes, bytearray)):
            body = body.decode('utf-8', 'replace')
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except Exception:
                return ' '.join(body.split())[:300]
        if isinstance(body, dict):
            e = body.get('error', body.get('detail', body.get('message')))
            if isinstance(e, dict):
                e = e.get('message') or e.get('detail') or e
            return ' '.join(str(e).split())[:300]
        return type(body).__name__
    except Exception as x:
        return f'unreadable ({type(x).__name__})'


async def _resting() -> bool:
    from open_webui.utils import petal_thanks as T

    try:
        async with aiohttp.ClientSession() as session:
            return await T._live_stop(session)
    except Exception:
        return False


# ── the door ──────────────────────────────────────────────────────────────────────────────────────────
@router.get('/stream/profiles')
async def profiles(user=Depends(get_admin_user)):
    found = await asyncio.to_thread(L.list_profiles)
    return {'profiles': [L.summary(p) for p in found], 'demos': await asyncio.to_thread(L.demos), 'folder': _folder()}


@router.post('/stream/plant')
async def plant(form: PlantForm, user=Depends(get_admin_user)):
    done = await asyncio.to_thread(L.plant, form.names)
    found = await asyncio.to_thread(L.list_profiles)
    return {
        **done,
        'profiles': [L.summary(p) for p in found],
        'demos': await asyncio.to_thread(L.demos),
        'folder': _folder(),
    }


@router.post('/stream/state')
async def state(form: StateForm, user=Depends(get_admin_user)):
    if not _chat_ok(form.chat_id):
        raise HTTPException(status_code=400, detail='not a chat')
    saved = is_saved_chat_id(form.chat_id)
    st = L.chat_state(form.chat_id, saved)
    lead = _lead(form.chat_id, form.page, form.visible)
    prof = await asyncio.to_thread(L.load_profile, st['profile']) if st else None
    return _state_out(form.chat_id, saved, st, prof, form.leaf, lead)


@router.post('/stream/on')
async def turn_on(form: OnForm, user=Depends(get_admin_user)):
    if not _chat_ok(form.chat_id):
        raise HTTPException(status_code=400, detail='not a chat')
    if not await _owned(form.chat_id, user):
        raise HTTPException(status_code=404, detail='no such chat')
    prof = await asyncio.to_thread(L.load_profile, form.profile)
    if not prof:
        raise HTTPException(status_code=404, detail='no such profile in her folder')
    saved = is_saved_chat_id(form.chat_id)
    st = L.turn_on(form.chat_id, prof['name'], saved)
    lead = _lead(form.chat_id, form.page, True)  # turning it on is a look
    return _state_out(form.chat_id, saved, st, prof, form.leaf, lead)


@router.post('/stream/off')
async def turn_off(form: StateForm, user=Depends(get_admin_user)):
    if not _chat_ok(form.chat_id):
        raise HTTPException(status_code=400, detail='not a chat')
    saved = is_saved_chat_id(form.chat_id)
    was = L.turn_off(form.chat_id, saved)
    _LEADS.pop(form.chat_id, None)
    return {'chat_id': form.chat_id, 'on': False, 'was': was}


@router.post('/stream/speak')
async def speak(request: Request, form: SpeakForm, user=Depends(get_admin_user)):
    from open_webui.utils import petal_thanks as T

    chat_id = form.chat_id
    if not _chat_ok(chat_id):
        raise HTTPException(status_code=400, detail='not a chat')
    saved = is_saved_chat_id(chat_id)
    st = L.chat_state(chat_id, saved)
    if not st:
        return {'status': 'off', 'state': {'chat_id': chat_id, 'on': False}}
    lead = _lead(chat_id, form.page, form.visible)
    if not lead:
        return {'status': 'not_lead', 'state': {'chat_id': chat_id, 'on': True, 'lead': False}}
    prof = await asyncio.to_thread(L.load_profile, st['profile'])
    if not prof:
        L.turn_off(chat_id, saved)
        return {'status': 'gone', 'state': {'chat_id': chat_id, 'on': False, 'gone': st['profile']}}
    if chat_id in _SPEAKING:
        return {'status': 'speaking'}
    now = time.time()
    if L.quiet_end(now, prof['quiet']):
        return {'status': 'quiet', 'state': _state_out(chat_id, saved, st, prof, form.leaf, lead, now)}

    _SPEAKING.add(chat_id)
    try:
        # ── the chat as it stands ──
        if saved:
            from open_webui.models.chats import Chats
            from open_webui.tasks import has_active_tasks
            from open_webui.utils.misc import get_message_list

            chat = await Chats.get_chat_by_id_and_user_id(chat_id, user.id)
            if not chat:
                L.turn_off(chat_id, saved)
                return {'status': 'off', 'state': {'chat_id': chat_id, 'on': False}}
            history = (chat.chat or {}).get('history') or {}
            messages = history.get('messages') or {}
            leaf_id = chat.current_message_id if chat.current_message_id in messages else history.get('currentId')
            leaf = messages.get(leaf_id) if leaf_id else None
            if not leaf or leaf.get('role') != 'assistant' or leaf.get('done') is False:
                return {'status': 'busy', 'why': 'a reply is owed' if leaf and leaf.get('role') == 'user' else 'a reply runs'}
            if await has_active_tasks(request.app.state.redis, chat_id):
                return {'status': 'busy', 'why': 'a task runs in this chat'}
            branch = get_message_list(messages, leaf_id)
            anchor = float(leaf.get('timestamp') or 0)
            if form.leaf and form.leaf.id == leaf_id and form.leaf.at:
                anchor = max(anchor, float(form.leaf.at))
            wanted = form.model or next(iter((chat.chat or {}).get('models') or []), None)
            chat_system = ((chat.chat or {}).get('params') or {}).get('system')
            chat_system = chat_system if isinstance(chat_system, str) else ''
            page_leaf = Leaf(id=leaf_id, at=anchor, role='assistant', done=True)
        else:
            if not _leaf_ready(form.leaf):
                return {'status': 'busy', 'why': 'a reply is owed or runs'}
            leaf_id = form.leaf.id
            branch = _temp_branch(form.turns)
            anchor = float(form.leaf.at or 0)
            wanted = form.model
            chat_system = ''  # a temporary chat's own system prompt stays on its page
            page_leaf = form.leaf
        anchor = max(anchor, float(st.get('on_at') or 0))

        key = L.key_bytes()
        n, label = L.draw_n(saved)
        d = L.due(key, n, anchor, prof, label)
        if now < d['due_at'] - 2:
            return {'status': 'wait', 'state': _state_out(chat_id, saved, st, prof, page_leaf, lead, now)}
        if await _resting():
            return {'status': 'resting'}

        # ── her request ──
        from open_webui.utils.chat import generate_chat_completion

        wreq = _worker_request(request.app)
        models = await T._models(wreq, user)
        model_id = await T._pick(wreq, models, wanted, user)
        if not model_id:
            return {'status': 'error', 'why': 'no model to ask'}
        hidden = await asyncio.to_thread(T._hour_hidden)
        card = await _card(model_id, user, hidden, chat_system)
        facts = await asyncio.to_thread(L.facts_for, prof, branch, now, hidden_hour=hidden, typing=bool(form.typing))
        msgs, peek = L.assemble(prof, card, L.recent_turns(branch, prof['turns']), facts)
        lo, hi = prof['length']
        payload = {
            'model': model_id,
            'messages': msgs,
            'stream': False,
            'max_tokens': hi * 4 + 48,  # room for her words in any script; fit() keeps the range
            'chat_template_kwargs': {'enable_thinking': False},  # thinking is off, everywhere
            'metadata': {'task': 'petal_stream', 'task_body': {}, 'chat_id': None},  # OWUI saves nothing of it
        }
        if prof.get('temperature') is not None:
            payload['temperature'] = prof['temperature']
        if prof.get('top_p') is not None:
            payload['top_p'] = prof['top_p']
        try:
            res = await generate_chat_completion(wreq, form_data=payload, user=user, bypass_system_prompt=True)
        except Exception as e:
            log.warning(f'🌊 stream: the model call failed ({type(e).__name__})')
            return {'status': 'error', 'why': type(e).__name__}
        code, body = T._unwrap(res)
        if code >= 400:
            reason = _reason_of(body)
            log.warning(f'🌊 stream: the model answered {code} · {reason}')
            return {'status': 'error', 'why': f'the model answered {code} · {reason[:200]}'}
        try:
            raw = (body['choices'][0].get('message') or {}).get('content')
        except (KeyError, IndexError, TypeError, AttributeError):
            raw = None
        text, info = L.fit(L.clean(raw), lo, hi)
        if not text:
            return {'status': 'empty'}

        # ── her words land ──
        at = time.time()
        message = {
            'id': str(uuid4()),
            'parentId': leaf_id,
            'childrenIds': [],
            'role': 'assistant',
            'content': text,
            'model': model_id,
            'modelName': ((models.get(model_id) or {}).get('name')) or model_id,
            'modelIdx': 0,
            'timestamp': int(at),
            'done': True,
            L.STAMP: L.stamp(prof, at, d['gap']),
        }
        if saved and not await _insert(request.app, chat_id, user, leaf_id, message):
            return {'status': 'yielded'}
        L.spoke(chat_id, saved, {**info, 'at': int(at), 'gap': d['gap'], 'ph': d['ph'], 'fp': d['fp'], 'profile': prof['name']})
        if saved:
            await _reload(chat_id, message['id'], user)
        st_now = L.chat_state(chat_id, saved) or st
        nxt = _state_out(chat_id, saved, st_now, prof, Leaf(id=message['id'], at=at, role='assistant', done=True), lead)
        return {
            'status': 'spoke',
            'message': message,
            'parent_id': leaf_id,
            'state': nxt,
            'peek': {**peek, 'words': info['words'], 'fitted_from': info['fitted_from'], 'short': info['short']},
        }
    finally:
        _SPEAKING.discard(chat_id)
