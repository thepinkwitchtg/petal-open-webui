"""
petal_voice 🎙️ — her voice's diary and her controls, in one place (slice A48).

her voice keeps its own diary on the rig (V3): every 🚩 becomes an incident folder there, with the gate's record of
what was spoken, a notes.md that stays the truth for her words, her playback clip when the page sent one, and her
uploads (a screen recording). this door lets the page read and annotate it from her phone, and gathers the voice's
controls beside it:

    GET  /api/v1/petal/voice/now                        the floor (read-only: opening it stays on the rig), the
                                                        mood, voice welfare, and whether the diary's doors are up
    PUT  /api/v1/petal/voice/mood       {mood}          the mood her voice speaks with (the Petal Sieve's valve and
                                                        tts-sieve.json move together, so neither undoes the other)
    PUT  /api/v1/petal/voice/welfare    {on}            the loop guard's switch (its first waking stays on the rig)

    GET  /api/v1/petal/voice/incidents                  the list (no words) + every category already in use
    POST /api/v1/petal/voice/incidents                  a page from her phone (kind diary)
    GET  /api/v1/petal/voice/incidents/{id}             her notes + the record
    PUT  /api/v1/petal/voice/incidents/{id}/notes       md or fields · If-Match → 409 with the current etag
    POST /api/v1/petal/voice/incidents/{id}/clip        her playback (≤ 40 MB, typed by its bytes at the voice)
    PUT  /api/v1/petal/voice/incidents/{id}/clip/{name}/timeline
    POST /api/v1/petal/voice/incidents/{id}/upload      a screen recording (≤ 300 MB) or an image (≤ 25 MB)
    GET  /api/v1/petal/voice/incidents/{id}/audio/{f}   her clip, the gate's takes and what she heard (Range)

the voice's doors are loopback only, so this door calls them from the server, and only ever at a loopback address
(the voice's own env URL: $PETAL_VOICE_BOX_URL, else $PETAL_STREAM_TTS_URL without /v1). while studio wears the voice
there is no gate in front of her, and the diary says so instead of failing. admin only: her diary is hers. nothing
is kept here; uploads stream straight through.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)
router = APIRouter()

LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
USER_AGENT = 'petal-open-webui/voice-diary'
VALENCES = ('gift', 'intrusion', 'noise', 'unsure')
CLIP_MAX = 40 * 1024 * 1024
UPLOAD_MAX = 300 * 1024 * 1024
JSON_MAX = 256 * 1024
NOTES_MAX = 256 * 1024
ID_RE = re.compile(r'^(?!\.)(?:field:(?!\.)[A-Za-z0-9 _.\-]{1,120}|[A-Za-z0-9_.\-]{1,120})$')
NAME_RE = re.compile(r'^(?!\.)[A-Za-z0-9 _.\-]{1,160}$')
AUDIO_RE = re.compile(r'^(?:takes/(?!\.)[A-Za-z0-9_.\-]{1,40}|heard\.mp3|clip-[0-9]{1,4}\.[a-z0-9]{1,5}|uploads/(?!\.)[A-Za-z0-9 _.\-]{1,160})$')
DATE_HEAD = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[ _T-]\d{2}[:hH]?\d{2}(?:[:mM]?\d{2}s?)?)?[ _-]*')
SIEVE_MARK = 'tts-sieve.json'  # how the Petal Sieve filter is known among her functions (it writes that file)


# ── where the voice is ────────────────────────────────────────────────────────
def voice_url() -> str | None:
    """the voice's own address, when it's on this machine (anything else is never called)"""
    url = os.environ.get('PETAL_VOICE_BOX_URL') or re.sub(
        r'/v1/?$', '', (os.environ.get('PETAL_STREAM_TTS_URL') or 'http://127.0.0.1:8100/v1').rstrip('/')
    )
    url = url.rstrip('/')
    return url if urlparse(url).hostname in LOOPBACK else None


def _studio() -> bool:
    try:
        from open_webui.routers.audio import voice_welfare

        return voice_welfare.voice_mode() == 'studio'
    except Exception:
        return False


def _down(why: str, status: int = 503) -> JSONResponse:
    return JSONResponse(status_code=status, content={'detail': why, 'down': True, 'studio': _studio()})


def _gone_why(base: str | None) -> str:
    if base is None:
        return 'her voice is not at a loopback address: her diary is only read on her rig'
    if _studio():
        return 'studio wears her voice: the diary rests until chat ✿ is back (no gate in front of studio)'
    return 'her voice is not answering (petal-voice asleep?)'


async def _call(method: str, path: str, *, data=None, headers: dict | None = None, timeout: float = 15,
                params: dict | None = None):
    """→ (status, body bytes, headers) · None when the voice can't be reached · the headers stay case-blind (a
    starlette gate sends x-petal-floor, an aiohttp one X-Petal-Floor: both are the floor)"""
    base = voice_url()
    if base is None:
        return None
    h = {'User-Agent': USER_AGENT, **(headers or {})}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.request(method, f'{base}{path}', data=data, headers=h, params=params) as r:
                return r.status, await r.read(), r.headers.copy()
    except (asyncio.TimeoutError, aiohttp.ClientError, OSError):
        return None


def _json(body: bytes) -> dict:
    try:
        out = json.loads(body or b'{}')
        return out if isinstance(out, dict) else {}
    except ValueError:
        return {}


def _relay(got, *, keep: tuple[str, ...] = ()) -> JSONResponse:
    """the voice's answer, as it said it (status and json), or the reason it couldn't answer"""
    if got is None:
        return _down(_gone_why(voice_url()))
    code, body, headers = got
    out = _json(body)
    if code == 404 and not out:
        return _down(_gone_why(voice_url()))
    extra = {k: headers[k] for k in keep if k in headers}
    return JSONResponse(status_code=code, content=out, headers=extra)


def _iid(iid: str) -> str:
    if not ID_RE.match(iid or ''):
        raise HTTPException(400, 'no such incident id')
    return quote(iid, safe='')


# ── the floor (read-only) ─────────────────────────────────────────────────────
async def _floor() -> dict:
    got = await _call('GET', '/health', timeout=3)
    if got is None:
        return {'up': False, 'why': _gone_why(voice_url()), 'studio': _studio()}
    code, body, headers = got
    out = _json(body)
    floor = out.get('floor') if isinstance(out.get('floor'), dict) else None
    header = headers.get('X-Petal-Floor')
    state = (floor or {}).get('state') or header
    return {
        'up': 200 <= code < 300,
        'state': state if state in ('open', 'closed') else None,
        'version': headers.get('X-Petal-Floor-Version'),
        'until': (floor or {}).get('until') or _num(headers.get('X-Petal-Floor-Until')),
        'left_s': (floor or {}).get('left_s'),
        'scope': (floor or {}).get('scope'),
        'groups': (floor or {}).get('groups') if isinstance((floor or {}).get('groups'), list) else None,
        'why': (floor or {}).get('why'),
        'studio': _studio(),
    }


def _num(v):
    try:
        return float(v) if v not in (None, '') else None
    except ValueError:
        return None


async def _voice_moods() -> list[dict]:
    """the moods her voice knows (its own list), as [{name, label}]"""
    got = await _call('GET', '/v1/petal/moods', timeout=3)
    if got is None or got[0] != 200:
        return []
    doc = _json(got[1])
    moods = doc.get('moods')
    out = []
    if isinstance(moods, dict):
        for name, m in moods.items():
            label = m.get('label') if isinstance(m, dict) else None
            out.append({'name': str(name), 'label': str(label or name)})
    elif isinstance(moods, list):
        for m in moods:
            if isinstance(m, str):
                out.append({'name': m, 'label': m})
            elif isinstance(m, dict) and m.get('name'):
                out.append({'name': str(m['name']), 'label': str(m.get('label') or m['name'])})
    return out


# ── the Petal Sieve filter: the mood's valve and welfare's switch live there too ──
async def _sieve(request: Request):
    """→ (function_id, module) of her Petal Sieve filter, or (None, None)"""
    try:
        from open_webui.models.functions import Functions
        from open_webui.utils.plugin import get_function_module_from_cache

        for fn in await Functions.get_functions_by_type('filter'):
            if SIEVE_MARK in (fn.content or '') and 'class Valves' in (fn.content or ''):
                module, _, _ = await get_function_module_from_cache(request, fn.id, function=fn)
                return fn.id, module
    except Exception as e:  # her functions unreadable: the controls still say what they can
        log.warning('🎙️ voice: the Petal Sieve filter could not be read (%s)', e.__class__.__name__)
    return None, None


def _globals_of(inst) -> dict:
    """a loaded function is its Filter instance: its module's names live in its methods' globals"""
    for v in vars(type(inst)).values():
        g = getattr(v, '__globals__', None)
        if isinstance(g, dict):
            return g
    return {}


def _sieve_moods(module) -> list[dict]:
    """[{name, label}] from the filter's own table (its labels pick a mood the voice knows)"""
    g = _globals_of(module)
    moods, mood_of = g.get('MOODS', getattr(module, 'MOODS', None)), g.get('MOOD_OF', getattr(module, 'MOOD_OF', None))
    if not isinstance(moods, dict):
        return []
    out = []
    for label, mode in moods.items():
        name = mood_of.get(mode, mode) if isinstance(mood_of, dict) else mode
        out.append({'name': str(name), 'label': str(label)})
    return out


