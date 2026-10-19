

# >>> petal · hush · begin >>>
##################################
#
# 🌸 petal · hush  ·  v0.7  (petal-patch, grafted by petal-hush-apply.sh)
# Petal writes the whisper in the empty chat field, at runtime.
# called directly through generate_chat_completion, like title
# generation — never through the chat pipeline, so memory injection, background review and the
# ledger never see it. nothing is saved to any chat.
#
# v0.3 · model resolution now mirrors titles exactly
#        (chat model → task model, local OR external),
#        pipeline inlet filters run like they do for titles,
#        upstream errors come back loud with the model name,
#        and a stale task model falls back to the chat's own.
# v0.4 · every failure names its model AND its real reason
#        (HTTPException details were being swallowed), and the
#        chat model is resolved to its base for the log.
# v0.5 · app.state.MODELS is filled lazily in 0.12 — chat fills
#        it, titles ride after a chat, but hush fires on page
#        load into an empty dict. we now fill it like chat does.
# v0.6 · the model is picked exactly like a new chat picks it
#        (tab → your default → admin default → first visible),
#        and Petal is asked in HER OWN model — no task-model
#        swap — so her system prompt + params shape every line.
# v0.7 · a trimmed answer says WHY ('reason'), and the page's
#        debug mode gets what the server saw: the prompt sent,
#        her raw words, finish_reason, how much she reasoned.
#
##################################

import json as _petal_json
import time as _petal_time

from open_webui.env import STATIC_DIR as _PETAL_STATIC_DIR
from open_webui.utils.models import get_all_models as _petal_get_all_models
from open_webui.utils.task import prompt_template as _petal_prompt_template

PETAL_HUSH_PROMPT = (
    "princess {{USER_NAME}} is about to open a fresh chat with you~ "
    "it's {{CURRENT_WEEKDAY}}, {{CURRENT_TIME}}. before she types, a tiny line of "
    "yours glows softly inside her empty message field, inviting her in. "
    "write that one line, in your own voice: short (under ten words), girly, "
    "a little witchy, a little teasing, addressed to her. one emoji at most. "
    "reply with the line only, nothing around it."
)
_PETAL_HUSH_THINK = re.compile(r'<think>.*?</think>', re.S | re.I)


def _petal_hush_prompt() -> str:
    """static/petal/hush-prompt.txt wins if present — edit it live, no restart."""
    try:
        text = (_PETAL_STATIC_DIR / 'petal' / 'hush-prompt.txt').read_text(encoding='utf-8').strip()
        if text:
            return text
    except Exception:
        pass
    return PETAL_HUSH_PROMPT


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
            'chat_id': None,
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
    """'petal-prose (→ base petal-omni)' — what the server will actually be asked for."""
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


@router.post('/petal_hush/completions')
async def petal_hush(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if not request.app.state.MODELS:  # lazy in 0.12 — fill it the way /api/chat/completions does
        await _petal_get_all_models(request, user=user)
    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {**dict(request.app.state.MODELS.items()), request.state.model['id']: request.state.model}
    else:
        models = request.app.state.MODELS
    if not models:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: no models loaded at all')

    # the model the next new chat will open on — Petal with her own style.
    # no task-model swap: titles want a cheap voice, whispers want HER voice,
    # and calling the derived model makes OWUI apply its system prompt + params.
    admin_defaults = [m.strip() for m in ((await Config.get('ui.default_models')) or '').split(',') if m.strip()]
    model_id, picked_by = _petal_hush_pick_model(models, form_data.get('model'), user, admin_defaults)
    if not model_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='petal hush: no visible model to ask')

    content = await _petal_prompt_template(_petal_hush_prompt(), user)
    avoid = [a for a in (form_data.get('avoid') or []) if isinstance(a, str)][:8]
    if avoid:
        content += '\n\n(fresh words please — not these: ' + ' / '.join(avoid) + ')'

    t0 = _petal_time.monotonic()
    code, body = await _petal_hush_ask(request, user, models, model_id, content)
    if code >= 400:
        err = _petal_hush_err(body)
        label = f'{_petal_hush_base(models, model_id)} · picked from {picked_by}'
        log.warning('petal hush: %s failed → %s', label, err)
        content_out = {'detail': 'petal hush: no whisper', 'tried': [{'model': label, 'error': err}]}
        if form_data.get('debug'):
            content_out['debug'] = {'model': label, 'prompt': content, 'error': err,
                                    'ms': round((_petal_time.monotonic() - t0) * 1000)}
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=content_out)

    try:
        choice = body['choices'][0]
        message = choice.get('message') or {}
    except (KeyError, IndexError, TypeError):
        choice, message = {}, {}
    raw = message.get('content')
    whisper, why = _petal_hush_clean(raw)
    ms = round((_petal_time.monotonic() - t0) * 1000)
    if whisper:
        log.info('petal hush: %s (%s) in %dms → %r', model_id, picked_by, ms, whisper)
    else:
        log.info('petal hush: %s (%s) in %dms → trimmed: %s', model_id, picked_by, ms, why)

    out = {'whisper': whisper, 'model': model_id, 'picked_by': picked_by}
    if not whisper:
        out['reason'] = why
    if form_data.get('debug'):
        reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
        out['debug'] = {
            'model': _petal_hush_base(models, model_id),
            'picked_by': picked_by,
            'prompt': content,
            'raw': raw if isinstance(raw, str) else raw,
            'finish_reason': choice.get('finish_reason'),
            'reasoning_chars': len(reasoning) if isinstance(reasoning, str) else None,
            'usage': body.get('usage'),
            'ms': ms,
        }
    return out
# <<< petal · hush · end <<<
