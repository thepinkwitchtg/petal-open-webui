"""
🎀📡 voice events — the page knows what she's saying, sentence by sentence
──────────────────────────────────────────────────────────────────────────
petal stream turns a whole reply into one mp3, played by one <audio>. so the page can follow her
(light the sentence she's saying, the quote she's speaking), every stream gets a little channel
beside it, and a speaker clip carries the same events in a header.

the stream:  GET /api/v1/audio/petal-stream/{id}/events      text/event-stream
             same id as the audio, signed in like the rest of OWUI (an EventSource sends the cookie;
             a fetch can send the Bearer header). every event has an id, so a reconnect replays what
             it missed (Last-Event-ID, or ?after=N). once she's done and you have it all, the answer
             is 204, so an EventSource stops asking.

  event     data (JSON)                                          when
  sentence  {type, seq, message_id, idx, text, start, duration}   as soon as the station knows where the
                                                                  sentence sits in the stream: welfare
                                                                  airtight, the moment its first sample goes
                                                                  out; otherwise once its take is complete
                                                                  (still ahead of her ears: the voice runs
                                                                  ~11× faster than she speaks)
  end       {type, seq, message_id, at}                           all of her is in the stream, its audio
                                                                  ends at `at`
  stop      {type, seq, message_id, at, reason}                   the stream was cut short at `at`
                                                                  (reason: gone · broken · unplayed)

  start · duration · at are seconds on the player's own clock (audio.currentTime, the mp3's 46 ms
  delay included), so the page lights a sentence while start ≤ currentTime < start + duration: right
  through pauses, buffering and any playback rate. idx is the part's place in the parts the page sent
  (a part with nothing to say, or one welfare skipped, sends no sentence). text is that part exactly
  as the page sent it, before the TTS sieve, so the page finds it in the reply, quotes included. one
  idx can start twice only in near-free welfare (a take let out early, then killed): the later start
  wins from its start.

  pause · resume, and the moment playback truly ends or stops, only the page can know: it makes them
  from its own <audio> (pause · play · ended · its stop), in the same shape.

the speaker path (/audio/speech, one quote spoken alone): add "petal": {"message_id", "idx"} to the
body and the clip answers with the same events in an X-Petal-Voice header: url-encoded JSON
{"v": 1, "events": [sentence (start 0), end]}. "petal" never reaches the voice, nor the cache key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

if __package__:  # inside OWUI
    from open_webui.routers.audio import voice_welfare
else:  # on its own, beside its siblings
    import voice_welfare

log = logging.getLogger(__name__)

RATE = 24000
MP3_DELAY_S = 1105 / RATE  # lame's encoder delay + the decoder's: the player hears sample 0 this late
KEEP_S = 1800  # a finished stream's channel stays this long (a page that reconnects catches up)
UNPLAYED_S = 120  # the audio ticket's own life: a stream never played closes its channel
MAX_CHANNELS = 32
HEADER = "X-Petal-Voice"
TEXT_MAX = 2000  # in a header the text is a convenience (the page sent it): a very long one is cut


# ── on petal stream's queue, beside her audio ────────────────────────────────
@dataclass
class Saying:
    """right before a take's first sample: what's about to be heard"""

    idx: int
    text: str
    seconds: float | None  # known when the whole take goes out at once (welfare airtight)


@dataclass
class Said:
    """right after the last sample of a take that was heard"""

    idx: int
    seconds: float


def clock(sent_s: float) -> float:
    """a stream position (seconds of pcm the station has sent) → the player's audio.currentTime"""
    return round(sent_s + MP3_DELAY_S, 3)


# ── one stream's channel ──────────────────────────────────────────────────────
class Channel:
    def __init__(self, cid: str, user: str, message_id: str | None):
        self.id, self.user, self.message_id = cid, user, message_id
        self.events: list[dict] = []
        self.started = self.closed = False
        self.t = time.monotonic()  # opened, then closed
        self._wake: asyncio.Event | None = None

    def publish(self, kind: str, **data) -> dict | None:
        if self.closed:
            return None
        ev = {"type": kind, "seq": len(self.events) + 1, "message_id": self.message_id, **data}
        self.events.append(ev)
        self._poke()
        return ev

    def close(self) -> None:
        if not self.closed:
            self.closed, self.t = True, time.monotonic()
            self._poke()

    def _poke(self) -> None:
        if self._wake is not None:
            self._wake.set()
            self._wake = None

    async def wait(self, timeout: float) -> bool:
        """→ True when something new came (or it closed), False after a quiet timeout"""
        if self._wake is None:
            self._wake = asyncio.Event()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False


_channels: dict[str, Channel] = {}


def sweep() -> None:
    now = time.monotonic()
    for cid, ch in list(_channels.items()):
        if not ch.started and not ch.closed and now - ch.t > UNPLAYED_S:
            ch.publish("stop", at=0.0, reason="unplayed")
            ch.close()
        if ch.closed and now - ch.t > KEEP_S:
            _channels.pop(cid, None)
    over = len(_channels) - MAX_CHANNELS
    if over > 0:  # the oldest finished ones go first
        for cid, _ in sorted(((k, v) for k, v in _channels.items() if v.closed), key=lambda kv: kv[1].t)[:over]:
            _channels.pop(cid, None)


