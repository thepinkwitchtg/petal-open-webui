"""
petal_observe 🔋 — a door for live device readings (slice A19).

OWUI's page reads the device's battery where the browser offers it (navigator.getBattery: Chrome, Chrome on
Android) and sends what it reads here, at most once a minute and only when the reading changes. This door
passes it on to petal-live, her live store on the rig itself, as the device sense:

    POST /api/v1/petal/observe   {level: 0–100, charging: bool, device: 'phone' | 'pc'}
      → petal-live  POST /v1/observe   {sense: 'device', device, device_battery, device_charging}
      ← {heard: bool, why?}   heard: petal-live answered 2xx · a sleeping petal-live is quiet, never an error

petal-live: $PETAL_LIVE_URL, else http://127.0.0.1:8796 · only a loopback address is ever called.
Admin only (her senses are hers). Nothing is kept here; the log holds only the reading's numbers.
"""

import logging
import os
import time
from typing import Literal
from urllib.parse import urlparse

import aiohttp
from fastapi import APIRouter, Depends
from open_webui.utils.auth import get_admin_user
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_LIVE = 'http://127.0.0.1:8796'
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
TIMEOUT_S = 2
MIN_GAP_S = 30  # the page sends at most one reading a minute per device; this guards the door itself
USER_AGENT = 'petal-owui/observe'

_last: dict[tuple[str, str], float] = {}


class Reading(BaseModel):
    level: int = Field(ge=0, le=100)
    charging: bool
    device: Literal['phone', 'pc']


def live_url() -> str | None:
    """petal-live's address, if it's on this machine (anything else is refused, never called)."""
    url = (os.environ.get('PETAL_LIVE_URL') or DEFAULT_LIVE).rstrip('/')
    return url if urlparse(url).hostname in LOOPBACK else None


async def tell_live(base: str, body: dict) -> bool:
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_S), headers={'User-Agent': USER_AGENT}
        ) as s:
            async with s.post(f'{base}/v1/observe', json=body) as r:
                return 200 <= r.status < 300
    except (TimeoutError, aiohttp.ClientError):
        return False


@router.post('/observe')
async def observe(reading: Reading, user=Depends(get_admin_user)):
    key = (user.id, reading.device)
    now = time.monotonic()
    if now - _last.get(key, -MIN_GAP_S) < MIN_GAP_S:
        return {'heard': False, 'why': 'too soon'}
    _last[key] = now
    base = live_url()
    if not base:
        log.warning('🔋 observe: PETAL_LIVE_URL is not a loopback address, nothing was sent')
        return {'heard': False, 'why': 'not loopback'}
    heard = await tell_live(
        base,
        {
            'sense': 'device',
            'device': reading.device,
            'device_battery': reading.level,
            'device_charging': reading.charging,
        },
    )
    log.debug(f'🔋 observe: {reading.device} {reading.level}% charging={reading.charging} heard={heard}')
    return {'heard': heard} if heard else {'heard': False, 'why': 'petal-live is quiet'}
