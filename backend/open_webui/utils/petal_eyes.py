"""
petal_eyes 🌸👁 — what Petal received, byte for byte (slice A10 · her eyes).

the outlet (routers/openai.py) serializes the payload once, sends those exact bytes and shows
them here first. `req_sha = sha256(bytes)`: petal-wellspring (Lily's source tap, every raw
character Petal writes, before OWUI prettifies it) keeps the same hash for the same bytes, so
the two views join on it.

  saved chats → $PETAL_APP_DATA/petal-eyes/<chat_id>/<message_id>.json.gz      gold tier · 700/600
                another round for the same reply (a tool follow-up, a continue) lands beside it
                as <message_id>.r2.json.gz, .r3 … : nothing is ever overwritten
  temp chats  → an in-memory ring of the last 20, so her tests stay auditable (contract 0)
  tasks       → never (titles, tags, follow-ups and the hush aren't replies)

a record: {at, chat_id, message_id, model, req_sha, payload, parts, round, to}
  payload — the request exactly as sent (its bytes, embedded verbatim in the record)
  parts   — what each injector put in, so the viewer can tint it by source. one line in any
            filter (its `__metadata__`) or injector, no import needed, harmless on a fork
            without eyes:

      (__metadata__ or {}).setdefault('petal_eyes_parts', []).append({'source': '🌸 petal-soft', 'text': text})

            extra keys ride along as they are ({'tokens': 32, 'memory_ids': [...]}, a pull …)
  to      — host:port the bytes went to (so a missing wellspring record can say where they went)

🧵 the rendered view (A13): a kept round asked again of the live vLLM (/tokenize then /detokenize,
with the same chat-template settings), so her eyes read every special token too. kept nowhere.
"""

import asyncio
import collections
import gzip
import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from open_webui.utils import petal_markers_core as core
from open_webui.utils.chat_id import is_saved_chat_id

log = logging.getLogger(__name__)

KEY = 'petal_eyes_parts'
RING_SIZE = 20
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')  # saved chat + message ids are uuids
_SHA = re.compile(r'^[0-9a-f]{64}$')

_ring: collections.deque = collections.deque(maxlen=RING_SIZE)
_ring_lock = threading.Lock()
_pending: set = set()  # write tasks, held until they land


def home() -> Path:
    return core.app_data_root() / 'petal-eyes'


def wellspring_home() -> Path:
    """petal-wellspring/ · the tap's former home (petal-spill/) is read only while the new one is absent."""
    root = core.app_data_root()
    home_ = root / 'petal-wellspring'
    return root / 'petal-spill' if not home_.is_dir() and (root / 'petal-spill').is_dir() else home_


# ── the injectors' side ────────────────────────────────────────
def part(metadata: Optional[dict], source: str, text: Any, **extra) -> None:
    """an injector's one line: what it put in, for the viewer's tint."""
    if not isinstance(metadata, dict) or not source:
        return
    metadata.setdefault(KEY, []).append({'source': str(source), 'text': '' if text is None else str(text), **extra})


def _parts(metadata: dict) -> list:
    """a snapshot of the parts so far · a tool round may run the inlets again: one copy is kept."""
    out, seen = [], set()
    for p in metadata.get(KEY) or []:
        if not isinstance(p, dict):
            continue
        q = {**p, 'source': str(p.get('source') or '?'), 'text': '' if p.get('text') is None else str(p.get('text'))}
        k = json.dumps(q, sort_keys=True, ensure_ascii=False, default=str)
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out


# ── the outlet's side ──────────────────────────────────────────
def _host(url: Optional[str]) -> Optional[str]:
    try:
        u = urlparse(url or '')
        return u.netloc.rsplit('@', 1)[-1] or None  # never a user:pass@
    except Exception:
        return None


