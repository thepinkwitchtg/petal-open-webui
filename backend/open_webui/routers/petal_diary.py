"""
petal_diary 📔 — Lily's diary (slice A11). A thin door over utils/petal_diary.py (self-tested):
    python3 backend/open_webui/utils/petal_diary.py

Home: $PETAL_APP_DATA/petal-diary/diary.jsonl   (gold tier · 700/600 · append-only)
Admin-only. Nothing here reaches Petal: `petal_sees` only marks what she may read one day.

    GET  /api/v1/petal/diary/stream?q&before&limit  → { items: [note | orbit | climax | trip | vow | vow_end], more }
    POST /api/v1/petal/diary   { kind: note|amend|void, via, … }  → { id }
    GET  /api/v1/petal/diary/stats                   → numbers only
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from open_webui.utils import petal_diary as diary
from open_webui.utils import petal_markers_core as core
from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)
router = APIRouter()


def _guard(fn):
    try:
        return fn()
    except (diary.DiaryError, core.MarkerError) as e:
        raise HTTPException(400, detail=str(e))
    except OSError as e:
        log.exception('petal diary: disk')
        raise HTTPException(500, detail=f'the diary could not touch the page: {e.strerror or e}')


# sync handlers on purpose: FastAPI runs them in its threadpool, so the file locks never block the loop


@router.get('/diary/stream')
def diary_stream(q: Optional[str] = None, before: Optional[int] = None, limit: int = 300, user=Depends(get_admin_user)):
    def go():
        g = core.Garden()
        g.ensure()
        mview, _ = core.settle(g, int(time.time()))  # any reader notices crossed boundaries
        return diary.stream(diary.Diary(), mview, q=q, before=before, limit=limit)

    return _guard(go)


@router.post('/diary')
def diary_write(body: dict = Body(...), user=Depends(get_admin_user)):
    return _guard(lambda: diary.write(diary.Diary(), body))


@router.get('/diary/stats')
def diary_stats(user=Depends(get_admin_user)):
    return _guard(lambda: diary.stats(diary.Diary()))
