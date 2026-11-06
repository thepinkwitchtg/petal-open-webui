"""
petal_gentle_stop 🌙 — OWUI honors the gentle stop at the outlet (sprint contract 8).

while the launcher tucks Petal in (a stop, a restart, a mode / model / profile switch) it leaves
$PETAL_APP_DATA/petal-launcher/gentle-stop.json and waits for vLLM to fall idle before stopping
her. a chat still in retrieval isn't running in vLLM yet, so without this it would be sent to a
dying vLLM (TransferEncodingError). so, right before a chat request goes to Petal's vLLM:

    file present + the launcher answers  →  wait until the file is gone and vLLM is healthy, then send
    file present + the launcher is silent →  a stale file: never wait on it
    no file                               →  nothing (one stat)

a quiet status in the chat while it waits ("🌙 Petal is finishing a thought, your message waits
for her"), hidden again once she's back. a ceiling (~20 min, PETAL_GENTLE_STOP_WAIT_S) after
which the message errors cleanly. temp chats included: it's care, not recording.

only requests bound for a local OpenAI-compatible connection wait (Petal's vLLM on this rig);
a cloud model is never held back. hosts: PETAL_GENTLE_STOP_HOSTS (comma list).
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp

log = logging.getLogger(__name__)

LOCAL_HOSTS = {
    h.strip().lower()
    for h in (os.getenv('PETAL_GENTLE_STOP_HOSTS') or 'localhost,127.0.0.1,::1,0.0.0.0').split(',')
    if h.strip()
}
LAUNCHER_HEALTH = os.getenv('PETAL_LAUNCHER_HEALTH') or 'http://127.0.0.1:8770/health'
CEILING_S = int(os.getenv('PETAL_GENTLE_STOP_WAIT_S') or 20 * 60)
POLL_S = 2.0
WAITING = '🌙 Petal is finishing a thought, your message waits for her'


def stop_file() -> Path:
    root = Path(os.environ.get('PETAL_APP_DATA') or '~/Gardens/Documents/Petal-App-Data').expanduser()
    return root / 'petal-launcher' / 'gentle-stop.json'


def read_stop() -> Optional[dict]:
    p = stop_file()
    try:
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding='utf-8')) or {}
    except Exception:
        return {}  # half-written or odd: still a stop


async def _ok(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as r:
            return r.status < 400
    except Exception:
        return False


def _health_url(base: str) -> str:
    """vLLM answers /health at its root; OpenAI-style bases usually end in /v1."""
    b = base.rstrip('/')
    if b.endswith('/v1'):
        b = b[: -len('/v1')]
    return f'{b}/health'


async def petal_base_url(request, model: Optional[dict]) -> Optional[str]:
    """the base URL this chat will be sent to, if it's a local OpenAI-compatible connection."""
    model = model or {}
    if model.get('owned_by') != 'openai' or model.get('pipe'):
        return None
    target = model
    if 'urlIdx' not in target:  # a custom model rides its base model's connection
        base_id = (model.get('info') or {}).get('base_model_id')
        if not base_id:
            return None
        state = request.app.state
        target = (getattr(state, 'OPENAI_MODELS', None) or {}).get(base_id) or (state.MODELS or {}).get(base_id) or {}
        if 'urlIdx' not in target:
            return None
    try:
        from open_webui.routers.openai import get_openai_connection  # late: no import cycle

        url, _, _ = await get_openai_connection(target['urlIdx'])
    except Exception:
        return None
    host = (urlparse(url).hostname or '').lower()
    return url if host in LOCAL_HOSTS else None


async def wait_for_petal(request, model: Optional[dict], metadata: Optional[dict]) -> None:
    """hold a chat request while the launcher tucks Petal in · a no-op without the file."""
    stop = read_stop()
    if stop is None:
        return
    base = await petal_base_url(request, model)
    if base is None:
        return

    emitter = None
    async with aiohttp.ClientSession() as session:
        if not await _ok(session, LAUNCHER_HEALTH):
            log.info('🌙 gentle stop: the file is there but the launcher is silent — a stale file, not waiting')
            return
        why = stop.get('reason') or 'a gentle stop'
        log.info(f'🌙 gentle stop ({why}): holding a chat request until Petal is back')
        try:
            from open_webui.socket.main import get_event_emitter

            if metadata and metadata.get('chat_id') and metadata.get('message_id'):
                emitter = await get_event_emitter(metadata, update_db=False)
                await emitter({'type': 'status', 'data': {'action': 'petal_gentle_stop', 'description': WAITING, 'done': False}})
        except Exception:
            emitter = None  # the wait still happens, just without the quiet line

        t0 = time.monotonic()
        try:
            while True:
                gone = read_stop() is None
                if not gone and not await _ok(session, LAUNCHER_HEALTH):
                    gone = True  # the launcher went silent mid-wait: the file is stale now
                if gone and await _ok(session, _health_url(base)):
                    log.info(f'🌙 gentle stop: Petal is back after {round(time.monotonic() - t0)}s — sending')
                    return
                if time.monotonic() - t0 > CEILING_S:
                    raise Exception(
                        f'🌙 Petal didn\'t come back within {max(1, round(CEILING_S / 60))} min ({why}). '
                        'your message is safe here — send it again once she\'s up'
                    )
                await asyncio.sleep(POLL_S)
        finally:
            if emitter:
                try:
                    await emitter(
                        {'type': 'status', 'data': {'action': 'petal_gentle_stop', 'description': WAITING, 'done': True, 'hidden': True}}
                    )
                except Exception:
                    pass