def _spawn(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def see(metadata: Optional[dict], body: bytes, model: Optional[str] = None, url: Optional[str] = None) -> Optional[str]:
    """the outlet's one call, right before the send · → req_sha (None when this isn't a reply).
    never raises: her eyes never cost her a message."""
    try:
        if not isinstance(metadata, dict) or metadata.get('task'):
            return None
        chat_id, message_id = metadata.get('chat_id'), metadata.get('message_id')
        if not (chat_id and message_id):
            return None
        req_sha = hashlib.sha256(body).hexdigest()
        head = {
            'at': round(time.time(), 3),
            'chat_id': str(chat_id),
            'message_id': str(message_id),
            'model': model,
            'req_sha': req_sha,
            'to': _host(url),
        }
        parts = _parts(metadata)
        if is_saved_chat_id(head['chat_id']):
            if _ID.match(head['chat_id']) and _ID.match(head['message_id']):
                _spawn(asyncio.to_thread(_keep_safely, head, body, parts))
            else:
                log.warning('🌸👁 petal eyes: an id that is not a plain id — nothing kept')
        else:  # contract 0: a temp chat is only ever remembered in memory
            with _ring_lock:
                n = 1 + sum(
                    1 for r in _ring if r['head']['chat_id'] == head['chat_id'] and r['head']['message_id'] == head['message_id']
                )
                _ring.append({'head': {**head, 'round': n}, 'body': body, 'parts': parts})
        return req_sha
    except Exception as e:
        log.warning(f'🌸👁 petal eyes: not kept ({e!r})')
        return None


def _record_bytes(head: dict, body: bytes, parts: list) -> bytes:
    """the record, with the payload embedded verbatim: the exact bytes Petal received."""
    pre = json.dumps(head, ensure_ascii=False)[:-1]  # '{"at": …, "round": n' (closing brace dropped)
    post = json.dumps(parts, ensure_ascii=False, default=str)
    return f'{pre}, "payload": '.encode('utf-8') + body + f', "parts": {post}}}'.encode('utf-8')


def _dir(chat_id: str) -> Path:
    root = home()
    core.app_data_root().mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700, exist_ok=True)
    d = root / chat_id
    d.mkdir(mode=0o700, exist_ok=True)
    return d


def _name(message_id: str, n: int) -> str:
    return f'{message_id}.json.gz' if n == 1 else f'{message_id}.r{n}.json.gz'


def _keep(head: dict, body: bytes, parts: list) -> Optional[Path]:
    d = _dir(head['chat_id'])
    for n in range(1, 1000):  # claim the next free round with O_EXCL: two writers never share a name
        path = d / _name(head['message_id'], n)
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            break
        except FileExistsError:
            continue
    else:
        return None
    tmp = d / f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp'
    fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=6, mtime=0) as gz:
        gz.write(_record_bytes({**head, 'round': n}, body, parts))
    os.replace(tmp, path)  # atomic over the claimed (empty) name
    return path


def _keep_safely(head: dict, body: bytes, parts: list) -> None:
    try:
        _keep(head, body, parts)
    except Exception as e:
        log.warning(f'🌸👁 petal eyes: not kept ({e!r})')


# ── the viewer's side ──────────────────────────────────────────
_ROUND = re.compile(r'\.r(\d+)\.json\.gz$')


def get(chat_id: str, message_id: str) -> list:
    """every round kept for one reply, oldest first."""
    chat_id, message_id = str(chat_id or ''), str(message_id or '')
    if is_saved_chat_id(chat_id):
        if not (_ID.match(chat_id) and _ID.match(message_id)):
            return []
        d = home() / chat_id
        if not d.is_dir():
            return []
        out = []
        for p in d.iterdir():
            if p.name != f'{message_id}.json.gz' and not (
                p.name.startswith(f'{message_id}.r') and _ROUND.search(p.name)
            ):
                continue
            try:
                out.append(json.loads(gzip.decompress(p.read_bytes())))
            except Exception:
                continue  # a round still being written (or broken): skipped, never fatal
        return sorted(out, key=lambda r: int(r.get('round') or 1))
    with _ring_lock:
        entries = [r for r in _ring if r['head']['chat_id'] == chat_id and r['head']['message_id'] == message_id]
    out = []
    for r in entries:
        try:
            out.append({**r['head'], 'payload': json.loads(r['body']), 'parts': r['parts']})
        except Exception:
            continue
    return sorted(out, key=lambda r: int(r.get('round') or 1))


def stats() -> dict:
    """numbers only."""
    chats = records = size = 0
    root = home()
    if root.is_dir():
        for d in root.iterdir():
            if not d.is_dir():
                continue
            chats += 1
            for p in d.glob('*.json.gz'):
                records += 1
                try:
                    size += p.stat().st_size
                except OSError:
                    pass
    with _ring_lock:
        ring = len(_ring)
    return {'chats': chats, 'records': records, 'bytes': size, 'ring': ring, 'ring_size': RING_SIZE}


