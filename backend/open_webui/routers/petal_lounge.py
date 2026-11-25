"""
petal_lounge 🌊 — Petal Stream (slice A41 · the lounge): Petal speaks on her own, in a chat opened to it.

the core lives in utils/petal_lounge.py (her profiles, the spiral rhythm, the slots, the state). this door:

    GET  /api/v1/petal/stream/profiles            → { profiles: [summary…], asleep: n, folder } (awake ones only;
                                                    chats left on with a sleeping or gone profile are turned off)
    GET  /api/v1/petal/stream/knobs               → { text } the knobs reference, shown in the 💗 (never copied)
    POST /api/v1/petal/stream/state  { chat_id, page, visible, leaf }        → this chat's stream (+ when she may speak)
    POST /api/v1/petal/stream/on     { chat_id, profile, page, visible, leaf } → on, for this chat only
    POST /api/v1/petal/stream/off    { chat_id }                               → off
    POST /api/v1/petal/stream/speak  { chat_id, page, visible, leaf, model, typing, turns? }
         → { status: 'spoke', message, parent_id, state } · or { status, state? } with status one of
           wait (not yet: her rhythm) · quiet (a quiet window) · busy (a reply runs, or one is owed) · speaking
           (she is already writing here) · not_lead (another page leads) · resting (the gentle stop) · yielded (the
           chat moved on while she wrote: her next message ends the turn) · empty · error · stopped (three model
           errors in a row: nothing asked until her md changes or the stream is turned on again) · off · gone ·
           asleep (enabled: false)

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
  keys). a saved chat gets it as its message row (0.13.5), then every open page reloads that chat
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

import os

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from open_webui.utils import petal_lounge as L
from open_webui.utils.auth import get_admin_user
from open_webui.utils.chat_id import is_saved_chat_id, is_temporary_chat_id

log = logging.getLogger(__name__)
router = APIRouter()

PAGE_OK = re.compile(r'^[A-Za-z0-9_-]{4,48}$')
TURNS_MAX = 2000  # a temporary chat's branch, as the page holds it (A43: the full branch)
TURN_CHARS = 100000
RESERVE = 2048  # tokens kept free for her words when a long branch is trimmed ($PETAL_STREAM_RESERVE)

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
    # A43 · what a normal send of this chat carries from the page (Chat.svelte), so her turn is built the same way
    filter_ids: Optional[list[str]] = None  # the filters she has on in this chat
    variables: Optional[dict] = None  # the page's prompt variables (the time, her name, her place…)
    mode: Optional[str] = None  # the 🌀 mode chip's pick for this chat
    system: Optional[str] = None  # temporary chats only: the chat's system prompt, held by the page
    params: Optional[dict] = None  # temporary chats only: the chat's params, held by the page


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
    if not prof.get('enabled', True):
        return {**out, 'on': False, 'asleep': prof['name']}
    s = L.summary(prof)
    out.update(
        profile=prof['name'],
        title=prof['title'],
        emoji=prof['emoji'],
        voice=prof['voice'],
        typing=s['typing'],
        spoke=int(st.get('spoke') or 0),
        passed=int(st.get('passed') or 0),
        problems=prof['problems'],
        ignored=prof.get('ignored') or [],
        mtime=prof.get('mtime'),
        stopped=L.stopped(st, prof.get('mtime')),
        errors=int(st.get('errors') or 0),
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
    anchor = L.anchor_of(leaf.at, st)
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
    """her words under the leaf she answered, if the chat is still where she left it (the timers' way) · since 0.13.5
    a message lives in its chat_message row (every key it has, the stamp in `data`) and the chat keeps only
    `current_message_id`: both written in one chat transaction, through upstream's own helpers"""
    from open_webui.models.chat_messages import ChatMessages
    from open_webui.models.chats import Chats
    from open_webui.tasks import has_active_tasks

    lock = _LOCKS.setdefault(chat_id, asyncio.Lock())
    async with lock:
        if await has_active_tasks(app.state.redis, chat_id):
            return False
        async with Chats._chat_transaction(chat_id) as (session, row):
            if not row or row.user_id != user.id or row.current_message_id != leaf_id:
                return False
            messages = await ChatMessages.get_messages_map_by_message_ids(chat_id, [leaf_id], db=session)
            if leaf_id not in messages:
                return False
            # 🌊 A43 · the row knows it's a stream message (meta beside the stamp): a later request's replay places the
            # spoke-first line before it
            spoken = {**message, 'parentId': leaf_id, 'meta': {**(message.get('meta') or {}), 'petal_spoke_first': True}}
            history = {'messages': messages, 'currentId': row.current_message_id}
            Chats.upsert_message_to_history(history, message['id'], spoken)
            for mid in (message['id'], leaf_id):  # hers, and the leaf that now lists her as its child
                m = history['messages'][mid]
                await ChatMessages.upsert_message(mid, chat_id, m.get('user_id') or user.id, m, db=session)
            row.current_message_id = history['currentId']
            row.updated_at = int(time.time())
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


def _window(models: dict, model_id: str) -> Optional[int]:
    """her window in tokens: the model list's max_model_len (vLLM lists it; a card reads its base model's),
    else $PETAL_STREAM_WINDOW, else unknown (nothing trimmed until the model says otherwise)"""
    seen, mid = set(), model_id
    while mid and mid not in seen and len(seen) < 4:
        seen.add(mid)
        entry = models.get(mid) or {}
        for src in (entry, entry.get('openai') or {}):
            v = src.get('max_model_len') if isinstance(src, dict) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                return int(v)
        mid = ((entry.get('info') or {}).get('base_model_id')) if isinstance(entry.get('info'), dict) else None
    try:
        v = int(os.environ.get('PETAL_STREAM_WINDOW') or 0)
        return v if v > 0 else None
    except ValueError:
        return None


def _reserve(form_data: dict) -> int:
    """the room kept for her words when a long branch is trimmed: a normal reply's own max_tokens when her card
    or chat sets one, else $PETAL_STREAM_RESERVE, else RESERVE"""
    for k in ('max_tokens', 'max_completion_tokens'):
        v = form_data.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            return v
    try:
        v = int(os.environ.get('PETAL_STREAM_RESERVE') or 0)
        return v if v > 0 else RESERVE
    except ValueError:
        return RESERVE


def _ran(form_data: dict) -> list:
    return list(((form_data.get('metadata') or {}).get('petal_stream') or {}).get('filters') or [])


def _with_images(messages: list[dict]) -> list[dict]:
    """a user message's image files as image_url parts, the way OWUI's own replay builds them"""
    from open_webui.utils.misc import is_raster_image_content_type

    for message in messages:
        image_files = [
            f
            for f in message.get('files', []) or []
            if isinstance(f, dict) and (f.get('type') == 'image' or is_raster_image_content_type(f.get('content_type')))
        ]
        if message.get('role') == 'user' and image_files and isinstance(message.get('content', ''), str):
            message['content'] = [
                {'type': 'text', 'text': message.get('content', '')},
                *[{'type': 'image_url', 'image_url': {'url': f['url']}} for f in image_files if f.get('url')],
            ]
    return messages


async def _turn(request, wreq, user, form, model_id: str, models: dict, chat_id: str, saved: bool, leaf_id: str,
                chat_system: str, chat_params: dict, branch: list, profile: str = '') -> tuple[dict, str]:
    """her stream turn, built the way a normal reply is (main.chat_completion → process_chat_payload →
    petal_state): her card and the chat's system prompt, her filters' inlets, the full branch, the page's
    variables, her mode · nothing is saved by it: no message id, no session, no task (her eyes and OWUI's
    bookkeeping see no reply to keep) · → (form_data, the card's own system prompt, for the window's count)"""
    from open_webui.models.config import Config
    from open_webui.models.models import Models
    from open_webui.utils import petal_state
    from open_webui.utils.filter import get_sorted_filter_ids
    from open_webui.utils.middleware import load_messages_from_db, process_chat_payload
    from open_webui.utils.misc import merge_model_params

    model = models.get(model_id) or request.app.state.MODELS.get(model_id)
    if not model:
        raise LookupError('model')
    card = await Models.get_model_by_id(model_id)
    card_params = card.params.model_dump() if card and card.params else {}
    card_system = card_params.get('system') if isinstance(card_params.get('system'), str) else ''

    # the params, as main merges them: global defaults · her card · her settings · this chat
    ui = (user.settings.ui if getattr(user, 'settings', None) else None) or {}
    defaults = copy.deepcopy(await Config.get('models.default_params', {}) or {})
    model_info_params = merge_model_params(defaults, card_params)
    model_info_params.pop('model_controls', None)
    request_params = {
        **(ui.get('params') if isinstance(ui.get('params'), dict) else {}),
        **{k: v for k, v in (chat_params or {}).items() if k != 'system'},
    }
    request_params = {k: v for k, v in request_params.items() if v is not None and k != 'model_controls'}
    params = merge_model_params(model_info_params, request_params)

    # the chat's system prompt, as the page sends it with a normal turn (the card's own joins it at the door)
    system = chat_system or (ui.get('system') if isinstance(ui.get('system'), str) else '')
    if saved:
        history = await load_messages_from_db(chat_id, leaf_id) or []
    else:
        history = [{k: v for k, v in m.items() if k in ('role', 'content', L.STAMP)} for m in branch]
    messages = ([{'role': 'system', 'content': system}] if system else []) + _with_images(history)

    variables = form.variables if isinstance(form.variables, dict) else {}
    filter_ids = [f for f in (form.filter_ids or []) if isinstance(f, str)][:64]
    mode = form.mode.strip()[:64] if isinstance(form.mode, str) and form.mode.strip() else None
    metadata = {
        'model_id': model_id,
        'tool_approval_resume': None,
        'user_id': user.id,
        'user_agent': L.CALLER,
        'client_ip': '127.0.0.1',
        'internal': False,
        'chat_id': chat_id,
        'message_id': None,  # no reply placeholder: nothing of OWUI's keeps this request
        'user_message': None,
        'user_message_id': None,  # the branch is given, never re-read (no compaction runs for her stream)
        'assistant_message_id': None,
        'regeneration_message_id': None,
        'session_id': None,
        'petal_mode': mode,
        'petal_turn': None,
        'petal_stream': {'profile': profile, 'leaf': leaf_id, 'filters': []},  # a filter may tell her turn apart
        'automation_id': None,
        'folder_id': None,
        'filter_ids': filter_ids,
        'tool_ids': None,
        'files': None,
        'features': {},
        'variables': variables,
        'chat_variables': {},
        'chat_context': {'messages': [m for m in messages if m.get('role') == 'system'], 'params': {}, 'chat_variables': {}},
        'model': model,
        'params': {
            'stream_delta_chunk_size': None,
            'reasoning_tags': None,
            'compact_token_threshold': None,
            'function_calling': params.get('function_calling') or 'native',
            'tool_approval_mode': None,
            'model_controls': {},
        },
    }
    try:
        metadata['petal_stream']['filters'] = list(await get_sorted_filter_ids(wreq, model, filter_ids))
    except Exception:
        pass
    form_data = {'model': model_id, 'messages': messages, 'stream': False, 'params': params, 'metadata': metadata}
    wreq.state.metadata = metadata
    form_data, metadata, _events, _paused = await process_chat_payload(wreq, form_data, user, metadata, model)
    if saved:  # her state reads the branch up to the leaf (notes before her messages, as any turn)
        metadata['user_message_id'] = leaf_id
    try:
        await petal_state.apply(wreq, form_data, user, metadata, model)
    except Exception as e:
        log.warning(f'🌊 stream: petal state skipped ({type(e).__name__})')  # her state never breaks a turn
    metadata['user_message_id'] = None
    form_data['metadata'] = metadata
    wreq.state.metadata = metadata
    return form_data, card_system


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


def _failed(chat_id: str, saved: bool, prof: dict, why: str, lead: bool, leaf) -> dict:
    """a model error, counted · the third in a row (her md unchanged) stops her trying"""
    n = L.note_error(chat_id, saved, why, prof.get('mtime'))
    st = L.chat_state(chat_id, saved)
    out = {'status': 'stopped' if n >= L.ERRORS_STOP else 'error', 'why': why, 'errors': n}
    if st:
        out['state'] = _state_out(chat_id, saved, st, prof, leaf, lead)
    return out


async def _resting() -> bool:
    from open_webui.utils import petal_thanks as T

    try:
        async with aiohttp.ClientSession() as session:
            return await T._live_stop(session)
    except Exception:
        return False


# ── the door ──────────────────────────────────────────────────────────────────────────────────────────
def _sweep() -> int:
    """chats left on with a profile she put to sleep (enabled: false) or took away: turned off · → how many"""
    awake = {p['name'] for p in L.list_profiles()}
    n = 0
    for chat_id, saved, name in L.chats_on():
        if name not in awake:
            L.turn_off(chat_id, saved)
            _LEADS.pop(chat_id, None)
            n += 1
    return n


@router.get('/stream/profiles')
async def profiles(user=Depends(get_admin_user)):
    found = await asyncio.to_thread(L.list_profiles)
    asleep = await asyncio.to_thread(L.list_profiles, True)
    await asyncio.to_thread(_sweep)
    return {'profiles': [L.summary(p) for p in found], 'asleep': len(asleep), 'folder': _folder()}


@router.get('/stream/knobs')
async def knobs(user=Depends(get_admin_user)):
    return {'text': await asyncio.to_thread(L.knobs), 'folder': _folder()}


@router.post('/stream/state')
async def state(form: StateForm, user=Depends(get_admin_user)):
    if not _chat_ok(form.chat_id):
        raise HTTPException(status_code=400, detail='not a chat')
    saved = is_saved_chat_id(form.chat_id)
    st = L.chat_state(form.chat_id, saved)
    lead = _lead(form.chat_id, form.page, form.visible)
    prof = await asyncio.to_thread(L.load_profile, st['profile']) if st else None
    out = _state_out(form.chat_id, saved, st, prof, form.leaf, lead)
    if st and not out['on']:  # a profile gone or asleep: the chat goes off (never deleted, only off)
        L.turn_off(form.chat_id, saved)
    return out


@router.post('/stream/on')
async def turn_on(form: OnForm, user=Depends(get_admin_user)):
    if not _chat_ok(form.chat_id):
        raise HTTPException(status_code=400, detail='not a chat')
    if not await _owned(form.chat_id, user):
        raise HTTPException(status_code=404, detail='no such chat')
    prof = await asyncio.to_thread(L.load_profile, form.profile)
    if not prof:
        raise HTTPException(status_code=404, detail='no such profile in her folder')
    if not prof.get('enabled', True):
        raise HTTPException(status_code=409, detail='that profile sleeps (enabled: false)')
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
    if not prof.get('enabled', True):
        L.turn_off(chat_id, saved)
        return {'status': 'asleep', 'state': {'chat_id': chat_id, 'on': False, 'asleep': prof['name']}}
    halt = L.stopped(st, prof.get('mtime'))
    if halt:
        return {'status': 'stopped', 'why': halt['why'], 'state': _state_out(chat_id, saved, st, prof, form.leaf, lead)}
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
            chat_params = (chat.chat or {}).get('params') or {}
            chat_params = chat_params if isinstance(chat_params, dict) else {}
            chat_system = chat_params.get('system') if isinstance(chat_params.get('system'), str) else ''
            page_leaf = Leaf(id=leaf_id, at=anchor, role='assistant', done=True)
        else:
            if not _leaf_ready(form.leaf):
                return {'status': 'busy', 'why': 'a reply is owed or runs'}
            leaf_id = form.leaf.id
            branch = _temp_branch(form.turns)
            anchor = float(form.leaf.at or 0)
            wanted = form.model
            chat_params = form.params if isinstance(form.params, dict) else {}  # held by the page (contract 0)
            chat_system = form.system if isinstance(form.system, str) else ''
            page_leaf = form.leaf
        anchor = L.anchor_of(anchor, st)

        key = L.key_bytes()
        n, label = L.draw_n(saved)
        d = L.due(key, n, anchor, prof, label)
        if now < d['due_at'] - 2:
            return {'status': 'wait', 'state': _state_out(chat_id, saved, st, prof, page_leaf, lead, now)}
        if await _resting():
            return {'status': 'resting'}

        # ── her request: a normal turn, then the floor ──
        from open_webui.utils.chat import generate_chat_completion

        wreq = _worker_request(request.app)
        models = await T._models(wreq, user)
        model_id = await T._pick(wreq, models, wanted, user)
        if not model_id:
            return {'status': 'error', 'why': 'no model to ask'}
        hidden = await asyncio.to_thread(T._hour_hidden)
        facts = await asyncio.to_thread(L.facts_for, prof, branch, now, hidden_hour=hidden, typing=bool(form.typing))
        note, peek = await asyncio.to_thread(L.floor_note, prof, facts)
        try:
            form_data, card_system = await _turn(
                request, wreq, user, form, model_id, models, chat_id, saved, leaf_id, chat_system, chat_params, branch,
                prof['name'],
            )
        except Exception as e:
            log.warning(f'🌊 stream: her turn could not be built ({type(e).__name__})')
            return _failed(chat_id, saved, prof, f'her turn could not be built · {type(e).__name__}', lead, form.leaf)
        if note:
            form_data['messages'].append({'role': 'user', 'content': note, L.FLOOR_MARK: 'floor'})
        form_data.pop('tools', None)  # her stream speaks in words: no tool loop rides on it
        form_data.pop('tool_choice', None)
        form_data['stream'] = False
        form_data['chat_template_kwargs'] = {**(form_data.get('chat_template_kwargs') or {}), 'enable_thinking': False}
        if prof.get('temperature') is not None:
            form_data['temperature'] = prof['temperature']
        if prof.get('top_p') is not None:
            form_data['top_p'] = prof['top_p']
        full = copy.deepcopy(form_data['messages'])
        window = _window(models, model_id)
        reserve = _reserve(form_data)
        per = L.CHARS_PER_TOKEN
        budget = (window - reserve - L.tokens_of({'content': card_system}, per)) if window else None
        form_data['messages'], left_out, est = L.trim(copy.deepcopy(full), budget, per)
        res = None
        for attempt in (0, 1):
            try:
                res = await generate_chat_completion(wreq, form_data=form_data, user=user)
            except Exception as e:
                log.warning(f'🌊 stream: the model call failed ({type(e).__name__})')
                return _failed(chat_id, saved, prof, type(e).__name__, lead, form.leaf)
            code, body = T._unwrap(res)
            if code < 400:
                break
            reason = _reason_of(body)
            seen = L.context_refusal(reason) if attempt == 0 else None
            if seen:  # the model counted: trimmed again by her own numbers, asked once more
                window, used = seen
                total = est + L.tokens_of({'content': card_system}, per)
                per = per * min(1.0, total / max(used, 1)) if used > total else per * 0.8
                budget = window - reserve - L.tokens_of({'content': card_system}, per)
                form_data['messages'], left_out, est = L.trim(copy.deepcopy(full), budget, per)
                log.info(f'🌊 stream: her window is {window} tokens · trimmed again ({left_out} left out)')
                continue
            log.warning(f'🌊 stream: the model answered {code} · {reason}')
            return _failed(chat_id, saved, prof, f'the model answered {code} · {reason[:200]}', lead, form.leaf)
        try:
            raw = (body['choices'][0].get('message') or {}).get('content')
        except (KeyError, IndexError, TypeError, AttributeError):
            raw = None
        text = L.clean(raw)
        L.clear_errors(chat_id, saved)
        at = time.time()
        peek = {**peek, 'left_out': left_out, 'window': window, 'tokens': est, 'filters': _ran(form_data)}
        record = {'at': int(at), 'gap': d['gap'], 'ph': d['ph'], 'fp': d['fp'], 'profile': prof['name'],
                  'left_out': left_out}

        # ── she let it pass: nothing lands, the gap starts over ──
        if L.is_pass(text):
            L.spoke(chat_id, saved, {**record, 'words': 0, 'passed_at': at}, passed=True)
            st_now = L.chat_state(chat_id, saved) or st
            return {
                'status': 'passed',
                'left_out': left_out,
                'state': _state_out(chat_id, saved, st_now, prof, page_leaf, lead),
                'peek': peek,
            }

        # ── her words land ──
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
            L.STAMP: L.stamp(prof, at, d['gap'], L.in_a_row(branch)),
        }
        if isinstance(body.get('usage'), dict):  # the same Info as any reply
            message['usage'] = body['usage']
        if saved and not await _insert(request.app, chat_id, user, leaf_id, message):
            return {'status': 'yielded'}
        words = L.count_words(text)
        L.spoke(chat_id, saved, {**record, 'words': words})
        if saved:
            await _reload(chat_id, message['id'], user)
        st_now = L.chat_state(chat_id, saved) or st
        nxt = _state_out(chat_id, saved, st_now, prof, Leaf(id=message['id'], at=at, role='assistant', done=True), lead)
        return {
            'status': 'spoke',
            'message': message,
            'parent_id': leaf_id,
            'left_out': left_out,
            'state': nxt,
            'peek': {**peek, 'words': words},
        }
    finally:
        _SPEAKING.discard(chat_id)
