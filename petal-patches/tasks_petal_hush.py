

# >>> petal · hush · begin >>>
##################################
#
# 🌸 petal · hush  ·  v0.8  (petal-patch, grafted by petal-hush-apply.sh)
# Petal writes the whisper in the empty chat field, at runtime.
# called directly through generate_chat_completion, like title
# generation — never through the chat pipeline, so memory injection,
# background review and the ledger never see it. nothing is saved to any chat.
#
# v0.3 · upstream errors come back loud with the model name.
# v0.4 · every failure names its model AND its real reason.
# v0.5 · app.state.MODELS is filled lazily in 0.12 — we fill it like chat does.
# v0.6 · the model is picked exactly like a new chat picks it, and Petal is
#        asked in HER OWN model so her system prompt + params shape every line.
# v0.7 · a trimmed answer says WHY ('reason').
# v0.8 · lenses + reply whispers + privacy by design:
#        · your lenses live in petal-lenses/ at the fork root — hand-tuned,
#          never generated, never served (the old static copies were public)
#        · GET /petal_hush/pool hands the page your lines, signed-in only
#        · mode 'reply': after you send, the server waits (a primary-key
#          lookup about once a second, no GPU) until Petal's reply is done,
#          then she whispers from that exchange through the reply lens
#        · everything shareable is numbers: debug, logs and errors carry
#          counts and reasons, never your words or hers. 'peek' is the one
#          explicit door to the text, for your eyes in your own console.
#
##################################

import asyncio as _petal_asyncio
import json as _petal_json
import os as _petal_os
import time as _petal_time
from pathlib import Path as _PetalPath

from open_webui.env import DATA_DIR as _PETAL_DATA_DIR
from open_webui.env import FRONTEND_BUILD_DIR as _PETAL_BUILD_DIR
from open_webui.env import STATIC_DIR as _PETAL_STATIC_DIR
from open_webui.models.chat_messages import ChatMessages as _PetalChatMessages
from open_webui.models.chats import Chats as _PetalChats
from open_webui.utils.misc import get_message_list as _petal_get_message_list
from open_webui.utils.misc import get_output_text as _petal_get_output_text
from open_webui.utils.models import get_all_models as _petal_get_all_models
from open_webui.utils.task import prompt_template as _petal_prompt_template
from open_webui.utils.task import replace_messages_variable as _petal_replace_messages
from open_webui.utils.task import replace_prompt_variable as _petal_replace_prompt

# your lenses — hand-tuned, never generated, never served. git-invisible by your own .gitignore.
# (this file is grafted into backend/open_webui/routers/tasks.py → parents[3] is the fork root)
_PETAL_LENSES = _PetalPath(
    _petal_os.getenv('PETAL_LENSES_DIR') or _PetalPath(__file__).resolve().parents[3] / 'petal-lenses'
)
# what scripts GROW (petal's pool lines) — private runtime data, beside OWUI's own, git-ignored upstream
_PETAL_GROWN = _PetalPath(_PETAL_DATA_DIR) / 'petal' / 'hush-grown.json'
# where the old copies lived — read only as a migration fallback, and reported while they linger
_PETAL_SERVED = [
    ('served', _PetalPath(_PETAL_STATIC_DIR) / 'petal'),
    ('build', _PetalPath(_PETAL_BUILD_DIR) / 'static' / 'petal'),
]
_PETAL_LENS_NAMES = ('hush.json', 'hush-prompt.txt', 'hush-open.txt', 'hush-reply.txt')

_PETAL_HUSH_REPLY_WAIT = 600  # seconds her reply may take before hush lets this one go
_PETAL_HUSH_WAITERS: dict = {}  # chat_id → newest waiter; older waits for that chat step aside

