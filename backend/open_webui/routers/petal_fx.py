"""
petal_fx ✨ — the fx door (slice A18b): a read-only window onto the rig's effects service.

    GET /api/v1/petal/fx/{path}   →   PETAL_FX_URL + path     (default http://127.0.0.1:8300/v1/)

the phone reaches the service through OWUI over the tailnet, with no new port. /static/loader.js asks
for `look`, and the look names what else to wake (scripts, fonts), all through this same door.

only the service's read-only face passes: `look`, and one file under `engine/`, `fonts/` or `fx/`.
GET (and HEAD) only, no query strings, a verified session (OWUI's cookie is enough, so <script src>
and font urls work), a small allow-list of content types, and short timeouts: an asleep or missing
service answers a quiet 502/504 and the quotes keep their static face. ETag revalidation passes
through, so a page load asks "still the same?" and gets a 304.

PETAL_FX_URL='' closes the door (404).
"""

import logging
import os
import re

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from open_webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)
router = APIRouter()

FX_URL = os.environ.get('PETAL_FX_URL', 'http://127.0.0.1:8300/v1/').strip()
if FX_URL and not FX_URL.endswith('/'):
    FX_URL += '/'

FACE = re.compile(r'(?:look|(?:engine|fonts|fx)/[A-Za-z0-9][A-Za-z0-9._-]{0,120})')
TYPES = {
    'application/json',
    'application/javascript',
    'text/javascript',
    'text/plain',
    'font/ttf',
    'font/otf',
    'font/woff',
    'font/woff2',
    'application/font-sfnt',
    'application/x-font-ttf',
    'application/x-font-otf',
    'application/font-woff',
    'application/font-woff2',
}
PASS_BACK = ('ETag', 'Last-Modified', 'Cache-Control')
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT = aiohttp.ClientTimeout(total=8, connect=1.5)


def _face_path(path: str) -> str:
    if not FX_URL:
        raise HTTPException(status_code=404, detail='the fx door is closed (PETAL_FX_URL is empty)')
    if not FACE.fullmatch(path) or '..' in path:
        raise HTTPException(status_code=404, detail='not part of the fx face')
    return FX_URL + path


async def _body(r: aiohttp.ClientResponse) -> tuple[bytes, str]:
    """the file and its type, if it's a type the face may send and not too much of it"""
    ctype = (r.headers.get('Content-Type') or '').split(';')[0].strip().lower()
    if ctype not in TYPES:
        raise HTTPException(status_code=502, detail=f'the fx service sent {ctype or "no type"}')
    chunks, total = [], 0
    async for chunk in r.content.iter_chunked(65536):  # read() alone may stop at what's buffered
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(status_code=502, detail='the fx service sent too much')
        chunks.append(chunk)
    return b''.join(chunks), r.headers.get('Content-Type') or ctype


def _status(r: aiohttp.ClientResponse) -> None:
    if r.status == 404:
        raise HTTPException(status_code=404, detail='the fx service has no such file')
    if r.status not in (200, 304):
        raise HTTPException(status_code=502, detail=f'the fx service answered {r.status}')


async def _forward(path: str, request: Request) -> Response:
    url = _face_path(path)
    headers = {'Accept': '*/*', 'User-Agent': 'petal-owui/fx-door'}
    if request.headers.get('if-none-match'):
        headers['If-None-Match'] = request.headers['if-none-match']
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(url, headers=headers, allow_redirects=False) as r:
                _status(r)
                back = {k: r.headers[k] for k in PASS_BACK if k in r.headers}
                if r.status == 304:
                    return Response(status_code=304, headers=back)
                body, full = await _body(r)
    except HTTPException:
        raise
    except TimeoutError:  # before OSError: a timeout is an OSError too
        raise HTTPException(status_code=504, detail='the fx service took too long')
    except (aiohttp.ClientError, OSError):
        raise HTTPException(status_code=502, detail='the fx service is asleep')
    back.setdefault('Cache-Control', 'no-cache')
    back['X-Content-Type-Options'] = 'nosniff'
    if request.method == 'HEAD':
        back['Content-Length'] = str(len(body))
        return Response(status_code=200, media_type=full, headers=back)
    return Response(content=body, status_code=200, media_type=full, headers=back)


@router.api_route('/fx/{path:path}', methods=['GET', 'HEAD'])
async def fx_face(path: str, request: Request, user=Depends(get_verified_user)):
    if request.url.query:
        raise HTTPException(status_code=404, detail='the fx face takes no query')
    return await _forward(path, request)