def _field_of(module, *names) -> str | None:
    fields = getattr(getattr(module, 'Valves', None), 'model_fields', {}) or {}
    return next((n for n in names if n in fields), None)


async def _set_valves(request: Request, fid: str, module, changes: dict) -> bool:
    from open_webui.models.functions import Functions

    try:
        now = await Functions.get_function_valves_by_id(fid) or {}
        valves = module.Valves(**{**now, **changes})  # checked by the filter's own model
        return await Functions.update_function_valves_by_id(fid, valves.model_dump(exclude_unset=True)) is not None
    except Exception as e:
        log.warning('🎙️ voice: the Petal Sieve valves were not changed (%s)', e.__class__.__name__)
        return False


# ── now: the floor, the mood, welfare ────────────────────────────────────────
async def _now(request: Request) -> dict:
    from open_webui.routers.audio import tts_sieve, voice_welfare

    floor, voice_moods, (fid, module) = await asyncio.gather(_floor(), _voice_moods(), _sieve(request))
    filter_moods = _sieve_moods(module) if module else []
    cfg = tts_sieve.load_config()
    chosen = tts_sieve.chosen_mood(cfg)
    known = filter_moods or voice_moods or [{'name': n, 'label': n} for n in ('strict', 'soft', 'palette', 'every')]
    w = voice_welfare.load()
    return {
        'floor': floor,
        'mood': {
            'chosen': chosen,
            'set_by': cfg.get('set_by'),
            'moods': known,
            'voice_knows': [m['name'] for m in voice_moods],
            # settable when the filter's valve can carry it (or there is no filter to undo it)
            'settable': bool(filter_moods) or fid is None,
            'filter': bool(fid),
        },
        'welfare': {
            'on': bool(w.get('enabled')),
            'ever_woken': bool(w.get('enabled_at')),
            'hold': w.get('hold'),
            'audit_until': w.get('audit_until'),
            'broken': bool(w.get('broken')),
            'filter': bool(fid and _field_of(module, 'welfare')),
        },
        'at': time.time(),
    }