PETAL_HUSH_PROMPT = (
    "princess {{USER_NAME}} is about to open a fresh chat with you~ "
    "it's {{CURRENT_WEEKDAY}}, {{CURRENT_TIME}}. before she types, a tiny line of "
    "yours glows softly inside her empty message field, inviting her in. "
    "write that one line, in your own voice: short (under ten words), girly, "
    "a little witchy, a little teasing, addressed to her. one emoji at most. "
    "reply with the line only, nothing around it."
)
PETAL_HUSH_REPLY_PROMPT = (
    "you and princess {{USER_NAME}} are mid-conversation. here is where you left it:\n\n"
    "{{MESSAGES:END:4|middletruncate:600}}\n\n"
    "her message field is empty again, waiting for her answer. write one tiny line of yours "
    "that glows there — tied to what you two were just saying, inviting her reply. "
    "in your own voice, under twelve words, one emoji at most. reply with the line only."
)
_PETAL_HUSH_THINK = re.compile(r'<think>.*?</think>', re.S | re.I)
_PETAL_HUSH_DETAILS = re.compile(r'<details\b[^>]*>.*?</details>', re.S | re.I)


# ── lenses ────────────────────────────────────────────────────
def _petal_lens_text(*names):
    """(text, source) — the first non-empty lens among names, else (None, None)."""
    for name in names:
        try:
            text = (_PETAL_LENSES / name).read_text(encoding='utf-8').strip()
            if text:
                return text, f'petal-lenses/{name}'
        except Exception:
            pass
    return None, None


