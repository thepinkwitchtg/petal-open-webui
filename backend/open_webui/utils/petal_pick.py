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
- each reply carries its pick record `petal_pick: {pair, slot, seed, pull, frame_sha[, arm]}` (pull = the
  `petal_steer` it was sent with, or null), on the message and in the 👁 record; downstream filters can read
  it in `__metadata__` (`slot` 0 is the first reply)
- **equal frames (A29b).** the frame is the first reply's *final* request, the bytes about to leave for vLLM
  (every inlet, enricher, state, file, variable and the rendered system prompt, its clock included): the
  second reply sends a deep copy of exactly that, with only its seed (and, for A30, its pull) its own.
  `frame_sha` is each request's sha256 minus those two; the page offers the pick only when both match
- **arms (A30).** 1 in her N picks (Settings → 🌸 Petal, 1 in 3 by default) is an arm: both siblings come from the
  one frame, one goes unsteered (chat's baseline, 0), the other under her pull, the side drawn. its strength
  (A30b) is no longer drawn from a set: the strength search finds it (utils/petal_arms.py: stochastic bisection on
  her picks, steered vs unsteered, inside [0, 0.5] and the card's range). the pull's name is read on her shelf
  (utils/petal_shelf.py, the 💗 filter's door): a ready blend → `{"blend": slug, "strength": s}`, a ♡'d string →
  `{"strings": {id: s}, "strength": 1}` inside its card's range, tagged with the steered reply's id (vLLM notes
  the pin at `<notes>/seen/<tag>.pin.json`). anything else → no arm, a plain pick, and the page's console says
  why. `frame_sha` stays equal (the pull is not part of the frame). each record carries
  `arm: {name, kind, id, strength, steered[, tag, asked]}` (strength 0 on the unsteered side), blind on the page
  until her 💗
- everything the first reply was shown while its frame was built is shown under the second one too, keyed to
  its own id: every chip and citation it received (any filter's, retrieval's), the 9.4 chips that ride in
  `metadata['petal_chips']`, its files, embeds and statuses. neither reply looks more attuned than the
  other before she reads them (a visible frame biases her pick)
- **refused** (the second placeholder is dropped before it exists; the page goes on with one reply): temp
  chats, internal and subagent turns, 🧪 tries, no live page, a continue or a guided regeneration, agents,
  direct connections, models served by anything but an OpenAI-style connection, code interpreter or image
  generation on, anything but two fresh ids for one model
- **🌕 the fusion check (A34)** asks through this module too: its one decider sits in `FUSION_ASK`, beside
  `OFFERS`, asked through `ask_fusion` (utils/petal_fusion.py holds the v1 rate and the rails)
"""

import asyncio
import copy
import hashlib
import json
import logging
import random
import weakref
from typing import Any

from open_webui.utils import petal_arms, petal_fusion, petal_shelf
from open_webui.utils.chat_id import is_saved_chat_id

log = logging.getLogger(__name__)

# what the second reply's tool call says instead of running
HELD = '🍒 a pick sibling never acts: this tool call was not run, so this reply stays a plain sibling'
OWN = ('message_id', 'task_id', 'petal_pick', 'chat_context')  # what each sibling keeps of its own
# plain data in the metadata each sibling holds its own copy of (its rounds never reach the other's)
PLAIN = (
    'variables',
    'files',
    'features',
    'params',
    'chat_variables',
    'user_message',
    'petal_eyes_parts',
    'initial_output',
    'petal_footnote',
    'petal_state',
    'petal_chips',
)
SHOWN = ('statusHistory', 'sources', 'files', 'embeds')  # what a reply is shown, as the chat keeps it
SERVE_WAIT_S = 120  # the second reply waits this long for the first one's request (it takes milliseconds)
# vLLM's short way to ask for a pull: merged into any `petal_steer`, so an arm clears them on both sides
SHORT_PULL = ('petal_blend', 'petal_strength', 'petal_layer', 'petal_tag')
FRAMES: 'weakref.WeakValueDictionary[str, Frame]' = weakref.WeakValueDictionary()  # live frames, by first id
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
    if (model_item or {}).get('pipe') or (model_item or {}).get('owned_by') in ('ollama', 'arena'):
        return 'only an OpenAI-style connection serves a pick'
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


def _copied(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:  # not plain data after all: shared as it is
        return value


def _own_copy(metadata: dict) -> dict:
    meta = {**metadata}
    for key in PLAIN:
        if key in meta:
            meta[key] = _copied(meta[key])
    return meta


class Frame:
    """what the first reply's task builds once, handed to the second's: its metadata and body after every
    inlet (`offer`), then its final request at the send (`sent`). an arm (A30) says which sibling is pulled."""

    def __init__(self, pair: list, arm: dict | None = None):
        self.pair = list(pair)
        self.arm = arm if isinstance(arm, dict) and arm.get('side') in (0, 1) and arm.get('steer') else None
        loop = asyncio.get_running_loop()
        self._ready: asyncio.Future = loop.create_future()
        self._served: asyncio.Future = loop.create_future()
        for future in (self._ready, self._served):
            future.add_done_callback(_quiet)
        FRAMES[self.pair[0]] = self

    @property
    def served(self) -> bool:
        return self._served.done()

    def record_for(self, slot: int) -> dict:
        """what a sibling's pick record says of the arm: its pull's name, kind and id, its own strength (0 on the
        unsteered side), whether it's the steered one, and (that one) its tag · {} for a plain pick."""
        if not self.arm:
            return {}
        what, steered = self.arm.get('what') or {}, slot == self.arm['side']
        rec = {
            'name': what.get('name'),
            'kind': what.get('kind'),
            'id': what.get('id'),
            'strength': what.get('strength') if steered else 0,
            'steered': steered,
        }
        if steered:
            rec['tag'] = self.pair[slot]
            if 'asked' in what:
                rec['asked'] = what['asked']
        return {'arm': rec}

    def steer_for(self, metadata: dict | None) -> Any:
        """a sibling's pull at the send: as its frame built it (a plain pick), the arm's (its steered side, tagged
        with its own id), or none at all (its other side: chat's baseline, 0)."""
        pick = metadata.get('petal_pick') if isinstance(metadata, dict) else None
        if not self.arm or not isinstance(pick, dict) or pick.get('slot') not in (0, 1):
            return _KEEP
        if pick['slot'] != self.arm['side']:
            return None
        return {**copy.deepcopy(self.arm['steer']), 'tag': self.pair[pick['slot']]}

    async def offer(self, form_data: dict, metadata: dict, events: list | None) -> None:
        """the frame as built: every inlet has run (filters, enrichers, states, files, her state lines), and
        what the first reply was shown meanwhile is in the chat."""
        if self._ready.done():
            return
        try:
            body = copy.deepcopy({k: v for k, v in form_data.items() if k != 'metadata'})
            meta = _own_copy(metadata)
            shown = with_chips(await shown_on(metadata), metadata.get('petal_chips'))
            if not self._ready.done():
                self._ready.set_result((body, meta, copy.deepcopy(list(events or [])), shown))
        except Exception as e:  # the first reply never pays for its sibling: only the second one ends
            log.warning(f'🍒 petal pick: the frame could not be copied ({e!r})')
            self.fail(e)

    def sent(self, payload: dict) -> None:
        """the first reply's final request, the bytes about to leave: the frame the second one sends."""
        if not self._served.done():
            self._served.set_result(copy.deepcopy(payload))

    def fail(self, error: BaseException) -> None:
        """the first reply ended before its frame was built or sent: the second goes on alone."""
        for future in (self._ready, self._served):
            if not future.done():
                future.set_exception(error)

    async def take(self, mine: dict) -> tuple:
        """the second reply's copy of the frame: the first one's request, its own ids, and what the first one
        was shown (what Petal got is the same for both, so both show it)."""
        body, metadata, events, shown = await asyncio.shield(self._ready)
        meta = {**_own_copy(metadata), **{k: mine[k] for k in OWN if k in mine}}
        if meta.get('petal_chips') and mine.get('message_id'):  # the chips it's shown, named for it
            meta['petal_chips'] = _rekeyed(meta['petal_chips'], self.pair[0], mine['message_id'])
        form = {**copy.deepcopy(body), 'metadata': meta}
        await echo_shown(shown, self.pair, meta)
        return form, meta, copy.deepcopy(events)

    async def copy_for(self, own: dict) -> dict:
        """the first reply's final request for the second, its seed and its pull its own."""
        try:
            first = await asyncio.wait_for(asyncio.shield(self._served), SERVE_WAIT_S)
        except Exception as e:  # the first one never sent (failed, stopped): this one goes as it built itself
            log.warning(f'🍒 petal pick: the second reply sends its own request ({e!r})')
            return own
        sent = copy.deepcopy(first)
        if 'seed' in own:
            sent['seed'] = own['seed']
        else:
            sent.pop('seed', None)
        pull = _pull(own)
        xargs = dict(sent['vllm_xargs']) if isinstance(sent.get('vllm_xargs'), dict) else {}
        if pull is _KEEP:
            xargs.pop('petal_steer', None)
        else:
            xargs['petal_steer'] = copy.deepcopy(pull)
        if xargs:
            sent['vllm_xargs'] = xargs
        else:
            sent.pop('vllm_xargs', None)
        return sent


def arm_rules(raw: Any) -> dict | None:
    """her arms as the page sends them (`petal_arms`: {every, pull}) · None: no arms this turn. (A30's
    `strengths` may still ride along from an older page: the search chooses now, so they are let go.)"""
    if not isinstance(raw, dict):
        return None
    pull, every = raw.get('pull'), raw.get('every')
    if not isinstance(pull, str) or not pull.strip() or len(pull) > 200:
        return None
    if not isinstance(every, int) or isinstance(every, bool) or not 1 <= every <= 100:
        return None
    return {'every': every, 'pull': pull.strip()}


def _choose(pull: str, pair: list, side: int, rng: Any) -> tuple[dict | None, dict | None, str | None]:
    """the arm's pull at the strength the search tries: its cap read on the shelf (0.5, or where the card ends),
    the try remembered until her pick (both ids)."""
    top, top_what, why = petal_shelf.door(pull, petal_arms.CAP)
    if top is None:
        return None, None, why
    cap, key = abs(float(top_what['strength'])), f"{top_what['kind']}:{top_what['id']}"
    m = petal_arms.point(key, cap, rng)
    steer, what, why = petal_shelf.door(pull, m)
    if steer is not None:
        petal_arms.tried(key, cap, m, pair, side)
    return steer, what, why


async def draw_arm(raw: Any, pair: list | None, *, user: Any = None, rng: Any = None) -> tuple[dict | None, str | None]:
    """🍒 A30 · is this pick an arm? 1 in her N: the side drawn, her pull read on the shelf, its strength the
    search's (A30b). → (arm, why): arm = {side, steer, what} · why = an arm the roll asked for that couldn't be
    served (her console says it; the pick goes on plain) · (None, None): not an arm this time, nothing says so.
    the seam the tuning fork (W) can replace later, to choose the strength per moment."""
    rules = arm_rules(raw)
    if not rules or not pair:
        return None, None
    rng = rng or random
    try:
        if rng.random() * rules['every'] >= 1:
            return None, None
        if user is not None and getattr(user, 'role', None) != 'admin':
            return None, "no arm: the shelf is its keeper's (an admin's)"
        side = rng.randrange(2)
        steer, what, why = await asyncio.to_thread(_choose, rules['pull'], list(pair), side, rng)
    except Exception as e:  # an arm never costs her the pick: it goes on plain
        log.warning(f'🍒 petal pick: no arm ({e!r})')
        return None, 'no arm: the shelf could not be read'
    if steer is None:
        return None, f'no arm: {why}'
    return {'side': side, 'steer': steer, 'what': what}, None


# ── picks that come to her (A30b): the seam a future trigger asks through ────────────────────────────────────
# a trigger is (context) → (bool, why) | None · the fusion check's surprise (its active learning) will be one:
# the moment the system can't tell what she'd want is the moment a pick teaches most. none is built yet.
OFFERS: list = []


def should_offer(context: dict) -> tuple[bool, str]:
    """🍒 A30b · should her next reply in this chat be a pick? asked after each of her turns ends (context:
    user_id, chat_id, message_id: the reply just written); the page arms "next reply" when one says yes, and her
    usual skips still hold (temporary chats, her voice, a call, tools). (False, why) while nothing asks."""
    for trigger in list(OFFERS):
        try:
            got = trigger(context)
        except Exception as e:  # a trigger never costs her the turn
            log.warning(f'🍒 petal pick: an offer trigger failed ({e!r})')
            continue
        if isinstance(got, (tuple, list)) and got and got[0] is True:
            return True, str(got[1] if len(got) > 1 and got[1] else 'a trigger asked')[:200]
    return False, 'nothing asks for a pick yet'


# ── 🌕 the fusion check (A34): one decider, registered here beside OFFERS ────────────────────────────────────
# (context) → (bool, why), asked once a reply is finished (context: utils/petal_fusion.context_for). v1 is her rate,
# aggressive at first and calming as her moons accumulate (petal_fusion.fusion_should_ask). petal-calibrate's
# `offer:fusion` takes this one place in v2 (FUSION_ASK[0] = its client): the page and the routes never change,
# and the rails below hold whoever decides
FUSION_ASK: list = [petal_fusion.fusion_should_ask]


def ask_fusion(context: dict) -> tuple[bool, str]:
    """🌕 A34 · should this finished reply ask her how the fusion is going? the rails first (saved chats only, no
    internal chat or turn, never inside a pick, once a stretch, never in a young stretch), then the one decider."""
    why = petal_fusion.rails(context)
    if why:
        return False, why
    decide = FUSION_ASK[0] if FUSION_ASK else None
    if not callable(decide):
        return False, 'nothing decides the fusion check'
    try:
        got = decide(context)
    except Exception as e:  # a decider never costs her the turn
        log.warning(f'🌕 petal fusion: the decider failed ({e!r})')
        return False, 'the fusion check could not decide'
    if isinstance(got, (tuple, list)) and got:
        said = str(got[1]) if len(got) > 1 and got[1] else ''
        return (True, (said or 'asked')[:200]) if got[0] is True else (False, (said or 'not now')[:200])
    return False, 'not now'


def _pull(payload: dict) -> Any:
    xargs = payload.get('vllm_xargs')
    return xargs['petal_steer'] if isinstance(xargs, dict) and 'petal_steer' in xargs else _KEEP


def frame_sha(payload: dict) -> str:
    """a request's sha256 minus what a sibling owns (its seed, its pull): one frame, one sha."""
    body = {k: v for k, v in payload.items() if k != 'seed'}
    xargs = body.get('vllm_xargs')
    if isinstance(xargs, dict):
        xargs = {k: v for k, v in xargs.items() if k != 'petal_steer'}
        if xargs:
            body['vllm_xargs'] = xargs
        else:
            body.pop('vllm_xargs', None)
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def wire_steer(payload: dict) -> dict:
    """vLLM's OpenAI server types `vllm_xargs` values as str | int | float | list: an object is refused (422,
    `petal_steer` "Input should be a valid string"). petal-strings reads `petal_steer` as a JSON string (the shape
    petal_pull.py in Anamnesis II/III sends), so a steer held as an object is serialised here, at the last moment.
    the pick record keeps the object. (Orchestrator hotfix A30c, nov 19: arms failed on every steered sibling.)"""
    xargs = payload.get('vllm_xargs') if isinstance(payload, dict) else None
    if isinstance(xargs, dict) and isinstance(xargs.get('petal_steer'), (dict, list)):
        payload['vllm_xargs'] = {**xargs, 'petal_steer': json.dumps(xargs['petal_steer'], ensure_ascii=False)}
    return payload


async def serve(metadata: dict | None, payload: dict) -> dict:
    """🍒 A29b · right before the bytes leave for the model (routers/openai.py): the first reply's request
    becomes the frame, the second sends a deep copy of it with its own seed and pull, and each reply's pick
    record learns what was really sent (seed, pull, `frame_sha`). anything else passes untouched."""
    pick = metadata.get('petal_pick') if isinstance(metadata, dict) else None
    if not isinstance(pick, dict) or pick.get('slot') not in (0, 1) or not isinstance(payload, dict):
        return wire_steer(payload)
    if pick.get('frame_sha'):  # a later round of the same reply (its tools ran): the frame was its first request
        return wire_steer(payload)
    try:
        frame = FRAMES.get(str((pick.get('pair') or [''])[0]))
        if frame is not None and pick.get('slot') == 0:
            frame.sent(payload)
        elif frame is not None:
            payload = await frame.copy_for(payload)
    except Exception as e:  # her message is never lost to the pick: it goes as built
        log.warning(f'🍒 petal pick: served as built ({e!r})')
    try:  # in place: the router holds a merged copy of the metadata, the pick record itself is shared
        seed, pull = payload.get('seed'), _pull(payload)
        pick.update(
            {
                'seed': seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
                'pull': None if pull is _KEEP else copy.deepcopy(pull),
                'frame_sha': frame_sha(payload),
            }
        )
    except Exception as e:
        log.warning(f'🍒 petal pick: the frame went unstamped ({e!r})')
    return wire_steer(payload)


async def shown_on(metadata: dict) -> dict:
    """what a reply has been shown so far, as the chat keeps it: statuses, chips (any filter's, the 9.4 ones,
    retrieval's), files and embeds."""
    try:
        chat_id, message_id = metadata.get('chat_id'), metadata.get('message_id')
        if not is_saved_chat_id(chat_id) or not message_id:
            return {}
        from open_webui.models.chats import Chats

        message = await Chats.get_message_by_id_and_message_id(chat_id, message_id) or {}
        return {key: copy.deepcopy(message[key]) for key in SHOWN if message.get(key)}
    except Exception as e:  # what she's shown never costs her the reply
        log.warning(f'🍒 petal pick: what the first reply was shown could not be read ({e!r})')
        return {}


def _chip_key(source: Any) -> Any:
    if not isinstance(source, dict):
        return json.dumps(source, sort_keys=True, default=str)
    sid = (source.get('source') or {}).get('id') if isinstance(source.get('source'), dict) else None
    return sid or json.dumps(source, sort_keys=True, default=str)


def with_chips(shown: dict | None, chips: list | None) -> dict:
    """what the chat kept, plus the 9.4 chips in `metadata['petal_chips']` it may not have kept (each chip once,
    by its id, in the order she was shown them)."""
    shown = dict(shown or {})
    sources = list(shown.get('sources') or [])
    seen = {_chip_key(s) for s in sources}
    for chip in chips or []:
        if isinstance(chip, dict) and _chip_key(chip) not in seen:
            seen.add(_chip_key(chip))
            sources.append(copy.deepcopy(chip))
    if sources:
        shown['sources'] = sources
    return shown


def _rekeyed(value: Any, first: str, mine: str) -> Any:
    """a copy with every id that names the first reply (`…-<first id>`) naming the second instead."""
    if isinstance(value, dict):
        return {
            k: (
                v[: -len(first)] + mine
                if k in ('id', 'source', 'message_id') and isinstance(v, str) and v.endswith(first)
                else _rekeyed(v, first, mine)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_rekeyed(v, first, mine) for v in value]
    return copy.deepcopy(value)


async def echo_shown(shown: dict | None, pair: list, metadata: dict) -> int:
    """what the first reply was shown while its frame was built, shown under the second one too, keyed to its
    own id: nothing runs again, so neither reply looks different from the other before she reads them.
    returns how many things were shown."""
    try:
        first, mine = (pair or [None])[0], metadata.get('message_id')
        if not shown or not first or not mine or first == mine:
            return 0
        from open_webui.socket.main import get_event_emitter

        emit = await get_event_emitter(metadata)
        if not emit:
            return 0
        n = 0
        for status in shown.get('statusHistory') or []:
            await emit({'type': 'status', 'data': _rekeyed(status, first, mine)})
            n += 1
        for source in shown.get('sources') or []:
            await emit({'type': 'source', 'data': _rekeyed(source, first, mine)})
            n += 1
        for key in ('files', 'embeds'):
            if shown.get(key):
                await emit({'type': key, 'data': {key: _rekeyed(shown[key], first, mine)}})
                n += len(shown[key])
        return n
    except Exception as e:  # a chip never costs her the reply
        log.warning(f'🍒 petal pick: what the first reply was shown stayed with it ({e!r})')
        return 0


def dress(form_data: dict, metadata: dict, steer: Any = _KEEP) -> dict:
    """🍒 the one place two siblings differ, right before the send. the first goes as built; the second samples
    on its own seed. `steer` (A30, from `Frame.steer_for`): a `petal_steer` value, or None for unsteered, makes
    the two differ in the pull, nothing else (a plain pick keeps the pull its frame built). the reply's pick
    record learns its seed and its pull here."""
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
        for key in SHORT_PULL:  # the pull is this one, whole: nothing else rides beside it (or for the other side)
            xargs.pop(key, None)
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