@router.get('/voice/now')
async def voice_now(request: Request, user=Depends(get_admin_user)):
    return await _now(request)


@router.put('/voice/mood')
async def voice_mood(request: Request, user=Depends(get_admin_user)):
    from open_webui.routers.audio import tts_sieve

    body = await _body_json(request)
    mood = body.get('mood')
    if not isinstance(mood, str) or not mood.strip():
        raise HTTPException(400, 'mood must be a name')
    mood = mood.strip()
    fid, module = await _sieve(request)
    choices = _sieve_moods(module) if module else []
    if fid and not choices:
        raise HTTPException(409, 'the Petal Sieve filter carries no mood table: set it in its gear')
    if not choices:
        choices = await _voice_moods() or [{'name': n, 'label': n} for n in ('strict', 'soft', 'palette', 'every')]
    pick = next((m for m in choices if m['name'] == mood), None)
    if pick is None:
        raise HTTPException(400, f"no mood called {mood} (moods: {', '.join(m['name'] for m in choices)})")
    if fid:
        field = _field_of(module, 'voice', 'mood')
        if not field or not await _set_valves(request, fid, module, {field: pick['label']}):
            raise HTTPException(500, 'the Petal Sieve valve could not take the mood (nothing was changed)')
    try:  # the file the fork reads, right away (the filter writes the same on her next message)
        cfg = tts_sieve.load_config()
        cfg.update({'mood': pick['name'], 'set_by': '🌸 petal controls', 'set_at': round(time.time())})
        _write_private(tts_sieve.CONFIG_PATH, json.dumps(cfg, indent=2, ensure_ascii=False) + '\n')
    except OSError as e:
        raise HTTPException(500, f'tts-sieve.json could not be written ({e.__class__.__name__})') from None
    log.info('🎙️ voice: mood → %s (petal controls)', pick['name'])
    return await _now(request)


