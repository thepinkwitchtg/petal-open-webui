"""
petal_shelf 💗 — what her shelf offers as a pull, for Settings → 🌸 Petal (slice A30 · arms).

    GET /api/v1/petal/shelf/pulls
      ← {ok, why, from, body, strung, pulls: [{name, kind: 'blend' | 'string', id, ready, waiting?, range?}]}

read where the 💗 filter reads (utils/petal_shelf.py: petal-emotions' home.json → owui_view). nothing is written,
nothing is asked of vLLM. admin only: her shelf's names are hers.
"""

import asyncio

from fastapi import APIRouter, Depends

from open_webui.utils import petal_shelf as shelf
from open_webui.utils.auth import get_admin_user

router = APIRouter()


@router.get('/shelf/pulls')
async def shelf_pulls(user=Depends(get_admin_user)):
    return await asyncio.to_thread(shelf.pulls)
