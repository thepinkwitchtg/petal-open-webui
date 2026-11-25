"""
🌸🧵 petal follow — the rig carries a reply into her voice while it's still being written (A45)
────────────────────────────────────────────────────────────────────────────────────────────────
with the phone's screen off, the page sleeps: its timers are throttled or frozen, its socket goes quiet,
and a stream fed by the page (A37) starves at the end of what was queued. so the rig feeds it instead.

  the reply's own words · the chat middleware hands each streaming reply's live output here
                          (provide(message_id, full_output)), and its final output when it ends or is
                          stopped (done(message_id, output)). nothing is copied while she writes: a
                          follower asks for a snapshot when it looks.
  a follower            · one per growing stream that asked to follow. it looks every POLL_S, cuts the
                          reply into the page's own sentences (petal_words: visible → whole), and feeds
                          the stream what's new. done ends it, so does her stop (the stream ends) or
                          a reply nobody can see any more (GROW_IDLE_S with no source).
  segments              · a stream may follow several replies in turn (🍒 A38's pick read aloud: her cue,
                          the first reply, her cue, the second). each sentence carries its reply's id and
                          its place in that reply (the cue is place 0), so the page lights the right
                          words. her 💗 can let the later segments go (cut()): the stream keeps only the
                          replies up to the chosen one (Growing.keep) and ends where it ends.
  a whole segment       · after-she-finishes reads a reply only once it's written (`whole`): the follower
                          waits for done before it gives a word.

the page opens the stream once and never feeds it: waking up, it finds the rig already ahead.
memory only: no word of hers is written by this module.
"""

from __future__ import annotations

import asyncio
import logging
import time

try:
    from open_webui.utils import petal_words as words
except ImportError:  # alone, beside petal_words.py (tests)
    import petal_words as words

log = logging.getLogger(__name__)

POLL_S = 0.25  # how often a follower looks at the reply (the page looked every 280 ms)
DB_EVERY_S = 2.0  # with no live source, how often the saved chat is read instead
ENDED_TTL_S = 600  # a finished reply's words wait this long for a follower that comes late
LIVE_TTL_S = 3 * 3600  # a live source nobody closed (a crash) is forgotten after this

_live: dict[str, dict] = {}  # message_id → {"fn": the middleware's full_output, "t"}
_ended: dict[str, dict] = {}  # message_id → {"output", "t"}


def _sweep(now: float) -> None:
    for k in [k for k, v in _live.items() if now - v["t"] > LIVE_TTL_S]:
        _live.pop(k, None)
    for k in [k for k, v in _ended.items() if now - v["t"] > ENDED_TTL_S]:
        _ended.pop(k, None)


def provide(message_id, fn) -> None:
    """the middleware: this reply is being written; fn() returns its output as it stands"""
    if isinstance(message_id, str) and message_id and callable(fn):
        now = time.monotonic()
        _sweep(now)
        _ended.pop(message_id, None)
        _live[message_id] = {"fn": fn, "t": now}


def done(message_id, output) -> None:
    """the middleware: this reply is finished (or she stopped it): here is all of it"""
    if isinstance(message_id, str) and message_id:
        _live.pop(message_id, None)
        _ended[message_id] = {"output": list(output or []), "t": time.monotonic()}


def drop(message_id) -> None:
    """the middleware: this reply broke off without an ending; a follower falls back to the saved chat"""
    if isinstance(message_id, str):
        _live.pop(message_id, None)


def _pulse(out) -> int:
    """how much the reply holds, every part of it (thinking and tool calls too): it moves while she writes"""
    try:
        return len(repr(out))
    except Exception:
        return 0


def snapshot(message_id) -> tuple[str, bool, int] | None:
    """(the reply's words as the page shows them, finished, its pulse) from the live source, or None"""
    e = _ended.get(message_id)
    if e is not None:
        return words.visible(None, e["output"]), True, 0
    lv = _live.get(message_id)
    if lv is None:
        return None
    try:
        out = lv["fn"]()
    except Exception:  # the writer's state moved under us: look again next time
        return None
    return words.visible(None, out), False, _pulse(out)


async def saved_snapshot(chat_id, message_id) -> tuple[str, bool, int] | None:
    """the saved chat's copy of the reply (a stream message, a reply that ended before anyone followed)"""
    if not isinstance(chat_id, str) or not chat_id or chat_id.startswith("local:"):
        return None
    try:
        from open_webui.models.chats import Chats

        m = await Chats.get_message_by_id_and_message_id(chat_id, message_id)
    except Exception:
        return None
    if not isinstance(m, dict):
        return None
    return words.visible(m.get("content"), m.get("output")), bool(m.get("done")), _pulse((m.get("content"), m.get("output")))


