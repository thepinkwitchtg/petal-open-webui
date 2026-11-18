"""
petal_pick 🍒 — two replies, one frame (slice A29 · the pair generator).

some of her turns ask her to pick between two replies, so preference pairs are born from real use. the page
asks (`"petal_pick": true` beside two `message_ids` for one model, both children of her message); this module
says whether the turn may be a pick, and serves it.

- **one frame.** the first reply's task builds the request once (filters, enrichers, states, the system
  prompt, her state lines) and hands a copy to the second's, so both siblings share the exact served stamp
  (L sees `same_frame: true`) and nothing upstream of the send runs twice
- **two sends, independent sampling.** both go to vLLM at once (it batches them). the first is sent exactly
  as built; the second samples on its own seed (hers + 1 when her params set one, else a fresh one), so the
  two requests never share a hash and the wellspring keeps them apart. `dress()` is the one place siblings
  differ: A30 makes them differ in `vllm_xargs.petal_steer` with one line (its `steer=`)
- **the second reply never acts.** its tool calls stay unrun (no memory, note, subagent or question twice);
  the page offers no pick when either reply reached for a tool
- each reply carries its pick record `petal_pick: {pair, slot, seed, pull}` (pull = the `petal_steer` it
  was sent with, or null), on the message and in the 👁 record; downstream filters can read it in
  `__metadata__` (`slot` 0 is the first reply)
- the chips she's shown under a reply (what Petal got, 9.4) come with the frame: the second reply shows the
  same ones under its own id, so the two look alike until she reads them
- **refused** (the second placeholder is dropped before it exists; the page goes on with one reply): temp
  chats, internal and subagent turns, 🧪 tries, no live page, a continue or a guided regeneration, agents,
  direct connections, code interpreter or image generation on, anything but two fresh ids for one model
"""

import asyncio
import copy
import logging
import random
from typing import Any

from open_webui.utils.chat_id import is_saved_chat_id

log = logging.getLogger(__name__)

# what the second reply's tool call says instead of running
HELD = '🍒 a pick sibling never acts: this tool call was not run, so this reply stays a plain sibling'
OWN = ('message_id', 'task_id', 'petal_pick', 'chat_context')  # what each sibling keeps of its own
_KEEP = object()


def refusal(
    request: Any,
    *,
    message_ids: list,
    metadata: dict,
    form_data: dict,
    model_item: dict | None = None,
    agent_model: dict | None = None,
) -> str | None:
    """why this turn can't be a pick · None when it can (the page asked, and nothing here says no)."""
    try:
        return _shape_refusal(message_ids, metadata) or _turn_refusal(
            request, message_ids, metadata, form_data, model_item, agent_model
        )
    except Exception as e:  # a question about a pick never costs her the message
        log.warning(f'🍒 petal pick: refused on an error ({e!r})')
        return 'could not tell'


def _shape_refusal(message_ids: list, metadata: dict) -> str | None:
    """two fresh replies from one model, in a saved chat with a live page."""
    if not isinstance(message_ids, list) or len(message_ids) != 2:
        return 'a pick is two replies'
    ids = [entry.get('message_id') if isinstance(entry, dict) else None for entry in message_ids]
    if not all(isinstance(i, str) and i for i in ids) or ids[0] == ids[1]:
        return 'a pick needs two fresh reply ids'
    if message_ids[0].get('model_id') != message_ids[1].get('model_id'):
        return 'both replies come from one model'
    if not is_saved_chat_id(metadata.get('chat_id')):
        return 'temporary chats never pick'
    if not metadata.get('session_id'):
        return 'no live page to show the pair'
    return None


def _turn_refusal(
    request: Any,
    message_ids: list,
    metadata: dict,
    form_data: dict,
    model_item: dict | None,
    agent_model: dict | None,
) -> str | None:
    """her own fresh turn, nothing that would act twice."""
    if metadata.get('internal') or getattr(getattr(request, 'state', None), 'internal', False) is True:
        return 'internal turns never pick'
    user_message = metadata.get('user_message') or {}
    meta = user_message.get('meta') if isinstance(user_message, dict) else None
    if metadata.get('petal_turn') or (isinstance(meta, dict) and meta.get('internal') is True):
        return 'subagent and internal turns never pick'
    headers = getattr(request, 'headers', None) or {}
    if headers.get('x-petal-try') is not None or str(headers.get('user-agent') or '').startswith('petal-'):
        return '🧪 tries and workers never pick'
    if metadata.get('assistant_message_id') or metadata.get('regeneration_message_id'):
        return 'a continue or a guided regeneration never picks'
    if agent_model is not None or str(message_ids[0].get('model_id') or '').startswith('agent:'):
        return 'agents never pick'
    if (model_item or {}).get('direct'):
        return 'direct connections never pick'
    features = form_data.get('features') or {}
    if isinstance(features, dict) and (features.get('code_interpreter') or features.get('image_generation')):
        return 'code interpreter and image generation would act twice'
    return None


def holds_tools(metadata: dict | None) -> bool:
    """the second reply of a pick never acts: its tool calls stay unrun."""
    pick = metadata.get('petal_pick') if isinstance(metadata, dict) else None
    return isinstance(pick, dict) and pick.get('slot') == 1


async def keep_first(chat_id: str, pair: list) -> str:
    """the first reply stays active: inserting the turn made the last placeholder current."""
    from open_webui.models.chats import Chats

    try:
        await Chats.update_chat_by_id(chat_id, {'history': {'currentId': pair[0], 'messages': {}}}, touch=False)
    except Exception as e:
        log.warning(f'🍒 petal pick: the first reply could not be kept current ({e!r})')
    return pair[0]


