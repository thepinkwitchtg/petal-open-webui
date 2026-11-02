"""
petal_harvest 🌷 — writes a chat harvest (rendered in the browser) onto the Petal rig.

The frontend already filters + renders the chats; this router only plants the files,
so it doesn't depend on OWUI's chat model internals and survives upstream merges.

Root folder: $PETAL_HARVEST_DIR
  default → /home/pinklily69/Gardens/Documents/Petal-App-Data/open-webui/harvests
Admin-only: nobody else on the instance can write to the garden.
"""

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)
router = APIRouter()

HARVEST_ROOT = Path(
    os.environ.get(
        'PETAL_HARVEST_DIR',
        '/home/pinklily69/Gardens/Documents/Petal-App-Data/open-webui/harvests',
    )
).expanduser()

_BAD = re.compile(r'[\\:*?"<>|\x00-\x1f]')


def _safe_part(part: str) -> str:
    part = _BAD.sub(' ', part).strip().strip('.')
    part = re.sub(r'\s+', ' ', part)
    return part[:150] or 'untitled'


def _safe_rel(name: str) -> Path:
    # allow one level of subfolder (json/...), never escape the harvest folder
    parts = [p for p in name.replace('\\', '/').split('/') if p not in ('', '.', '..')]
    if not parts:
        raise HTTPException(400, detail=f'bad file name: {name!r}')
    return Path(*[_safe_part(p) for p in parts[-2:]])


def _fresh_dir(base: Path) -> Path:
    if not base.exists():
        return base
    i = 2
    while True:
        cand = base.with_name(f'{base.name} ({i})')
        if not cand.exists():
            return cand
        i += 1


class HarvestFile(BaseModel):
    name: str
    content: str


class HarvestForm(BaseModel):
    folder: str
    files: list[HarvestFile]


@router.get('/harvest/info')
async def harvest_info(user=Depends(get_admin_user)):
    return {'root': str(HARVEST_ROOT), 'exists': HARVEST_ROOT.exists()}


@router.post('/harvest')
async def plant_harvest(form: HarvestForm, user=Depends(get_admin_user)):
    if not form.files:
        raise HTTPException(400, detail='nothing to harvest in that range')

    target = _fresh_dir(HARVEST_ROOT / _safe_part(form.folder))
    root = HARVEST_ROOT.resolve()

    try:
        target.mkdir(parents=True, exist_ok=False)
        for f in form.files:
            path = (target / _safe_rel(f.name)).resolve()
            if root not in path.parents:
                raise HTTPException(400, detail=f'refusing path outside garden: {f.name!r}')
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + '.part')
            tmp.write_text(f.content, encoding='utf-8')
            tmp.replace(path)
    except HTTPException:
        raise
    except OSError as e:
        log.exception('petal harvest failed')
        raise HTTPException(500, detail=f'could not write harvest: {e}')

    log.info(f'🌷 harvest planted: {target} ({len(form.files)} files)')
    return {'path': str(target), 'files': len(form.files)}