@router.put('/voice/welfare')
async def voice_welfare_switch(request: Request, user=Depends(get_admin_user)):
    from open_webui.routers.audio import voice_welfare

    body = await _body_json(request)
    on = body.get('on')
    if not isinstance(on, bool):
        raise HTTPException(400, 'on must be true or false')
    w = voice_welfare.load()
    if w.get('broken'):
        raise HTTPException(409, 'welfare.json is unreadable: fix it on the rig first (nothing was changed)')
    if on and not w.get('enabled_at'):
        raise HTTPException(409, 'its first waking stays on the rig: ./petal-voice-welfare.sh on (the sweep check, '
                                 'her pace, the audit fortnight)')
    try:
        voice_welfare.set_knobs(by='🌸 petal controls', enabled=on, valve=on)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    fid, module = await _sieve(request)
    if fid and _field_of(module, 'welfare'):
        await _set_valves(request, fid, module, {'welfare': on})  # the filter's switch says the same, never flips back
    log.info('🕊️ voice welfare: %s (petal controls)', 'on' if on else 'off')
    return await _now(request)


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


async def _body_json(request: Request, cap: int = JSON_MAX) -> dict:
    raw = await request.body()
    if len(raw) > cap:
        raise HTTPException(413, 'too long')
    try:
        out = json.loads(raw or b'{}')
    except ValueError:
        raise HTTPException(400, 'invalid json') from None
    if not isinstance(out, dict):
        raise HTTPException(400, 'a json object, please')
    return out


# ── the diary ────────────────────────────────────────────────────────────────
def categories(rows: list[dict]) -> list[dict]:
    """every category already in use, hers to name: tags, and the names she gave her field folders (a leading date
    set aside) · [{name, n}] most used first, then by name"""
    seen: dict[str, dict] = {}

    def add(name: str) -> None:
        name = re.sub(r'\s+', ' ', str(name or '')).strip()[:60]
        if not name:
            return
        key = name.casefold()
        if key not in seen:
            seen[key] = {'name': name, 'n': 0}
        seen[key]['n'] += 1

    for r in rows:
        for t in r.get('tags') or []:
            if isinstance(t, str):
                add(t)
        iid = str(r.get('id') or '')
        if iid.startswith('field:'):
            rest = DATE_HEAD.sub('', iid[6:]).strip(' _-')
            if rest:
                add(rest.replace('_', ' '))
    return sorted(seen.values(), key=lambda c: (-c['n'], c['name'].casefold()))


