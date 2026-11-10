"""
petal_eyes 👁 — what Petal received, for Lily's eyes (slice A10).

A thin door over utils/petal_eyes.py. Admin-only.

    GET /api/v1/petal/eyes?chat_id&message_id   → { rounds: [record…], kept: disk|ring }
    GET /api/v1/petal/eyes/spill?req_sha[&at]   → { path, view, record } from petal-spill/*/*.json.gz
    GET /api/v1/petal/eyes/stats                → numbers only
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from open_webui.utils import petal_eyes as eyes
from open_webui.utils.auth import get_admin_user
from open_webui.utils.chat_id import is_saved_chat_id

log = logging.getLogger(__name__)
router = APIRouter()


@router.get('/eyes')
async def read_eyes(chat_id: str, message_id: str, user=Depends(get_admin_user)):
    rounds = await asyncio.to_thread(eyes.get, chat_id, message_id)
    if not rounds:
        saved = is_saved_chat_id(chat_id)
        raise HTTPException(
            status_code=404,
            detail=(
                'nothing kept for this reply — it was sent before her eyes opened'
                if saved
                else f'this temp reply left the ring (it keeps the last {eyes.RING_SIZE} sends, until OWUI restarts)'
            ),
        )
    return {'rounds': rounds, 'kept': 'disk' if is_saved_chat_id(chat_id) else 'ring'}


@router.get('/eyes/spill')
async def read_spill(req_sha: str, at: Optional[float] = None, user=Depends(get_admin_user)):
    found = await asyncio.to_thread(eyes.find_spill, req_sha, at)
    if not found:
        raise HTTPException(status_code=404, detail='no spill carries this hash')
    return found


@router.get('/eyes/stats')
async def read_stats(user=Depends(get_admin_user)):
    return await asyncio.to_thread(eyes.stats)
