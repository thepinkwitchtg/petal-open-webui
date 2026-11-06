"""
petal_markers 🌙 — trip markers on the Petal rig (sprint contract 1).

A thin door over utils/petal_markers_core.py (pure python, self-tested):
    python3 backend/open_webui/utils/petal_markers_core.py

Home: $PETAL_APP_DATA/trip-markers/   (default ~/Gardens/Documents/Petal-App-Data)
Admin-only: nobody else on the instance can read or write the markers.
Petal does not see any of this yet: no filter, no system prompt injection (v0).

    GET  /api/v1/petal/markers/now               → { status, integration, also, last_dose, table, now }
    GET  /api/v1/petal/markers?from&to[&kind&chat_id&include_void]  → replayed events in range
    POST /api/v1/petal/markers   { kind, via, … } → { id }
    POST /api/v1/petal/markers/trip  { substance, dose, taken_at, ended_at, dry_run, … } → a past trip, previewed or locked in
    GET  /api/v1/petal/markers/stats?from&to     → numbers only
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from open_webui.utils import petal_markers_core as core
from open_webui.utils.auth import get_admin_user
from open_webui.utils.chat_id import is_saved_chat_id

log = logging.getLogger(__name__)
router = APIRouter()


def _garden() -> core.Garden:
    g = core.Garden()  # reads $PETAL_APP_DATA each time, so a launcher env change just works
    planted = g.ensure()['planted']
    if planted:
        log.info(f'🌙 trip markers: first run, planted {", ".join(planted)} in {g.dir}')
    return g


def _guard(fn):
    try:
        return fn()
    except core.MarkerError as e:
        raise HTTPException(400, detail=str(e))
    except OSError as e:
        log.exception('petal markers: disk')
        raise HTTPException(500, detail=f'trip markers could not touch the garden: {e.strerror or e}')


def _chip_table(table: dict) -> list[dict]:
    """what the chip needs to draw the picker — labels, emoji, units, tier thresholds (no notes)."""
    out = []
    for key, e in table.items():
        if not isinstance(e, dict):
            continue
        strains = e.get('strains') if isinstance(e.get('strains'), dict) else {}
        mut = e.get('mutation') if isinstance(e.get('mutation'), dict) else None
        pur = e.get('purge') if isinstance(e.get('purge'), dict) else None
        out.append({
            'key': key,
            'label': e.get('label') or key,
            'emoji': e.get('emoji') or '✧',
            'dose_unit': e.get('dose_unit'),
            'needs_dose': core.needs_dose(key, table),
            # 1.2 · strains (potency/duration_x null = note only), mutation and purge, when her row has them
            'strain_default': e.get('strain_default') if e.get('strain_default') in strains else None,
            'strains': [core.strain_of(e, k) for k in strains if isinstance(strains[k], dict)],
            'mutation_h': core._num((mut or {}).get('duration_h')),
            'purge_after_h': core._mid((pur or {}).get('integration_after_h')),
            'tiers': [{'from': t.get('from'), 'label': t.get('label')}
                      for t in (e.get('tiers') or []) if isinstance(t, dict)],
        })
    return out


# sync handlers on purpose: FastAPI runs them in its threadpool, so the file lock never blocks the loop


@router.get('/markers/now')
def markers_now(user=Depends(get_admin_user)):
    def go():
        now = int(time.time())
        view, _ = core.settle(_garden(), now)
        return {**core.now_view(view, now), 'table': _chip_table(view.table)}

    return _guard(go)


@router.get('/markers/preview')
def markers_preview(
    substance: str, dose: Optional[str] = None, strain: Optional[str] = None, user=Depends(get_admin_user)
):
    """what a dose would mean before it's set: duration, integration_from, tier (numbers + her labels)."""

    def go():
        g = _garden()
        p = core.profile(substance, dose, g.table(), g.settings(), strain or None)
        keys = ('duration_h', 'integration_from', 'peak_h', 'tier', 'why_no_end', 'dose_unit', 'dose_eff', 'strain')
        return {k: p[k] for k in keys}

    return _guard(go)


@router.get('/markers')
def markers_in_range(
    from_: int = Query(0, alias='from'),
    to: Optional[int] = None,
    kind: Optional[str] = None,
    chat_id: Optional[str] = None,
    include_void: bool = False,
    user=Depends(get_admin_user),
):
    def go():
        now = int(time.time())
        view, _ = core.settle(_garden(), now)
        return core.events_in(view, from_, to if to is not None else now, kind, chat_id, include_void)

    return _guard(go)


@router.post('/markers')
def markers_write(body: dict = Body(...), user=Depends(get_admin_user)):
    # 1.1: harvest lines are petal-ledger's alone — it imports the core and writes under the lock
    if body.get('kind') == 'harvest' or body.get('via') == 'ledger':
        raise HTTPException(400, detail='harvest lines are written by petal-ledger, not through this door')
    # contract 0: a climax needs a saved message to anchor to — temp and channel chats are dimmed
    if body.get('kind') == 'climax' and not is_saved_chat_id(str(body.get('chat_id') or '')):
        raise HTTPException(409, detail='temporary chat — no saved message to anchor a climax to')

    def go():
        return {'id': core.write(_garden(), body)['id']}

    return _guard(go)


@router.post('/markers/trip')
def markers_trip(body: dict = Body(...), user=Depends(get_admin_user)):
    """a new status, past or present, with her real end if she knows it (slice A6).
    { substance, dose, strain?, taken_at, ended_at|null, note?, via, temp, dry_run }
    → { id|null, timeline (with phase), due: [parts], lines: [kinds], written }
    one lock: the start line, then an amend of ends_at (her end is later) or a status.end (earlier).
    dry_run walks the very same path and writes nothing — the preview can't disagree with the write."""
    if body.get('via') == 'ledger':
        raise HTTPException(400, detail='harvest lines are written by petal-ledger, not through this door')
    fields = {k: body[k] for k in ('substance', 'dose', 'strain', 'taken_at', 'note', 'via', 'temp', 'duration_h')
              if k in body}

    def go():
        return core.trip(_garden(), fields, ended=body.get('ended_at'), dry_run=bool(body.get('dry_run')))

    return _guard(go)


@router.get('/markers/stats')
def markers_stats(
    from_: int = Query(0, alias='from'),
    to: Optional[int] = None,
    user=Depends(get_admin_user),
):
    def go():
        now = int(time.time())
        view, _ = core.settle(_garden(), now)
        return core.stats(view, from_, to if to is not None else now, now)

    return _guard(go)