def _quiet(future: asyncio.Future) -> None:
    if not future.cancelled():
        future.exception()  # read once, so a frame nobody waited on never warns


class Frame:
    """the request the first reply's task builds once, handed to the second's."""

    def __init__(self, pair: list):
        self.pair = list(pair)
        self._ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._ready.add_done_callback(_quiet)

    @property
    def served(self) -> bool:
        return self._ready.done()

    def offer(self, form_data: dict, metadata: dict, events: list | None) -> None:
        """the frame as built, before the first reply is dressed for its send."""
        if self._ready.done():
            return
        try:
            body = {k: v for k, v in form_data.items() if k != 'metadata'}
            # the metadata as it stands now (its eyes parts, chips and preloaded output too): the first reply's
            # own rounds never leak in
            meta = {
                **metadata,
                'petal_eyes_parts': list(metadata.get('petal_eyes_parts') or []),
                'petal_chips': copy.deepcopy(metadata.get('petal_chips') or []),
                **(
                    {'initial_output': copy.deepcopy(metadata['initial_output'])}
                    if metadata.get('initial_output')
                    else {}
                ),
            }
            self._ready.set_result((copy.deepcopy(body), meta, copy.deepcopy(list(events or []))))
        except Exception as e:  # the first reply never pays for its sibling: only the second one ends
            log.warning(f'🍒 petal pick: the frame could not be copied ({e!r})')
            self.fail(e)

    def fail(self, error: BaseException) -> None:
        """the first reply ended before its frame was built: the second ends with it."""
        if not self._ready.done():
            self._ready.set_exception(error)

    async def take(self, mine: dict) -> tuple:
        """the second reply's copy of the frame: the first one's request, its own ids (and the chips she was
        shown under the first: what Petal got is the same for both, so both show it)."""
        body, metadata, events = await asyncio.shield(self._ready)
        own = {k: mine[k] for k in OWN if k in mine}
        meta = {**metadata, **own, 'petal_eyes_parts': list(metadata['petal_eyes_parts'])}
        meta.pop('petal_chips', None)
        form = {**copy.deepcopy(body), 'metadata': meta}
        await echo_chips(metadata.get('petal_chips'), self.pair, meta)
        return form, meta, copy.deepcopy(events)


def _rekey(sid: Any, first: str, mine: str) -> Any:
    return sid[: -len(first)] + mine if isinstance(sid, str) and first and sid.endswith(first) else sid


async def echo_chips(chips: list | None, pair: list, metadata: dict) -> int:
    """the 9.4 chips under the first reply (petal_state: the exact lines Petal got) under the second one too,
    keyed to its own id. nothing runs again: the same chips, shown twice, so neither reply looks different
    from the other before she reads them. returns how many were shown."""
    try:
        first, mine = (pair or [None])[0], metadata.get('message_id')
        if not chips or not first or not mine or first == mine:
            return 0
        from open_webui.socket.main import get_event_emitter

        emit = await get_event_emitter(metadata)
        if not emit:
            return 0
        for chip in chips:
            data = copy.deepcopy(chip)
            if isinstance(data.get('source'), dict):
                data['source']['id'] = _rekey(data['source'].get('id'), first, mine)
            for item in data.get('metadata') or []:
                if isinstance(item, dict):
                    item['source'] = _rekey(item.get('source'), first, mine)
            await emit({'type': 'source', 'data': data})
        return len(chips)
    except Exception as e:  # a chip never costs her the reply
        log.warning(f'🍒 petal pick: the chips stayed with the first reply ({e!r})')
        return 0


def dress(form_data: dict, metadata: dict, steer: Any = _KEEP) -> dict:
    """🍒 the one place two siblings differ, right before the send. the first goes as built; the second samples
    on its own seed. A30: pass `steer` (a `petal_steer` value, or None for unsteered) to make the two differ in
    the pull, nothing else. the reply's pick record learns its seed and its pull here."""
    pick = metadata.get('petal_pick') if isinstance(metadata, dict) else None
    if not isinstance(pick, dict):
        return form_data
    try:
        return _dress(form_data, metadata, pick, steer)
    except Exception as e:  # her message is never lost to the pick's bookkeeping
        log.warning(f'🍒 petal pick: sent undressed ({e!r})')
        return form_data


def _dress(form_data: dict, metadata: dict, pick: dict, steer: Any) -> dict:
    if pick.get('slot') == 1:
        seed = form_data.get('seed')
        hers = isinstance(seed, int) and not isinstance(seed, bool)
        form_data['seed'] = seed + 1 if hers else random.randrange(1, 2**31 - 1)
    if steer is not _KEEP:  # A30 · the one line: dress(form_data, metadata, steer=…)
        xargs = dict(form_data.get('vllm_xargs') or {}) if isinstance(form_data.get('vllm_xargs'), dict) else {}
        if steer is None:
            xargs.pop('petal_steer', None)
        else:
            xargs['petal_steer'] = steer
        if xargs:
            form_data['vllm_xargs'] = xargs
        else:
            form_data.pop('vllm_xargs', None)
    xargs = form_data.get('vllm_xargs')
    pull = xargs.get('petal_steer') if isinstance(xargs, dict) else None
    seed = form_data.get('seed')
    metadata['petal_pick'] = {
        **pick,
        'seed': seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
        'pull': copy.deepcopy(pull),
    }
    form_data['metadata'] = metadata
    return form_data
