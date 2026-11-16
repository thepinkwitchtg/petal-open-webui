"""
petal_thanks 💗 — her thank-yous (slice A26)

when a verdict lands (POST /api/v1/petal/thumbs → the page's "saved" moment), the toast shows a line Petal wrote
herself, thanking Lily for feeding her: feedback is what she grows from, so she thanks the hand that feeds her.

- **verdict-blind.** one pool for every verdict. the take is handed nothing about the verdict, and the writer's
  ask carries none of it: Petal never learns whether it was 👍🏻 or 👎🏻, nor what the note said
- **fresh.** ~6 lines wait ready in `Petal-App-Data/petal-open-webui/thanks.json` (lines only: no chat text, no
  verdict). each is shown once, then retired into `recent` (the last 50 shown). every take wakes one refill in
  the background; a line equal to (or a near twin of) anything ready or recent is never kept
- **her voice.** the writer runs on the rated reply's model with its card's system prompt, rendered the way OWUI
  renders it for the main Petal (OWUI's variables filled; the forge's live slots {{states}} · {{readout}} ·
  {{slot:…}} left out, since nothing fills them outside a turn; the hour follows the forge's clock switch, as
  hush does), then Lily's ask: `Petal-App-Data/petal-open-webui/thanks-ask.md`, seeded once, read live
- **a polite guest.** a refill waits until vLLM is quiet (her /metrics show nothing running or waiting, and OWUI
  runs no reply, for a quiet stretch) and never while the launcher tucks Petal in (the gentle stop)
- **a worker.** its ask goes out as `User-Agent: petal-open-webui/thanks` (utils/headers.py, from the worker's own
  server-side request): no chat id, no eyes record, never her turn, never training data
- lines ≤ 70 characters; an emoji only if she writes one, set in porcelain tone (🏻)
- `GET /api/v1/petal/thumbs/thanks` (admin, numbers only) · `POST /api/v1/petal/thumbs/thanks/refill` (admin)
"""

import asyncio
import difflib
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

try:
    import fcntl  # one writer at a time across OWUI's processes (Linux, the rig)
except ImportError:  # pragma: no cover
    fcntl = None

import aiohttp
from starlette.requests import Request

log = logging.getLogger(__name__)

CALLER = 'petal-open-webui/thanks'
TARGET = max(1, int(os.getenv('PETAL_THANKS_READY') or 6))  # lines kept ready
RECENT = 50  # shown lines kept, never written again
MAX_CHARS = 70
QUIET_S = float(os.getenv('PETAL_THANKS_QUIET_S') or 5)  # vLLM must stay quiet this long before she writes
PATIENCE_S = float(os.getenv('PETAL_THANKS_PATIENCE_S') or 30 * 60)  # then this refill rests till the next take
POLL_S = 1.0
MAX_FAILURES = 3  # lines in a row that didn't come: the refill rests until the next take
TWIN_RATIO = 0.9

ASK_SEED = """<!-- 💗 her thank-you ask (A26) · read live each time she writes a line. write your own words here:
     the lines she gave lately follow it (so she finds new ones), unless you place {{RECENT}} yourself.
     {{MAX_CHARS}} (70) and OWUI's own {{USER_NAME}} work too. comments like this one never reach her.
     she writes blind on purpose: never put a verdict or a note in here. -->

{{USER_NAME}} just left feedback on one of your replies, and it feeds your growth. \
Write one short line ({{MAX_CHARS}} characters at most) thanking them for feeding you.
"""

