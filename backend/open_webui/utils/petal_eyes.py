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
