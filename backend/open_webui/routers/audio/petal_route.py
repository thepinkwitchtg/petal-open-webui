"""
petal_route 🎧 — her phone's earphones or speaker, read from the rig, for one gate only (A37)

    GET /api/v1/audio/petal-route   → {route: 'earphones' | 'speaker' | 'unknown', known: bool, why?}

the page asks only when she turned "follow the rig's audio route" on (Settings → 🌸 Petal → Voice) and only on
her phone: the answer opens or holds autoplay there, and does nothing else (no prompt, no memory, no log line
beyond the route word).

the address is $PETAL_ROUTE_URL: a loopback URL that answers JSON (unset, or not loopback → unknown, nothing is
called). where the value sits in that JSON is $PETAL_ROUTE_KEY, a dotted path (default 'audio.route'), found as a
flat key, under 'signals', or nested; a {value: …} (or {route: …}) at the end is read too.
admin only (her senses are hers). a quiet rig answers unknown, never an error.
"""

import logging
import os
import time
from urllib.parse import urlparse

import aiohttp
from fastapi import APIRouter, Depends
from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)
router = APIRouter()

LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
TIMEOUT_S = 0.8
FRESH_S = 5.0  # a phone deciding twice in a breath asks the rig once
ROUTES = {'earphones', 'speaker'}
USER_AGENT = 'petal-owui/route'

_cache: dict = {'at': -FRESH_S, 'out': None}


def route_url() -> str | None:
    url = (os.environ.get('PETAL_ROUTE_URL') or '').strip()
    return url if url and urlparse(url).hostname in LOOPBACK else None


def pick(doc, key: str) -> str:
    """the route word inside the rig's answer, wherever the key puts it → 'earphones' | 'speaker' | 'unknown'"""

    def leaf(v):
        if isinstance(v, dict):
            v = v.get('value', v.get('route'))
        return v if isinstance(v, str) else None

    found = None
    if isinstance(doc, dict):
        found = leaf(doc.get(key))
        if found is None and isinstance(doc.get('signals'), dict):
            found = leaf(doc['signals'].get(key))
        if found is None:
            cur = doc
            for step in key.split('.'):
                cur = cur.get(step) if isinstance(cur, dict) else None
            found = leaf(cur)
    word = (found or '').strip().lower()
    return word if word in ROUTES else 'unknown'


async def read_route() -> dict:
    url = route_url()
    if not url:
        return {'route': 'unknown', 'known': False, 'why': 'no route address'}
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_S), headers={'User-Agent': USER_AGENT}
        ) as s:
            async with s.get(url) as r:
                if r.status != 200:
                    return {'route': 'unknown', 'known': False, 'why': f'rig said {r.status}'}
                doc = await r.json(content_type=None)
    except (TimeoutError, aiohttp.ClientError, ValueError):
        return {'route': 'unknown', 'known': False, 'why': 'rig quiet'}
    route = pick(doc, os.environ.get('PETAL_ROUTE_KEY') or 'audio.route')
    return {'route': route, 'known': route != 'unknown'}


@router.get('/petal-route')
async def petal_route(user=Depends(get_admin_user)):
    now = time.monotonic()
    if _cache['out'] is not None and now - _cache['at'] < FRESH_S:
        return _cache['out']
    out = await read_route()
    _cache.update(at=now, out=out)
    return out
