"""
petal_shelf 💗 — what her shelf offers as a pull, for Settings → 🌸 Petal (slice A30 · arms), and the picks'
small doors beside it (A30b).

    GET /api/v1/petal/shelf/pulls
      ← {ok, why, from, body, strung, pulls: [{name, kind: 'blend' | 'string', id, ready, waiting?, range?}],
         search: {'<kind>:<id>': {cap, lo, hi, centre, width, phase, steps, reopens, pull}}}

read where the 💗 filter reads (utils/petal_shelf.py: petal-emotions' home.json → owui_view). nothing is written,
nothing is asked of vLLM. `search` is each pull's strength search (utils/petal_arms.py): the interval its 90%
of belief lies in, its centre, its phase (searching · narrowing · stable).

    GET /api/v1/petal/pick/offer?chat_id=…&message_id=…   (A30b)
      ← {offer: bool, why}

the seam picks that come to her ask through: after each of her turns ends, the page asks whether the next reply
should be a pick (petal_pick.should_offer). nothing asks yet; temporary chats and chats not hers never do.

admin only: her shelf's names are hers, and so is the search.
"""

import asyncio

from fastapi import APIRouter, Depends

from open_webui.utils import petal_arms, petal_pick
from open_webui.utils import petal_shelf as shelf
from open_webui.utils.auth import get_admin_user
from open_webui.utils.chat_id import is_saved_chat_id

router = APIRouter()


@router.get('/shelf/pulls')
async def shelf_pulls(user=Depends(get_admin_user)):
    out = await asyncio.to_thread(shelf.pulls)
    try:
        out['search'] = await asyncio.to_thread(petal_arms.views)
    except Exception:  # the search never costs her the shelf
        out['search'] = {}
    return out


@router.get('/pick/offer')
async def pick_offer(chat_id: str = '', message_id: str = '', user=Depends(get_admin_user)):
    if not is_saved_chat_id(chat_id):
        return {'offer': False, 'why': 'temporary chats never pick'}
    from open_webui.models.chats import Chats

    if not await Chats.get_chat_by_id_and_user_id(chat_id, user.id):
        return {'offer': False, 'why': 'not her chat'}
    offer, why = petal_pick.should_offer({'user_id': user.id, 'chat_id': chat_id, 'message_id': message_id})
    return {'offer': offer, 'why': why}