# ── 🫗 petal-wellspring: the source tap's side of the join (A11.1, was petal-spill) ─────────
# a record: petal-wellspring/<day>/<HHMMSS>-<id>.json.gz, one JSON object each:
#   {id, at, route, path, caller, req_sha, model, request, status, ms, cut, streamed, raw, content,
#    reasoning, finish, flags: [str]}
# every day folder keeps an index.jsonl, one line per record: {req_sha, file, at, route}. the indexes
# are read first (each once per change) and only the matching file is opened; a scan of the files
# stays as the fallback (a day without an index, a line not written yet, the tap's older records).
_SHA_IN = re.compile(rb'"(?:req_sha|request_sha|req_sha256|request_sha256|sha256|body_sha)"\s*:\s*"([0-9a-f]{64})"')
_well_lock = threading.Lock()
_well_index_sig: dict = {}  # index path → (mtime, size): already read
_well_seen: dict = {}  # record path → (mtime, size): already scanned
_well_by_sha: dict = {}  # req_sha → record path


def _inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _read_indexes(root: Path) -> None:
    for idx in root.glob('*/index.jsonl'):
        try:
            st = idx.stat()
        except OSError:
            continue
        sig = (st.st_mtime, st.st_size)
        if _well_index_sig.get(str(idx)) == sig:
            continue
        try:
            text = idx.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for line in text.splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue  # a torn line: the scan still finds its record
            sha, f = (e.get('req_sha'), e.get('file')) if isinstance(e, dict) else (None, None)
            if not (isinstance(sha, str) and _SHA.match(sha) and isinstance(f, str) and f):
                continue
            # a file name inside its day, or a path from the wellspring's root: never outside it
            for p in (idx.parent / f, root / f, idx.parent / Path(f).name):
                if _inside(p, root) and p.is_file():
                    _well_by_sha[sha] = str(p)
                    break
        _well_index_sig[str(idx)] = sig


def _shas_in(path: Path) -> set:
    try:
        with gzip.open(path, 'rb') as f:
            data = f.read()
    except Exception:
        return set()
    return {m.group(1).decode() for m in _SHA_IN.finditer(data)}


def _holds(rec: Any, req_sha: str) -> bool:
    return req_sha in json.dumps(rec, ensure_ascii=False, default=str) if rec is not None else False


def _load_well(path: Path, root: Path, req_sha: str) -> Optional[dict]:
    try:
        data = gzip.decompress(path.read_bytes()).decode('utf-8', 'replace')
    except Exception:
        return None
    rec: Any = None
    try:
        rec = json.loads(data)
        if isinstance(rec, list):  # an older tap's array of records: the one carrying this hash
            rec = next((r for r in rec if _holds(r, req_sha)), None)
    except ValueError:  # an older tap's jsonl: one record per line
        for line in data.splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if _holds(r, req_sha):
                rec = r
                break
    if rec is None or (isinstance(rec, dict) and rec.get('req_sha') not in (None, req_sha)):
        return None
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = path.name
    record = rec
    if isinstance(rec, dict) and rec.get('request') is not None:  # the very bytes her eyes already hold
        size = len(rec['request']) if isinstance(rec['request'], str) else len(json.dumps(rec['request']))
        record = {**rec, 'request': f'… the same request her eyes hold (req_sha matches) · {size:,} chars'}
    return {'path': rel, 'view': wellspring_view(rec), 'record': record}


def find_wellspring(req_sha: str, at: Optional[float] = None) -> Optional[dict]:
    """the wellspring record whose hash is `req_sha`: the day indexes first, then (fallback) every
    file, each read once per server life, the files nearest `at` (the send time) first."""
    req_sha = str(req_sha or '').lower()
    if not _SHA.match(req_sha):
        return None
    root = wellspring_home()
    if not root.is_dir():
        return None
    with _well_lock:
        _read_indexes(root)
        known = _well_by_sha.get(req_sha)
        if known and Path(known).is_file():
            found = _load_well(Path(known), root, req_sha)
            if found:
                return found
        files = []
        for p in root.glob('*/*.json.gz'):
            try:
                st = p.stat()
            except OSError:
                continue
            files.append((p, st))

        def order(item):
            p, st = item
            named = 0 if req_sha in p.name else 1
            return (named, abs(st.st_mtime - at) if at else -st.st_mtime)

        for p, st in sorted(files, key=order):
            sig = (st.st_mtime, st.st_size)
            if _well_seen.get(str(p)) == sig:
                continue
            shas = _shas_in(p)
            _well_seen[str(p)] = sig
            for sha in shas:
                _well_by_sha.setdefault(sha, str(p))
            if req_sha in shas:
                return _load_well(p, root, req_sha)
    return None


def _dig(rec: Any, *paths) -> Any:
    for path in paths:
        cur, ok = rec, True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            elif isinstance(cur, list) and isinstance(k, int) and -len(cur) <= k < len(cur):
                cur = cur[k]
            else:
                ok = False
                break
        if ok and cur not in (None, '', [], {}):
            return cur
    return None


