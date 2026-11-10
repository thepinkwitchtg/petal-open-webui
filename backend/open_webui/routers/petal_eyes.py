"""
petal_eyes 👁 — what Petal received, for Lily's eyes (slice A10).

A thin door over utils/petal_eyes.py. Admin-only.

    GET /api/v1/petal/eyes?chat_id&message_id   → { rounds: [record…], kept: disk|ring }
    GET /api/v1/petal/eyes/wellspring?req_sha[&at] → { path, view, record } from petal-wellspring/<day>/
                                                   (its index.jsonl first, a scan as the fallback)
    GET /api/v1/petal/eyes/rendered?chat_id&message_id[&round] → { text, count, max_model_len, asked, how,
                                                   settings, model }: the round through vLLM's own chat
                                                   template (/tokenize → /detokenize), asked live (A13)
    GET /api/v1/petal/eyes/stats                → numbers only
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from open_webui.utils import petal_eyes as eyes
from open_webui.utils.auth import get_admin_user
from open_webui.utils.chat_id import is_saved_chat_id

log = logging.getLogger(__name__)
router = APIRouter()


@router.get('/eyes')
async def read_eyes(chat_id: str, message_id: str, user=Depends(get_admin_user)):
    rounds = await asyncio.to_thread(eyes.get, chat_id, message_id)
    if not rounds:
        raise _gone(chat_id)
    return {'rounds': rounds, 'kept': 'disk' if is_saved_chat_id(chat_id) else 'ring'}


def _gone(chat_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=(
            'nothing kept for this reply — it was sent before her eyes opened'
            if is_saved_chat_id(chat_id)
            else f'this temp reply left the ring (it keeps the last {eyes.RING_SIZE} sends, until OWUI restarts)'
        ),
    )


@router.get('/eyes/rendered')
async def read_rendered(
    chat_id: str, message_id: str, round_: int = Query(0, alias='round'), user=Depends(get_admin_user)
):
    rounds = await asyncio.to_thread(eyes.get, chat_id, message_id)
    if not rounds:
        raise _gone(chat_id)
    rec = next((r for r in rounds if int(r.get('round') or 1) == round_), rounds[-1]) if round_ else rounds[-1]
    try:
        return await eyes.render(rec)
    except eyes.RenderError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


@router.get('/eyes/wellspring')
async def read_wellspring(req_sha: str, at: Optional[float] = None, user=Depends(get_admin_user)):
    found = await asyncio.to_thread(eyes.find_wellspring, req_sha, at)
    if not found:
        raise HTTPException(status_code=404, detail='no wellspring record carries this hash')
    return found


@router.get('/eyes/stats')
async def read_stats(user=Depends(get_admin_user)):
    return await asyncio.to_thread(eyes.stats)