def open_channel(cid: str, user: str, message_id) -> Channel:
    ch = Channel(cid, user, message_id if isinstance(message_id, str) else None)
    _channels[cid] = ch
    sweep()  # after: the cap counts the new one (only finished channels are ever let go)
    return ch


def channel(cid: str) -> Channel | None:
    sweep()
    return _channels.get(cid)


def after_of(last_event_id: str | None, after: str | None) -> int:
    """where a (re)connecting page stands: Last-Event-ID (EventSource) or ?after=N (fetch)"""
    for v in (last_event_id, after):
        if v and str(v).strip().isdigit():
            return int(str(v).strip())
    return 0


async def sse(ch: Channel, after: int = 0, heartbeat_s: float = 15.0):
    """text/event-stream: everything after `after`, then each new event as it comes, until she's done"""
    yield "retry: 3000\n\n"
    while True:
        while after < len(ch.events):
            ev = ch.events[after]
            after += 1
            yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        if ch.closed:
            return
        if not await ch.wait(heartbeat_s):
            sweep()  # a stream that was never played closes its own line once its ticket is gone
            if ch.closed:
                continue
            yield ": 💗\n\n"  # a comment line: keeps proxies and phones from calling the line dead


# ── the speaker path: one clip, the same events in a header ─────────────────
def take_petal(body: bytes) -> tuple[bytes, dict | None]:
    """/audio/speech: lifts "petal": {"message_id", "idx"} out of the body, so it never reaches the
    voice nor the cache key → (body, ask). an untouched body comes back byte for byte"""
    try:
        payload = json.loads(body)
    except (ValueError, TypeError, UnicodeDecodeError):
        return body, None
    if not isinstance(payload, dict) or "petal" not in payload:
        return body, None
    p = payload.pop("petal")
    p = p if isinstance(p, dict) else {}
    idx = p.get("idx")
    ask = {"message_id": p.get("message_id") if isinstance(p.get("message_id"), str) else None,
           "idx": idx if isinstance(idx, int) and not isinstance(idx, bool) else 0,
           "text": payload.get("input") if isinstance(payload.get("input"), str) else ""}
    # written the way a browser writes it, so the same words share one cached take with or without "petal"
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), ask


def clip_events(ask: dict, seconds: float | None, said: bool = True) -> str:
    """X-Petal-Voice's value: the stream's events for one clip, url-encoded JSON"""
    d = round(seconds or 0.0, 3)
    evs = []
    if said and seconds:
        ev = {"type": "sentence", "seq": 1, "message_id": ask.get("message_id"), "idx": ask.get("idx", 0),
              "text": (ask.get("text") or "")[:TEXT_MAX], "start": 0.0, "duration": d}
        if len(ask.get("text") or "") > TEXT_MAX:
            ev["cut"] = True
        evs.append(ev)
    evs.append({"type": "end", "seq": len(evs) + 1, "message_id": ask.get("message_id"), "at": d})
    return quote(json.dumps({"v": 1, "events": evs}, ensure_ascii=False, separators=(",", ":")), safe="")


def clip_seconds(data: bytes, content_type: str | None) -> float | None:
    pcm = voice_welfare.decode_clip(data, content_type or "audio/mpeg") if data else None
    return round(len(pcm) / (2 * RATE), 3) if pcm else None


def file_seconds(path) -> float | None:
    """a cached clip's length, heard once and kept beside it (.dur)"""
    path = Path(path)
    dur = path.with_suffix(".dur")
    try:
        return float(dur.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    mime = path.with_suffix(".mime")
    try:
        ct = mime.read_text(encoding="utf-8").strip() if mime.exists() else \
            ("audio/wav" if path.suffix == ".wav" else "audio/mpeg")
        s = clip_seconds(path.read_bytes(), ct)
    except OSError:
        return None
    if s is not None:
        try:
            dur.write_text(f"{s}\n", encoding="utf-8")
        except OSError:
            pass
    return s


async def follow(response, ask: dict | None, said: bool = True):
    """the speaker path's answer, carrying the stream's events (only when the page asked for them)"""
    if not ask or response is None:
        return response
    try:
        headers = getattr(response, "headers", None)
        if headers is None:
            return response
        if headers.get("X-Petal-Welfare") == "skipped":
            said = False  # welfare spent every take: a clean silence, nothing was said
        path = getattr(response, "path", None)  # a FileResponse (a cached or fresh take)
        if path:
            secs = await asyncio.to_thread(file_seconds, path)
        else:
            body = getattr(response, "body", None)
            secs = await asyncio.to_thread(clip_seconds, body, getattr(response, "media_type", None)) if body else None
        headers[HEADER] = clip_events(ask, secs, said=said)
        headers["Access-Control-Expose-Headers"] = HEADER
    except Exception as e:  # noqa: BLE001 — a clip is never lost over its events
        log.debug("voice events: speaker clip sent without its events (%s)", e)
    return response