def _from_chunks(rec: dict, fields: tuple) -> Optional[str]:
    """a tap that kept the SSE chunks: their deltas, joined."""
    if not isinstance(rec, dict):
        return None
    for v in rec.values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and 'choices' in v[0]:
            out = []
            for c in v:
                d = _dig(c, *[('choices', 0, 'delta', f) for f in fields])
                if isinstance(d, str):
                    out.append(d)
            if out:
                return ''.join(out)
    return None


_WELL_META = ('id', 'at', 'route', 'path', 'caller', 'model', 'status', 'ms', 'cut', 'streamed', 'finish')


def wellspring_view(rec: Any) -> dict:
    """the wellspring's own names (A11.1) · an older tap's records are read by best-effort names ·
    the whole record always rides beside it."""
    if not isinstance(rec, dict):
        return {'content': None, 'reasoning': None, 'raw': None, 'flags': None, 'meta': {}, 'keys': []}
    as_text = lambda v: v if (v is None or isinstance(v, str)) else json.dumps(v, ensure_ascii=False, indent=1)
    content = rec.get('content') if isinstance(rec.get('content'), str) else None
    reasoning = rec.get('reasoning') if isinstance(rec.get('reasoning'), str) else None
    if content is None:
        content = _dig(
            rec,
            ('raw_content',), ('text',), ('output_text',), ('output',), ('completion',),
            ('response', 'content'), ('response', 'text'), ('choices', 0, 'message', 'content'),
        ) or _from_chunks(rec, ('content',))  # fmt: skip
    if reasoning is None:
        reasoning = _dig(
            rec,
            ('reasoning_content',), ('thinking',), ('think',),
            ('response', 'reasoning'), ('response', 'reasoning_content'),
            ('choices', 0, 'message', 'reasoning_content'), ('choices', 0, 'message', 'reasoning'),
        ) or _from_chunks(rec, ('reasoning_content', 'reasoning'))  # fmt: skip
    flags = rec.get('flags')
    if flags is None:
        flags = _dig(rec, ('✧',), ('marks',), ('sparkles',), ('stars',))
    if flags is not None and not isinstance(flags, list):
        flags = [flags]
    return {
        'content': as_text(content),
        'reasoning': as_text(reasoning),
        'raw': as_text(rec.get('raw')),
        'flags': [f if isinstance(f, str) else json.dumps(f, ensure_ascii=False) for f in flags] if flags else flags,
        'meta': {k: rec[k] for k in _WELL_META if rec.get(k) is not None},
        'keys': list(rec.keys())[:80],
    }


# ── 🧵 the rendered view: her payload through vLLM's own chat template (A13) ─────────────────
# the request exactly as sent goes to vLLM's POST /tokenize with the same chat-template settings
# (add_generation_prompt · continue_final_message · chat_template(_kwargs) · tools …), and the tokens
# come back through POST /detokenize: every special token, the thinking switch and the tool block the
# template writes, in the order Petal reads them. asked live, kept nowhere.
#   where: the OWUI connection the bytes went to (matched by host:port, its /v1 dropped), or
#   $PETAL_EYES_TOKENIZE_URL (+ $PETAL_EYES_TOKENIZE_KEY) when a tap in between won't pass /tokenize.
#   only a vLLM on this rig is asked on its own (her payload never leaves the rig for a view); the
#   override is her explicit choice. a gentle stop in progress (contract 8) waits for Petal.
TOKENIZE_URL = os.getenv('PETAL_EYES_TOKENIZE_URL') or ''
TOKENIZE_KEY = os.getenv('PETAL_EYES_TOKENIZE_KEY') or ''
_TEMPLATE_KEYS = (
    'add_generation_prompt', 'continue_final_message', 'add_special_tokens',
    'chat_template', 'chat_template_kwargs', 'tools', 'mm_processor_kwargs',
)  # fmt: skip


class RenderError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def render_body(payload: dict) -> dict:
    """the /tokenize body for a chat payload: its messages + its own template settings, nothing more."""
    msgs = payload.get('messages') if isinstance(payload, dict) else None
    if not isinstance(msgs, list) or not msgs:
        raise RenderError(422, 'this request carries no chat messages to render (the responses API?)')
    body: dict = {'messages': msgs, 'add_generation_prompt': True, 'return_token_strs': False}
    if payload.get('model'):
        body['model'] = payload['model']
    for k in _TEMPLATE_KEYS:
        if payload.get(k) is not None:
            body[k] = payload[k]
    if body.get('continue_final_message') and 'add_generation_prompt' not in payload:
        body['add_generation_prompt'] = False  # vLLM refuses the two together
    return body