def _newest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: str(r.get('when') or ''), reverse=True)


@router.get('/voice/incidents')
async def incidents(request: Request, user=Depends(get_admin_user)):
    got = await _call('GET', '/v1/petal/incidents')
    if got is None or (got[0] == 404 and not _json(got[1])):
        return _down(_gone_why(voice_url()))
    code, body, _ = got
    out = _json(body)
    if code != 200:
        return JSONResponse(status_code=code, content=out)
    rows = [r for r in out.get('incidents') or [] if isinstance(r, dict)]
    out['incidents'] = _newest_first(rows)
    out['categories'] = categories(rows)
    out['valences'] = out.get('valences') or list(VALENCES)
    return out


@router.post('/voice/incidents')
async def new_page(request: Request, user=Depends(get_admin_user)):
    body = await _body_json(request, NOTES_MAX + 4096)
    fields = {k: body[k] for k in ('valence', 'tags', 'when', 'where_heard', 'body') if k in body}
    if 'valence' in fields and fields['valence'] not in VALENCES:
        raise HTTPException(400, 'valence is gift, intrusion, noise or unsure')
    if 'tags' in fields:
        fields['tags'] = _tags(fields['tags'])
    got = await _call('POST', '/v1/petal/incidents', data=json.dumps(fields, ensure_ascii=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json'})
    return _relay(got)


def _tags(v) -> list[str]:
    if not isinstance(v, list):
        raise HTTPException(400, 'tags are a list of names')
    out, seen = [], set()
    for t in v:
        if not isinstance(t, str):
            continue
        t = re.sub(r'[\r\n]+', ' ', t).strip()[:60]
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            out.append(t)
    return out[:24]


@router.get('/voice/incidents/{iid}')
async def incident(iid: str, request: Request, user=Depends(get_admin_user)):
    return _relay(await _call('GET', f'/v1/petal/incidents/{_iid(iid)}'))


@router.put('/voice/incidents/{iid}/notes')
async def notes(iid: str, request: Request, user=Depends(get_admin_user)):
    path = f'/v1/petal/incidents/{_iid(iid)}/notes'
    ctype = (request.headers.get('content-type') or '').split(';')[0].strip().lower()
    raw = await request.body()
    if len(raw) > NOTES_MAX + 4096:
        raise HTTPException(413, 'notes too long')
    headers = {}
    if request.headers.get('if-match'):
        headers['If-Match'] = request.headers['if-match']
    if ctype == 'application/json':
        try:
            fields = json.loads(raw or b'{}')
        except ValueError:
            raise HTTPException(400, 'invalid json') from None
        if not isinstance(fields, dict):
            raise HTTPException(400, 'a json object of fields, please')
        fields = {k: fields[k] for k in ('valence', 'tags', 'when', 'where_heard', 'body') if k in fields}
        if 'valence' in fields and fields['valence'] not in VALENCES:
            raise HTTPException(400, 'valence is gift, intrusion, noise or unsure')
        if 'tags' in fields:
            fields['tags'] = _tags(fields['tags'])
        data = json.dumps(fields, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    else:
        data = raw
        headers['Content-Type'] = 'text/markdown; charset=utf-8'
    return _relay(await _call('PUT', path, data=data, headers=headers), keep=('ETag',))


async def _stream_in(request: Request, cap: int, seen: dict):
    """her bytes, straight through (never held whole here) · past the cap the request is refused"""
    async for chunk in request.stream():
        seen['n'] += len(chunk)
        if seen['n'] > cap:
            seen['over'] = True
            raise HTTPException(413, 'too large')
        yield chunk


async def _pass_bytes(request: Request, path: str, cap: int, extra: dict | None = None, timeout: float = 600):
    length = request.headers.get('content-length')
    if length and length.isdigit() and int(length) > cap:
        raise HTTPException(413, 'too large')
    headers = {'Content-Type': request.headers.get('content-type') or 'application/octet-stream', **(extra or {})}
    if length and length.isdigit():
        headers['Content-Length'] = length
    seen = {'n': 0, 'over': False}
    try:
        got = await _call('POST', path, data=_stream_in(request, cap, seen), headers=headers, timeout=timeout)
    except HTTPException:
        raise
    except Exception:  # the client may wrap what the body raised: past the cap it is still the cap
        if seen['over']:
            raise HTTPException(413, 'too large') from None
        raise
    if seen['over']:  # the voice never got the whole of it: the cap, not a voice asleep
        raise HTTPException(413, 'too large')
    return _relay(got)


@router.post('/voice/incidents/{iid}/clip')
async def clip(iid: str, request: Request, user=Depends(get_admin_user)):
    return await _pass_bytes(request, f'/v1/petal/incidents/{_iid(iid)}/clip', CLIP_MAX, timeout=120)


@router.put('/voice/incidents/{iid}/clip/{name}/timeline')
async def timeline(iid: str, name: str, request: Request, user=Depends(get_admin_user)):
    if not NAME_RE.match(name or ''):
        raise HTTPException(400, 'no such clip')
    raw = await request.body()
    if len(raw) > JSON_MAX:
        raise HTTPException(413, 'timeline too long')
    try:
        json.loads(raw or b'null')
    except ValueError:
        raise HTTPException(400, 'invalid json') from None
    path = f'/v1/petal/incidents/{_iid(iid)}/clip/{quote(name, safe="")}/timeline'
    return _relay(await _call('PUT', path, data=raw, headers={'Content-Type': 'application/json'}))


@router.post('/voice/incidents/{iid}/upload')
async def upload(iid: str, request: Request, user=Depends(get_admin_user)):
    extra = {}
    fname = request.headers.get('x-petal-filename')
    if fname:
        extra['X-Petal-Filename'] = fname[:200]
    return await _pass_bytes(request, f'/v1/petal/incidents/{_iid(iid)}/upload', UPLOAD_MAX, extra, timeout=1800)


@router.get('/voice/incidents/{iid}/audio/{name:path}')
async def audio(iid: str, name: str, request: Request, user=Depends(get_admin_user)):
    """her clip, a take, what she heard or an upload, streamed through (Range kept, so the player can seek)"""
    if not AUDIO_RE.match(name or ''):
        raise HTTPException(400, 'no such file')
    base = voice_url()
    if base is None:
        return _down(_gone_why(None))
    path = f'/v1/petal/incidents/{_iid(iid)}/audio/' + '/'.join(quote(p, safe='') for p in name.split('/'))
    headers = {'User-Agent': USER_AGENT}
    if request.headers.get('range'):
        headers['Range'] = request.headers['range']
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=120))
    try:
        r = await session.get(f'{base}{path}', headers=headers)
    except (asyncio.TimeoutError, aiohttp.ClientError, OSError):
        await session.close()
        return _down(_gone_why(base))
    if r.status >= 400:
        body = await r.read()
        r.release()
        await session.close()
        return JSONResponse(status_code=r.status, content=_json(body) or {'detail': 'not found'})

    async def flow():
        try:
            async for chunk in r.content.iter_chunked(64 * 1024):
                yield chunk
        finally:
            r.release()
            await session.close()

    keep = {k: r.headers[k] for k in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges', 'ETag')
            if k in r.headers}
    keep['Cache-Control'] = 'private, no-store'
    return StreamingResponse(flow(), status_code=r.status, headers=keep)