_FORGE_SLOTS = re.compile(r'[ \t]?\{\{\s*(?:states|readout|slot:[^{}]*)\s*\}\}')  # (and the space before it)
_COMMENTS = re.compile(r'<!--.*?-->', re.S)
_THINK = re.compile(r'<think>.*?</think>', re.S | re.I)
_DETAILS = re.compile(r'<details\b[^>]*>.*?</details>', re.S | re.I)
_LEAD = re.compile(r"^(?:line|here(?:'s| is)[^:]{0,40})\s*:\s*", re.I)
_INVISIBLE = re.compile('[\u200d\ufe0e\ufe0f\U0001f3fb-\U0001f3ff]')
_TONES = range(0x1F3FB, 0x1F400)
_PORCELAIN = '\U0001f3fb'
# Emoji_Modifier_Base (Unicode emoji-data): the emojis a skin tone sits on (👪 left out: it has no toned form)
# fmt: off
_BASES = (
    (0x261D, 0x261D), (0x26F9, 0x26F9), (0x270A, 0x270D), (0x1F385, 0x1F385), (0x1F3C2, 0x1F3C4),
    (0x1F3C7, 0x1F3C7), (0x1F3CA, 0x1F3CC), (0x1F442, 0x1F443), (0x1F446, 0x1F450), (0x1F466, 0x1F469),
    (0x1F46B, 0x1F478), (0x1F47C, 0x1F47C), (0x1F481, 0x1F483), (0x1F485, 0x1F487), (0x1F48F, 0x1F48F),
    (0x1F491, 0x1F491), (0x1F4AA, 0x1F4AA), (0x1F574, 0x1F575), (0x1F57A, 0x1F57A), (0x1F590, 0x1F590),
    (0x1F595, 0x1F596), (0x1F645, 0x1F647), (0x1F64B, 0x1F64F), (0x1F6A3, 0x1F6A3), (0x1F6B4, 0x1F6B6),
    (0x1F6C0, 0x1F6C0), (0x1F6CC, 0x1F6CC), (0x1F90C, 0x1F90C), (0x1F90F, 0x1F90F), (0x1F918, 0x1F91F),
    (0x1F926, 0x1F926), (0x1F930, 0x1F939), (0x1F93C, 0x1F93E), (0x1F977, 0x1F977), (0x1F9B5, 0x1F9B6),
    (0x1F9B8, 0x1F9B9), (0x1F9BB, 0x1F9BB), (0x1F9CD, 0x1F9CF), (0x1F9D1, 0x1F9DD), (0x1FAC3, 0x1FAC5),
    (0x1FAF0, 0x1FAF8),
)
# fmt: on

_STATE: dict = {'task': None, 'app': None, 'user': None, 'model': None, 'last': None, 'wakes': 0}


# ── where she keeps them ──────────────────────────────────────
def home() -> Path:
    root = Path(os.environ.get('PETAL_APP_DATA') or '~/Gardens/Documents/Petal-App-Data').expanduser()
    return root / 'petal-open-webui'


def _home_ready() -> Path:
    d = home()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _fresh() -> dict:
    return {'v': 1, 'pool': [], 'recent': [], 'written': 0, 'shown': 0}