class Segment:
    """one reply a stream follows: its id and chat, the cue said before it (🍒), whether it waits to be
    written whole, the page's copy of it (a temporary chat's stream message has no other home), and how
    many of its sentences the stream already holds"""

    def __init__(self, message_id: str, chat_id: str | None = None, lead: str = "", whole: bool = False,
                 text: str | None = None, finished: bool = False, given: int = 0):
        self.message_id, self.chat_id, self.lead, self.whole = message_id, chat_id, lead or "", bool(whole)
        self.text, self.finished, self.given = text, bool(finished), max(0, int(given))
        self.lead_given = False

    @classmethod
    def of(cls, raw) -> "Segment | None":
        if not isinstance(raw, dict) or not isinstance(raw.get("message_id"), str) or not raw["message_id"]:
            return None
        chat = raw.get("chat_id") if isinstance(raw.get("chat_id"), str) else None
        lead = raw.get("lead") if isinstance(raw.get("lead"), str) else ""
        text = raw.get("text") if isinstance(raw.get("text"), str) else None
        given = raw.get("given") if isinstance(raw.get("given"), int) and not isinstance(raw.get("given"), bool) else 0
        return cls(raw["message_id"][:128], chat, lead[:400], raw.get("whole") is True, text, raw.get("finished") is True, given)


class Follower:
    """feeds one growing stream from the replies it follows (see the module's note)"""

    def __init__(self, parts, segments: list[Segment], trace=None, take=None, idle_s: float = 180.0):
        self.parts = parts  # petal_stream.Growing
        self.segments = segments
        self.trace = trace
        self.take = take  # (trace, first idx, parts) → the trace keeps one take per sentence
        self.idle_s = idle_s
        self.cut_after: str | None = None
        self.fed = 0  # sentences it gave (cues included)
        self.task: asyncio.Task | None = None

    def owns(self) -> bool:
        return self.task is not None and not self.task.done()

    def cut(self, message_id: str) -> bool:
        """her 💗 on the reply she's hearing: nothing after it is read (nor asked of the voice, nor played: the
        stream ends where that reply ends, even when the voice had already gone ahead)"""
        ids = [s.message_id for s in self.segments]
        if message_id not in ids:
            return False
        self.cut_after = message_id
        self.parts.keep = set(ids[: ids.index(message_id) + 1])
        return True

    def _feed(self, seg: Segment, fresh: list[dict], done: bool, source: str | None) -> None:
        first = len(self.parts)
        took = self.parts.feed(fresh, done=done)
        if self.take is not None and took:
            self.take(self.trace, first, fresh[:took])
        if self.trace is not None and source is not None:
            self.trace.meta["source"] = source[:40000]
        self.fed += took

    async def _look(self, seg: Segment, last_db: list[float]) -> tuple[str, bool, int] | None:
        snap = snapshot(seg.message_id)
        if snap is not None:
            return snap
        if seg.text is not None and seg.finished:  # the page's copy of a reply that was already whole
            return seg.text, True, 0
        now = time.monotonic()
        if now - last_db[0] >= DB_EVERY_S:  # the saved chat, last (it reads the whole chat's messages)
            last_db[0] = now
            return await saved_snapshot(seg.chat_id, seg.message_id)
        return None

    async def _segment(self, seg: Segment, last: bool) -> bool:
        """→ False when the stream is gone (cut short, she stopped it)"""
        given, quiet_since, last_db, pulse = seg.given, time.monotonic(), [0.0], None
        base = 1 if seg.lead else 0  # her cue is place 0 of its reply
        while True:
            if self.parts.done:
                return False
            snap = await self._look(seg, last_db)
            if snap is None or (not snap[1] and snap[2] == pulse):
                if time.monotonic() - quiet_since > self.idle_s:  # no source, or a reply that stopped moving
                    log.info("🧵 petal follow: %s went quiet for good, she finishes here", seg.message_id[:8])
                    return True
                await asyncio.sleep(POLL_S)
                if snap is None:
                    continue
            else:
                quiet_since = time.monotonic()
                self.parts.fed_at = quiet_since  # the reply moves: the stream waits for it however long it thinks
            text, finished, pulse = snap
            if seg.whole and not finished:
                await asyncio.sleep(POLL_S)
                continue
            ready = words.whole(text, finished)
            fresh = [{"text": p["text"], "para_end": p["para_end"], "mid": seg.message_id, "ix": base + given + k}
                     for k, p in enumerate(ready[given:])]
            if seg.lead and not seg.lead_given and (fresh or finished or text.strip()):
                fresh = [{"text": seg.lead, "para_end": True, "mid": seg.message_id, "ix": 0}] + fresh
                seg.lead_given = True
            if fresh:
                given = max(given, len(ready))
                self._feed(seg, fresh, False, text)
            if finished:
                return True
            await asyncio.sleep(POLL_S)

    async def run(self) -> None:
        try:
            for i, seg in enumerate(self.segments):
                alive = await self._segment(seg, i == len(self.segments) - 1)
                if not alive:
                    return
                if self.cut_after == seg.message_id:
                    break
            self.parts.feed([], done=True)  # all of it is in the stream: she finishes, then the stream ends
        except asyncio.CancelledError:
            raise
        except Exception as e:  # never costs her the stream: she says what she has, then ends
            log.warning("🧵 petal follow broke (%s): she finishes what she has", e.__class__.__name__)
            self.parts.feed([], done=True)

    def start(self) -> "Follower":
        self.task = asyncio.create_task(self.run())
        return self

    def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
