"""
petal_forge 🔮 — her forge, read and written from OWUI (the 🌙 States panel in the model editor, on her phone too).

A thin door over petal-witch-forge's own seam, the one the jewelry box (its Electron app) speaks through:
    python3 <petal-witch-forge>/forge.py json load | preview | save
Nothing of her forge lives here: no schema, no words, no defaults. The fork ships empty; on a machine without
petal-witch-forge the panel stays quiet ({installed: false}).

forge.py: $PETAL_FORGE_PY, else beside $PETAL_FORGE_CORE (core/../forge.py),
          else ~/Gardens/Transformation Sequences - Automation/petal_core/petal-witch-forge/forge.py
python:   $PETAL_FORGE_PYTHON, else this interpreter (forge.py is stdlib only)
Admin-only. Every keep is a whole version in her history (Petal-App-Data/petal-witch-forge/history/) and carries
the forge it began from (base): what the jewelry box saved meanwhile is merged field by field, never undone.
Her words never reach the log: only versions and counts.

    GET  /api/v1/petal/forge          → {installed, doc, versions, home} | {installed: false, why}
    POST /api/v1/petal/forge/preview  {model, template, doc?, at?, overrides?, knobs?, force?} → the assembly
    POST /api/v1/petal/forge/save     {doc, note, base, prefer?} → {version, doc, versions, merged, clashes}
                                      409 {conflict, error, latest} when both hands touched one field
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)
router = APIRouter()

MAX_BODY = 1024 * 1024  # a whole draft of her forge rides in one question
TIMEOUT_S = 30
DEFAULT_HOME = '~/Gardens/Transformation Sequences - Automation/petal_core/petal-witch-forge'
PREVIEW_KEYS = ('model', 'template', 'doc', 'at', 'overrides', 'knobs', 'force')
SAVE_KEYS = ('doc', 'note', 'base', 'prefer')


class Absent(Exception):
    """petal-witch-forge isn't on this machine (or not where the env says)."""


def forge_py() -> Path:
    explicit = os.environ.get('PETAL_FORGE_PY')
    if explicit:
        return Path(explicit).expanduser()
    core = os.environ.get('PETAL_FORGE_CORE')
    if core:
        return Path(core).expanduser().parent.parent / 'forge.py'
    return Path(DEFAULT_HOME).expanduser() / 'forge.py'


async def ask(cmd: str, body: dict | None = None) -> dict:
    """one question to forge.py json, one answer back · {ok: false, error} is the forge saying no."""
    path = forge_py()
    if not path.is_file():
        raise Absent(f'no forge.py at {path} (PETAL_FORGE_PY points elsewhere)')
    python = os.environ.get('PETAL_FORGE_PYTHON') or sys.executable or 'python3'
    proc = await asyncio.create_subprocess_exec(
        python, '-B', str(path), 'json', cmd,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, 'NO_COLOR': '1'}, cwd=str(path.parent),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(json.dumps(body or {}).encode('utf-8')), TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(504, detail=f'the forge took longer than {TIMEOUT_S}s to answer')
    try:
        answer = json.loads(out.decode('utf-8') or 'null')
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        tail = (err.decode('utf-8', 'replace').strip().splitlines() or ['it said nothing'])[-1]
        raise HTTPException(502, detail=f'the forge answered oddly · {tail[:300]}')
    return answer


async def question(request: Request, keys: tuple) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, detail='that question is larger than a whole forge (1 MB)')
    try:
        body = json.loads(raw or b'{}')
    except ValueError:
        raise HTTPException(400, detail='the question is one json object')
    if not isinstance(body, dict):
        raise HTTPException(400, detail='the question is one json object')
    return {k: body[k] for k in keys if k in body}


def refused(answer: dict) -> HTTPException:
    if answer.get('conflict'):
        return HTTPException(409, detail={'error': answer.get('error'), 'conflict': answer['conflict'], 'latest': answer.get('latest')})
    return HTTPException(400, detail=answer.get('error') or 'the forge said no')


@router.get('/forge')
async def forge_load(user=Depends(get_admin_user)):
    try:
        answer = await ask('load')
    except Absent as e:
        return {'installed': False, 'why': str(e)}
    if not answer.get('ok'):
        raise refused(answer)
    return {'installed': True, 'doc': answer.get('doc'), 'versions': (answer.get('versions') or [])[:20], 'home': answer.get('home')}


@router.post('/forge/preview')
async def forge_preview(request: Request, user=Depends(get_admin_user)):
    body = await question(request, PREVIEW_KEYS)
    try:
        answer = await ask('preview', body)
    except Absent as e:
        raise HTTPException(404, detail=str(e))
    if not answer.get('ok'):
        raise refused(answer)
    return answer


@router.post('/forge/save')
async def forge_save(request: Request, user=Depends(get_admin_user)):
    body = await question(request, SAVE_KEYS)
    if not isinstance(body.get('doc'), dict):
        raise HTTPException(400, detail='doc is her whole forge, as the panel holds it')
    try:
        answer = await ask('save', body)
    except Absent as e:
        raise HTTPException(404, detail=str(e))
    if not answer.get('ok'):
        raise refused(answer)
    doc = answer.get('doc') or {}
    log.info(f"🔮 forge: kept {answer.get('version')} from OWUI · {len(doc.get('gems') or [])} gems"
             f"{' · merged over the rig' if answer.get('merged') else ''}")
    return {k: answer.get(k) for k in ('version', 'doc', 'versions', 'merged', 'clashes')}