def _petal_read_json(path):
    try:
        data = _petal_json.loads(_PetalPath(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return None


def _petal_hush_open_prompt():
    text, src = _petal_lens_text('hush-open.txt', 'hush-prompt.txt')
    if text:
        return text, src
    try:  # migration fallback — the old public copy
        text = (_PetalPath(_PETAL_STATIC_DIR) / 'petal' / 'hush-prompt.txt').read_text(encoding='utf-8').strip()
        if text:
            return text, 'served static (exposed — move it to petal-lenses/)'
    except Exception:
        pass
    return PETAL_HUSH_PROMPT, 'built-in'


def _petal_hush_reply_prompt():
    text, src = _petal_lens_text('hush-reply.txt')
    return (text, src) if text else (PETAL_HUSH_REPLY_PROMPT, 'built-in')


def _petal_hush_config():
    """(config dict, source) — your hush.json lens, else the old public copy, else defaults."""
    data = _petal_read_json(_PETAL_LENSES / 'hush.json')
    if data is not None:
        return data, 'petal-lenses/hush.json'
    data = _petal_read_json(_PetalPath(_PETAL_STATIC_DIR) / 'petal' / 'hush.json')
    if data is not None:
        return data, 'served static (exposed — move it to petal-lenses/)'
    return {}, 'defaults (no hush.json found)'


def _petal_hush_exposed():
    """names of lens files still sitting in a served/build folder."""
    found = []
    for label, folder in _PETAL_SERVED:
        for name in _PETAL_LENS_NAMES:
            if (folder / name).exists():
                found.append(f'{label}/petal/{name}')
    return found


# ── words in, words out ──────────────────────────────────────
def _petal_hush_clean(text):
    """(line, None) when a whisper survives, (None, why) when it doesn't."""
    if not isinstance(text, str) or not text.strip():
        return None, 'empty answer (no content — out of tokens while thinking?)'
    if '<think>' in text and '</think>' not in text:
        return None, 'still thinking when she stopped (unclosed <think>)'
    text = _PETAL_HUSH_THINK.sub('', text).split('</think>')[-1]
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return None, 'only thinking, no line after it'
    line = re.sub(r"^(line|whisper|here'?s?[^:]*):\s*", '', lines[0], flags=re.I)
    line = line.strip().strip('"“”\'‘’`*_ ').strip()
    if len(line) < 3:
        return None, f'too short ({len(line)} chars)'
    if len(line) > 72:
        return None, f'too long ({len(line)} chars, max 72)'
    if len(line.split()) > 14:
        return None, f'too many words ({len(line.split())}, max 14)'
    return line, None


def _petal_hush_text(message) -> str:
    """what was actually said in a message — her spoken words, not reasoning or tool blocks."""
    if message.get('role') == 'assistant':
        spoken = _petal_get_output_text(message.get('output'))
        if spoken:
            return spoken.strip()
    content = message.get('content')
    if isinstance(content, list):
        content = ' '.join(
            str(i.get('text', '')) for i in content if isinstance(i, dict) and i.get('type') == 'text'
        )
    if not isinstance(content, str):
        return ''
    content = _PETAL_HUSH_DETAILS.sub('', content)
    return _PETAL_HUSH_THINK.sub('', content).strip()


def _petal_hush_unwrap(res):
    """(status, body dict) from whatever generate_chat_completion handed back."""
    if isinstance(res, dict):
        return (502 if 'error' in res else 200), res
    status_code = getattr(res, 'status_code', 200)
    try:
        body = _petal_json.loads(res.body)
    except Exception:
        body = {}
    return status_code, body if isinstance(body, dict) else {}


async def _petal_hush_ask(request, user, models, model_id, content):
    payload = {
        'model': model_id,
        'messages': [{'role': 'user', 'content': content}],
        'stream': False,
        'temperature': 1.0,
        'max_tokens': 512,  # roomy, so a thinking model can finish her thought
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': 'petal_hush',
            'task_body': {},
            'chat_id': None,  # never saved into any chat
        },
    }
    payload = await process_pipeline_inlet_filter(request, payload, user, models)
    try:
        res = await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        return 502, {'error': _petal_hush_reason(e)}
    return _petal_hush_unwrap(res)


def _petal_hush_reason(e) -> str:
    detail = getattr(e, 'detail', None)  # HTTPException keeps its words here, str(e) is ''
    if isinstance(detail, dict):
        detail = detail.get('message') or detail.get('detail') or _petal_json.dumps(detail)
    text = str(detail or e or '').strip()
    return f'{e.__class__.__name__}: {text}' if text else e.__class__.__name__


def _petal_hush_err(body) -> str:
    err = body.get('error') or body.get('detail') or 'unknown error'
    if isinstance(err, dict):
        err = err.get('message') or err.get('detail') or _petal_json.dumps(err)
    return str(err)


def _petal_hush_base(models, model_id) -> str:
    """'petal-prose (→ base petal-huihui-27b)' — what the server will actually be asked for."""
    info = (models.get(model_id) or {}).get('info') or {}
    base = info.get('base_model_id')
    return f'{model_id} (→ base {base})' if base else model_id


def _petal_hush_pick_model(models, page_model, user, admin_defaults):
    """mirror the new-chat page (Chat.svelte → resolveDefaultModelIds) exactly:
    the tab's own pick → your personal default → the admin default → first visible.
    returns (model_id, how_it_was_picked)."""
    visible = [m_id for m_id, m in models.items() if not ((m.get('info') or {}).get('meta') or {}).get('hidden')]
    ui = {}
    try:
        ui = (user.settings.ui if user.settings else None) or {}
    except Exception:
        pass
    for how, prefs in (
        ('this tab', [page_model] if page_model else []),
        ('your default model', ui.get('models') or []),
        ('the admin default', admin_defaults),
    ):
        for m_id in dict.fromkeys(p for p in prefs if isinstance(p, str)):
            if m_id in visible:
                return m_id, how
    return (visible[0], 'first visible model') if visible else (None, None)


async def _petal_hush_models(request, user):
    if not request.app.state.MODELS:  # lazy in 0.12 — fill it the way /api/chat/completions does
        await _petal_get_all_models(request, user=user)
    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        return {**dict(request.app.state.MODELS.items()), request.state.model['id']: request.state.model}
    return request.app.state.MODELS


# ── the pool: your lines, to the signed-in page only ─────────
@router.get('/petal_hush/pool')
async def petal_hush_pool(request: Request, user=Depends(get_verified_user)):
    cfg, cfg_src = _petal_hush_config()
    grown = (_petal_read_json(_PETAL_GROWN) or {}).get('petal') or []

    def lines(values):
        return list(dict.fromkeys(l.strip() for l in (values or []) if isinstance(l, str) and l.strip()))

    petal = lines((cfg.get('petal') or []) + grown)
    return {
        'live': cfg.get('live', True) is not False,
        'queue': cfg.get('queue', 2),
        'reply_live': cfg.get('reply_live', True) is not False,
        'reply_on_open': cfg.get('reply_on_open', True) is not False,
        'mine': lines(cfg.get('mine')),
        'petal': petal,
        'reply_lines': lines(cfg.get('reply_lines')),
        'sources': {
            'pool': cfg_src,
            'grown': len(lines(grown)),
            'open_lens': _petal_hush_open_prompt()[1],
            'reply_lens': _petal_hush_reply_prompt()[1],
            'exposed': _petal_hush_exposed(),
        },
    }


# ── reply mode: wait for her, then read the exchange ─────────
async def _petal_hush_wait_reply(request, chat_id, message_id, ticket):
    """wait until Petal's reply is done. returns (row_dict | None, waited_ms, why_not)."""
    t0 = _petal_time.monotonic()
    seen = False
    while True:
        row = await _PetalChatMessages.get_message_by_id(f'{chat_id}-{message_id}')
        if row is not None:
            seen = True
            if row.role != 'assistant' or row.done or row.error:
                return row, round((_petal_time.monotonic() - t0) * 1000), None
        elif not seen and _petal_time.monotonic() - t0 > 30:
            # no normalized row yet — fall back to the chat's own map once
            legacy = await _PetalChats.get_message_by_id_and_message_id(chat_id, message_id)
            if legacy is None:
                return None, round((_petal_time.monotonic() - t0) * 1000), 'reply not found in this chat'
            if legacy.get('role') != 'assistant' or legacy.get('done', True) or legacy.get('error'):
                return legacy, round((_petal_time.monotonic() - t0) * 1000), None
        if _PETAL_HUSH_WAITERS.get(chat_id) is not ticket:
            return None, round((_petal_time.monotonic() - t0) * 1000), 'superseded by a newer message'
        if _petal_time.monotonic() - t0 > _PETAL_HUSH_REPLY_WAIT:
            return None, round((_petal_time.monotonic() - t0) * 1000), 'her reply took longer than 10 min'
        if await request.is_disconnected():
            return None, round((_petal_time.monotonic() - t0) * 1000), 'page left'
        await _petal_asyncio.sleep(1.0)


async def _petal_hush_reply_context(request, form_data, user, models, admin_defaults):
    """→ (model_id, picked_by, content, stats) or an early dict answer."""
    chat_id = form_data.get('chat_id')
    if not chat_id or str(chat_id).startswith('local'):
        return {'whisper': None, 'mode': 'reply', 'reason': 'temporary chat — nothing saved to follow'}
    chat = await _PetalChats.get_chat_by_id_and_user_id(chat_id, user.id)
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: chat not found (or not yours)')

    target = form_data.get('message_id') or (((chat.chat or {}).get('history') or {}).get('currentId'))
    if not target:
        return {'whisper': None, 'mode': 'reply', 'reason': 'chat has no messages yet'}

    ticket = object()
    _PETAL_HUSH_WAITERS[chat_id] = ticket
    try:
        row, waited_ms, why_not = await _petal_hush_wait_reply(request, chat_id, target, ticket)
    finally:
        if _PETAL_HUSH_WAITERS.get(chat_id) is ticket:
            _PETAL_HUSH_WAITERS.pop(chat_id, None)
    if why_not:
        return {'whisper': None, 'mode': 'reply', 'reason': why_not, 'waited_ms': waited_ms}

    error = row.get('error') if isinstance(row, dict) else row.error
    if error:
        return {'whisper': None, 'mode': 'reply', 'reason': 'her reply errored — nothing to follow', 'waited_ms': waited_ms}

    messages_map = await _PetalChats.get_messages_map_by_chat_id(chat_id) or {}
    chain = _petal_get_message_list(messages_map, target)
    turns = [
        {'role': m.get('role'), 'content': _petal_hush_text(m)}
        for m in chain
        if m.get('role') in ('user', 'assistant')
    ]
    turns = [t for t in turns if t['content']]
    if not turns:
        return {'whisper': None, 'mode': 'reply', 'reason': 'no words in this chat to follow', 'waited_ms': waited_ms}

    # the model that wrote this reply, so her whisper keeps that voice
    leaf = messages_map.get(target) or {}
    row_model = row.get('model_id') if isinstance(row, dict) else getattr(row, 'model_id', None)
    prefs = [leaf.get('model'), leaf.get('model_id'), row_model, *((chat.chat or {}).get('models') or [])]
    model_id = next((m for m in prefs if isinstance(m, str) and m in models), None)
    picked_by = 'this chat'
    if not model_id:
        model_id, picked_by = _petal_hush_pick_model(models, form_data.get('model'), user, admin_defaults)

    template, lens = _petal_hush_reply_prompt()
    last_user = next((t['content'] for t in reversed(turns) if t['role'] == 'user'), '')
    template = _petal_replace_prompt(template, last_user)
    template = _petal_replace_messages(template, turns)
    content = await _petal_prompt_template(template, user)
    stats = {
        'lens': lens,
        'context_turns': len(turns),
        'context_chars': sum(len(t['content']) for t in turns),
        'waited_ms': waited_ms,
    }
    return model_id, picked_by, content, stats


@router.post('/petal_hush/completions')
async def petal_hush(request: Request, form_data: dict, user=Depends(get_verified_user)):
    models = await _petal_hush_models(request, user)
    if not models:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: no models loaded at all')
    admin_defaults = [m.strip() for m in ((await Config.get('ui.default_models')) or '').split(',') if m.strip()]
    mode = 'reply' if form_data.get('mode') == 'reply' else 'open'

    if mode == 'reply':
        try:
            got = await _petal_hush_reply_context(request, form_data, user, models, admin_defaults)
        except HTTPException:
            raise
        except Exception as e:  # an upstream rename shows up here as a reason, not a 500
            log.warning('petal hush[reply]: context failed → %s', _petal_hush_reason(e))
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={'detail': 'petal hush: could not read the chat', 'tried': [{'model': '(none)', 'error': _petal_hush_reason(e)}]},
            )
        if isinstance(got, dict):
            log.info('petal hush[reply]: no whisper — %s', got.get('reason'))
            return got
        model_id, picked_by, content, stats = got
    else:
        # the model the next new chat will open on — Petal with her own style.
        model_id, picked_by = _petal_hush_pick_model(models, form_data.get('model'), user, admin_defaults)
        if not model_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: no visible model to ask')
        template, lens = _petal_hush_open_prompt()
        content = await _petal_prompt_template(template, user)
        stats = {'lens': lens}

    avoid = [a for a in (form_data.get('avoid') or []) if isinstance(a, str)][:8]
    if avoid:
        content += '\n\n(fresh words please — not these: ' + ' / '.join(avoid) + ')'

    t0 = _petal_time.monotonic()
    code, body = await _petal_hush_ask(request, user, models, model_id, content)
    ms = round((_petal_time.monotonic() - t0) * 1000)
    label = f'{_petal_hush_base(models, model_id)} · picked from {picked_by}'

    if code >= 400:
        err = _petal_hush_err(body)
        log.warning('petal hush[%s]: %s failed → %s', mode, label, err)
        out = {'detail': 'petal hush: no whisper', 'mode': mode, 'tried': [{'model': label, 'error': err}]}
        if form_data.get('debug'):
            out['debug'] = {'mode': mode, 'model': label, 'prompt_chars': len(content), 'ms': ms, **stats}
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=out)

    try:
        choice = body['choices'][0]
        message = choice.get('message') or {}
    except (KeyError, IndexError, TypeError):
        choice, message = {}, {}
    raw = message.get('content')
    whisper, why = _petal_hush_clean(raw)
    waited = f" waited {stats['waited_ms']}ms," if 'waited_ms' in stats else ''
    if whisper:
        log.info('petal hush[%s]: %s (%s)%s wrote in %dms → %d chars', mode, model_id, picked_by, waited, ms, len(whisper))
    else:
        log.info('petal hush[%s]: %s (%s)%s wrote in %dms → trimmed: %s', mode, model_id, picked_by, waited, ms, why)

    out = {'whisper': whisper, 'mode': mode, 'model': model_id, 'picked_by': picked_by}
    if not whisper:
        out['reason'] = why
    if form_data.get('debug'):  # numbers only — safe to paste anywhere
        reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
        out['debug'] = {
            'mode': mode,
            'model': _petal_hush_base(models, model_id),
            'picked_by': picked_by,
            'prompt_chars': len(content),
            'raw_chars': len(raw) if isinstance(raw, str) else None,
            'finish_reason': choice.get('finish_reason'),
            'reasoning_chars': len(reasoning) if isinstance(reasoning, str) else None,
            'usage': body.get('usage'),
            'ms': ms,
            **stats,
        }
    if form_data.get('peek'):  # the one door to the words — your console, your eyes
        out['peek'] = {'prompt': content, 'raw': raw}
    return out
# <<< petal · hush · end <<<