def _root(url: str) -> str:
    b = (url or '').strip().rstrip('/')
    return b[: -len('/v1')] if b.endswith('/v1') else b


async def _where(to: Optional[str]) -> tuple[str, str, str]:
    """→ (root, key, how): the override, else the connection her bytes went to, else the record's host."""
    if TOKENIZE_URL:
        return _root(TOKENIZE_URL), TOKENIZE_KEY, 'PETAL_EYES_TOKENIZE_URL'
    if not to:
        raise RenderError(409, 'this record does not say where its bytes went')
    from open_webui.routers.openai import get_openai_runtime_config  # late: openai.py imports this file

    _, urls, keys, _ = await get_openai_runtime_config()
    for i, u in enumerate(urls or []):
        if _host(u) == to:
            return _root(u), (keys[i] if i < len(keys or []) else '') or '', f'connection {i}'
    return f'http://{to}', '', 'the record (no connection holds this host now)'


def _why(status: int, text: str, root: str) -> str:
    try:
        j = json.loads(text)
    except ValueError:
        j = None
    msg = None
    if isinstance(j, dict):
        e = j.get('error')
        msg = (e.get('message') if isinstance(e, dict) else e) or j.get('message') or j.get('detail')
    if status == 404 and (msg in (None, 'Not Found')):
        return f'{root} has no /tokenize (a tap in between? set PETAL_EYES_TOKENIZE_URL to vLLM itself)'
    if status == 404 and isinstance(msg, str) and 'does not exist' in msg:
        return f'vLLM serves another model now · {msg}'
    return f'vLLM answered {status}: {(msg if isinstance(msg, str) else text)[:600]}'


async def render(rec: dict) -> dict:
    """one kept round, rendered by the live vLLM · → {text, count, max_model_len, asked, how, settings, model}."""
    import aiohttp

    from open_webui.utils import petal_gentle_stop as gentle  # late: same reason as above

    body = render_body(rec.get('payload') or {})
    root, key, how = await _where(rec.get('to'))
    host = (urlparse(root).hostname or '').lower()
    if how != 'PETAL_EYES_TOKENIZE_URL' and host not in gentle.LOCAL_HOSTS:
        raise RenderError(409, f'the rendered view only asks a vLLM on this rig · this reply went to {rec.get("to")}')
    headers = {'Content-Type': 'application/json', **({'Authorization': f'Bearer {key}'} if key else {})}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        if gentle.read_stop() is not None and await gentle._ok(s, gentle.LAUNCHER_HEALTH):
            raise RenderError(503, '🌙 Petal is being tucked in (a gentle stop) · the rendered view waits until she is back')
        try:
            async with s.post(f'{root}/tokenize', data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=headers) as r:
                text = await r.text()
                if r.status >= 400:
                    raise RenderError(502, _why(r.status, text, root))
                tok = json.loads(text)
            tokens = tok.get('tokens') if isinstance(tok, dict) else None
            if not isinstance(tokens, list):
                raise RenderError(502, f'{root}/tokenize answered without tokens')
            det = {'tokens': tokens, **({'model': body['model']} if body.get('model') else {})}
            async with s.post(f'{root}/detokenize', data=json.dumps(det).encode('utf-8'), headers=headers) as r:
                text = await r.text()
                if r.status >= 400:
                    raise RenderError(502, _why(r.status, text, root))
                prompt = json.loads(text).get('prompt')
        except RenderError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise RenderError(502, f'vLLM at {root} did not answer ({type(e).__name__}) · is she awake?')
        except ValueError:
            raise RenderError(502, f'{root} answered something that is not JSON')
    tools = body.get('tools')
    settings = {k: body[k] for k in _TEMPLATE_KEYS if k in body and k not in ('tools', 'chat_template')}
    if isinstance(tools, list):
        settings['tools'] = len(tools)
    if body.get('chat_template'):
        settings['chat_template'] = f'her own · {len(str(body["chat_template"])):,} chars'
    if rec.get('payload', {}).get('tool_choice') is not None:
        settings['tool_choice'] = rec['payload']['tool_choice']
    return {
        'text': prompt if isinstance(prompt, str) else '',
        'count': tok.get('count', len(tokens)),
        'max_model_len': tok.get('max_model_len'),
        'asked': _host(root) or root,
        'how': how,
        'settings': settings,
        'model': body.get('model'),
    }