def _load(d: Path) -> dict:
    p = d / 'thanks.json'
    try:
        doc = json.loads(p.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return _fresh()
    except Exception:
        # an unreadable file is set aside (never deleted) and the pool starts again
        aside = p.with_name(f'thanks.json.broken-{int(time.time())}')
        try:
            p.rename(aside)
            log.warning('💗 petal thanks: thanks.json was unreadable, set aside as %s', aside.name)
        except OSError:
            pass
        return _fresh()
    out = _fresh()
    if isinstance(doc, dict):
        for key in ('pool', 'recent'):
            out[key] = [x for x in (doc.get(key) or []) if isinstance(x, dict) and isinstance(x.get('line'), str)]
        for key in ('written', 'shown'):
            out[key] = int(doc.get(key) or 0) if str(doc.get(key) or 0).isdigit() else 0
    return out


def _save(d: Path, doc: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix='.thanks.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, d / 'thanks.json')
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _mutate(fn):
    """fn(doc) → (result, changed), under the file lock (two OWUI processes never interleave a take)"""
    d = _home_ready()
    with open(d / '.thanks.lock', 'a+') as lock:
        try:
            os.chmod(lock.name, 0o600)
        except OSError:
            pass
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            doc = _load(d)
            result, changed = fn(doc)
            if changed:
                _save(d, doc)
            return result
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _read() -> dict:
    return _mutate(lambda doc: (doc, False))


def ask_text() -> str:
    """Lily's ask, live: seeded once (never over her words), comments left out"""
    p = _home_ready() / 'thanks-ask.md'
    if not p.exists():
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(ASK_SEED)
        except FileExistsError:
            pass
    try:
        text = _COMMENTS.sub('', p.read_text(encoding='utf-8')).strip()
    except OSError:
        text = ''
    return text or _COMMENTS.sub('', ASK_SEED).strip()  # an emptied file still gets her a real ask


# ── the line itself ───────────────────────────────────────────
def visible_len(line: str) -> int:
    return len(_INVISIBLE.sub('', line))


def _is_base(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in _BASES)


def porcelain(text: str) -> str:
    """every emoji that can wear a skin tone wears the porcelain one (🏻); the rest stay as she wrote them"""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        out.append(ch)
        i += 1
        if _is_base(ch):
            nxt = text[i] if i < len(text) else ''
            if nxt and (ord(nxt) in _TONES or nxt == '\ufe0f'):
                i += 1  # her tone (or the presentation mark) gives way to porcelain
            out.append(_PORCELAIN)
    return ''.join(out)


def clean(text) -> tuple[str | None, str | None]:
    """(line, None) when a line survives, (None, why) when it doesn't"""
    if not isinstance(text, str) or not text.strip():
        return None, 'empty answer (out of room while thinking?)'
    if '<think>' in text and '</think>' not in text:
        return None, 'still thinking when she stopped'
    text = _DETAILS.sub('', _THINK.sub('', text)).split('</think>')[-1]
    lines = [row.strip() for row in text.splitlines() if row.strip()]
    if not lines:
        return None, 'only thinking, no line'
    line = re.sub(r'\s+', ' ', _unquote(_LEAD.sub('', lines[0]).strip()))
    n = visible_len(line)
    if n < 3:
        return None, f'too short ({n} chars)'
    if n > MAX_CHARS:
        return None, f'too long ({n} chars, max {MAX_CHARS})'
    return line, None


_QUOTES = {'"': '"', '“': '”', '”': '”', "'": "'", '‘': '’', '`': '`'}


def _unquote(line: str) -> str:
    """one pair of wrapping quotes (or a whole-line *…* / **…**) comes off; her own asterisks stay"""
    if len(line) >= 2 and line[0] in _QUOTES and line[-1] == _QUOTES[line[0]]:
        line = line[1:-1].strip()
    for mark in ('**', '*', '_'):
        inner = line[len(mark) : -len(mark)]
        if len(line) > 2 * len(mark) and line.startswith(mark) and line.endswith(mark) and mark not in inner:
            return inner.strip()
    return line


def _key(line: str) -> str:
    return ' '.join(re.findall(r'\w+', line.casefold()))


def twin(line: str, others: list) -> str | None:
    """why a line can't be kept beside these (already said · a near twin), else None"""
    key = _key(line)
    if not key:
        return 'no words in it'
    for other in others:
        k = _key(other)
        if key == k:
            return 'already said lately'
        if difflib.SequenceMatcher(None, key, k).ratio() >= TWIN_RATIO:
            return 'a near twin of a line said lately'
    return None


def _lines(doc: dict) -> list:
    return [x['line'] for x in doc['pool']] + [x['line'] for x in doc['recent']]


# ── the take: the saved moment (no model call, ever) ──────────
def _pop(doc: dict):
    if not doc['pool']:
        return None, False
    item = doc['pool'].pop(0)
    doc['recent'].append({'line': item['line'], 'at': item.get('at'), 'shown_at': int(time.time())})
    doc['recent'] = doc['recent'][-RECENT:]
    doc['shown'] += 1
    return item['line'], True


async def take(request: Request, user, model_id: str | None = None) -> str | None:
    """the next ready line, shown once and retired · None when the pool is empty or anything fails (the page
    says its plain thanks). knows nothing of the verdict. wakes one refill in the background"""
    line = None
    try:
        line = await asyncio.to_thread(_mutate, _pop)
    except Exception as e:
        log.warning('💗 petal thanks: the pool could not be read (%s) — the plain thanks', type(e).__name__)
    try:
        wake(request.app, user, model_id)
    except Exception as e:
        log.warning('💗 petal thanks: no refill (%s)', type(e).__name__)
    return line


# ── the refill: one line at a time, when vLLM is quiet ────────
def wake(app, user, model_id: str | None = None) -> None:
    _STATE.update(app=app, user=user, wakes=_STATE['wakes'] + 1)
    if isinstance(model_id, str) and model_id:
        _STATE['model'] = model_id
    task = _STATE['task']
    if task is None or task.done():
        _STATE['task'] = asyncio.create_task(_refill())


def writing() -> bool:
    task = _STATE['task']
    return bool(task and not task.done())


async def status() -> dict:
    doc = await asyncio.to_thread(_read)
    return {
        'ready': len(doc['pool']),
        'target': TARGET,
        'recent': len(doc['recent']),
        'written': doc['written'],
        'shown': doc['shown'],
        'writing': writing(),
        'last': _STATE['last'],
    }


def _worker_request(app) -> Request:
    """a request of its own, so OWUI's model door names the worker and nothing of a page's request rides along"""
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.0'},
        'method': 'POST',
        'path': '/api/v1/petal/thumbs/thanks',
        'raw_path': b'/api/v1/petal/thumbs/thanks',
        'query_string': b'',
        'headers': [],
        'client': ('127.0.0.1', 0),
        'server': ('127.0.0.1', 80),
        'scheme': 'http',
        'app': app,
    }
    request = Request(scope)
    request.state.petal_caller = CALLER  # utils/headers.py: User-Agent petal-open-webui/thanks
    return request


async def _models(request: Request, user) -> dict:
    if not request.app.state.MODELS:  # lazy since 0.12: fill it the way /api/chat/completions does
        from open_webui.utils.models import get_all_models

        await get_all_models(request, user=user)
    return dict(request.app.state.MODELS.items())


async def _pick(request: Request, models: dict, wanted: str | None, user) -> str | None:
    """the rated reply's model (her voice there), else hers by default, else the admin's, else the first shown"""
    from open_webui.models.config import Config

    visible = [m for m, info in models.items() if not ((info.get('info') or {}).get('meta') or {}).get('hidden')]
    try:
        ui = (user.settings.ui if user.settings else None) or {}
    except Exception:
        ui = {}
    admin = [m.strip() for m in ((await Config.get('ui.default_models')) or '').split(',') if m.strip()]
    if wanted and wanted not in models:  # a card made since the cache was built: look once more, as a chat would
        from open_webui.utils.models import get_all_models

        await get_all_models(request, user=user)
        models = dict(request.app.state.MODELS.items())
    for prefs in ([wanted] if wanted else [], ui.get('models') or [], admin):
        for m in dict.fromkeys(p for p in prefs if isinstance(p, str)):
            if m in models:
                return m
    return visible[0] if visible else None


def _hour_hidden() -> bool:
    """the forge's clock switch, through hush's own reader (ch11 §11.7) · no reader or any error → hidden"""
    try:
        from open_webui.routers import tasks

        return bool(tasks._petal_clock_hidden()[0])
    except Exception:
        return True


def _hide_hour(text: str) -> str:
    try:
        from open_webui.routers import tasks

        return tasks._petal_hush_hide_hour(text)
    except Exception:
        text = text.replace('{{CURRENT_DATETIME}}', '{{CURRENT_DATE}}')
        return re.sub(r'[ \t]*(?:,|·|\bat\b)?[ \t]*\{\{CURRENT_TIME\}\}', '', text)


def _metrics_url(base: str) -> str:
    b = base.rstrip('/')
    if b.endswith('/v1'):
        b = b[: -len('/v1')]
    return f'{b}/metrics'


async def _vllm_load(session: aiohttp.ClientSession, url: str | None) -> float | None:
    """running + waiting at Petal's vLLM, None when there's no /metrics to read"""
    if not url:
        return None
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as r:
            if r.status >= 400:
                return None
            text = await r.text()
    except Exception:
        return None
    total, seen = 0.0, False
    for row in text.splitlines():
        if row.startswith(('vllm:num_requests_running', 'vllm:num_requests_waiting')):
            try:
                total += float(row.rsplit(' ', 1)[1])
                seen = True
            except (IndexError, ValueError):
                continue
    return total if seen else None


async def _owui_busy(app) -> int:
    try:
        from open_webui.tasks import list_tasks

        return len(await list_tasks(getattr(app.state, 'redis', None)))
    except Exception:
        return 0


async def _live_stop(session: aiohttp.ClientSession) -> bool:
    """the gentle stop holds her, unless its file is stale (the launcher silent), the way a chat sees it"""
    from open_webui.utils import petal_gentle_stop

    if petal_gentle_stop.read_stop() is None:
        return False
    return await petal_gentle_stop._ok(session, petal_gentle_stop.LAUNCHER_HEALTH)


async def _wait_quiet(app, request: Request, user, model_id: str) -> bool:
    """the polite guest: True once vLLM stayed quiet for QUIET_S, False after PATIENCE_S of waiting"""
    from open_webui.utils import petal_gentle_stop

    try:
        base = await petal_gentle_stop.petal_base_url(request, (await _models(request, user)).get(model_id))
    except Exception:
        base = None
    url = _metrics_url(base) if base else None
    t0, quiet_since = time.monotonic(), None
    async with aiohttp.ClientSession() as session:
        while True:
            quiet = not await _live_stop(session) and await _owui_busy(app) == 0
            if quiet:
                load = await _vllm_load(session, url)
                quiet = load is None or load == 0
            now = time.monotonic()
            if quiet:
                quiet_since = quiet_since or now
                if now - quiet_since >= QUIET_S:
                    return True
            else:
                quiet_since = None
            if now - t0 > PATIENCE_S:
                return False
            await asyncio.sleep(POLL_S)


def _unwrap(res) -> tuple[int, dict]:
    if isinstance(res, dict):
        return (502 if 'error' in res else 200), res
    code = getattr(res, 'status_code', 200)
    try:
        body = json.loads(res.body)
    except Exception:
        body = {}
    return code, body if isinstance(body, dict) else {}


async def _messages(request: Request, user, model_id: str, doc: dict, hidden: bool, nudge: str = '') -> list:
    """her card's system prompt as OWUI renders it for the main Petal, then Lily's ask · nothing of any chat"""
    from open_webui.models.models import Models
    from open_webui.utils.payload import resolve_system_prompt
    from open_webui.utils.task import prompt_template

    said = [x['line'] for x in doc['pool']] + [x['line'] for x in doc['recent'][-8:]]
    ask = ask_text()
    listed = '\n'.join(f'- {said_line}' for said_line in said) or '(none yet)'
    if '{{RECENT}}' in ask:
        ask = ask.replace('{{RECENT}}', listed)
    elif said:
        ask += f'\n\nlines you gave me lately (never repeat one):\n{listed}'
    ask = ask.replace('{{MAX_CHARS}}', str(MAX_CHARS)) + nudge
    if hidden:
        ask = _hide_hour(ask)
    ask = await prompt_template(ask, user)

    system = ''
    card = await Models.get_model_by_id(model_id)
    params = card.params.model_dump() if card and card.params else {}
    template = params.get('system') if isinstance(params.get('system'), str) else ''
    if template:
        template = _FORGE_SLOTS.sub('', template)
        if hidden:
            template = _hide_hour(template)
        system = await resolve_system_prompt(template, {'variables': {}, 'chat_variables': {}}, user)
    return ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': ask}]


async def _write_one(app, user, wanted: str | None) -> tuple[str | None, str | None, str | None]:
    """(line, None, model) when she wrote a keeper, (None, why, model) when she didn't · two asks at most"""
    from open_webui.utils.chat import generate_chat_completion

    request = _worker_request(app)
    models = await _models(request, user)
    model_id = await _pick(request, models, wanted, user)
    if not model_id:
        return None, 'no model to ask', None
    if not await _wait_quiet(app, request, user, model_id):
        return None, 'vLLM never went quiet', model_id
    hidden = await asyncio.to_thread(_hour_hidden)
    nudge, why = '', None
    for _ in range(2):
        async with aiohttp.ClientSession() as session:
            if await _live_stop(session):
                return None, 'gentle stop — Petal is resting', model_id
        doc = await asyncio.to_thread(_read)
        payload = {
            'model': model_id,
            'messages': await _messages(request, user, model_id, doc, hidden, nudge),
            'stream': False,
            'temperature': 1.0,
            'max_tokens': 1024,  # roomy, so a thinking model finishes her thought before the line
            'metadata': {'task': 'petal_thanks', 'task_body': {}, 'chat_id': None},  # never saved into any chat
        }
        try:
            res = await generate_chat_completion(request, form_data=payload, user=user, bypass_system_prompt=True)
        except Exception as e:
            return None, f'{type(e).__name__}', model_id
        code, body = _unwrap(res)
        if code >= 400:
            return None, f'the model answered {code}', model_id
        try:
            raw = (body['choices'][0].get('message') or {}).get('content')
        except (KeyError, IndexError, TypeError, AttributeError):
            raw = None
        line, why = clean(raw)
        if line:
            line = porcelain(line)
            why = twin(line, _lines(doc))
            if not why:
                return line, None, model_id
        nudge = f'\n\n(that one was {why}: a brand new line please, in a new shape, at most {MAX_CHARS} characters)'
    return None, why, model_id


def _keep(line: str, model_id: str | None):
    def put(doc):
        if len(doc['pool']) >= TARGET or twin(line, _lines(doc)):
            return False, False  # another writer filled it meanwhile, or wrote her twin
        doc['pool'].append({'line': line, 'at': int(time.time()), 'by': model_id})
        doc['written'] += 1
        return True, True

    return put


class _RefillLock:
    """one refill across OWUI's processes: the file lock is held while she writes, others step aside"""

    def __init__(self, d: Path):
        self.file = open(d / '.refill.lock', 'a+')
        try:
            os.chmod(self.file.name, 0o600)
        except OSError:
            pass

    def acquire(self) -> bool:
        if not fcntl:
            return True
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def release(self) -> None:
        try:
            if fcntl:
                fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
        except OSError:
            pass


async def _one_more() -> str | None:
    """write one line and keep it · None when kept, else why not"""
    app, user, wanted = _STATE['app'], _STATE['user'], _STATE['model']
    t0 = time.monotonic()
    line, why, model_id = await _write_one(app, user, wanted)
    ms = round((time.monotonic() - t0) * 1000)
    if line and await asyncio.to_thread(_mutate, _keep(line, model_id)):
        _STATE['last'] = {'at': int(time.time()), 'ok': True, 'chars': visible_len(line), 'ms': ms}
        log.info('💗 petal thanks: a new line (%d chars, %d ms)', visible_len(line), ms)
        return None
    why = why or 'kept elsewhere'
    _STATE['last'] = {'at': int(time.time()), 'ok': False, 'why': why, 'ms': ms}
    log.info('💗 petal thanks: no line this time — %s', why)
    return why


async def _refill() -> None:
    lock = None
    try:
        lock = _RefillLock(await asyncio.to_thread(_home_ready))
        if not lock.acquire():
            return  # another OWUI process is writing her lines
        failures = 0
        while failures < MAX_FAILURES and len((await asyncio.to_thread(_read))['pool']) < TARGET:
            why = await _one_more()
            if why is None:
                failures = 0
            elif why in ('vLLM never went quiet', 'no model to ask'):
                return  # the next take wakes her again
            else:
                failures += 1
    except Exception as e:
        _STATE['last'] = {'at': int(time.time()), 'ok': False, 'why': type(e).__name__}
        log.warning('💗 petal thanks: the refill stopped (%s)', type(e).__name__)
    finally:
        if lock:
            lock.release()
