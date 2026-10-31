"""
🌸📻 petal stream — Petal's voice as one live stream, so she keeps speaking with the screen off
──────────────────────────────────────────────────────────────────────────────────────────────
OWUI speaks one clip per sentence. between two clips the phone sees a page playing nothing,
freezes it, and the next sentence never starts. here she becomes a little radio station:

  POST /api/v1/audio/petal-stream        {voice, parts: [{text, para_end}]}  → {id}
  GET  /api/v1/audio/petal-stream/{id}   one continuous audio/mpeg stream, played by one <audio>

behind the GET, each sentence is asked of the omni voice (vLLM-Omni, streaming pcm) while the
previous one is still playing, and each take is a fresh generation, so she varies per sentence.

pacing "tight" (the default): her takes go out back to back, exactly as she made them, the way
OWUI's sentence clips always played. her own silences are part of the piece; nothing is faded,
trimmed or padded between them. pacing "shaped" adds the punctuation pauses and tail fades from
the cadence file (parked for a later session, when the pacing gets its own care).

if the voice is ever late *between* two sentences, a little quiet holds the line so the phone
never decides she stopped. inside a sentence nothing is ever inserted: the player just waits.

the id is a one-time capability (128 random bits, minted for a signed-in user, valid 2 min,
spent on the first GET) — so the <audio> element can open it without headers or cookies.

cadence knobs: ~/Gardens/Documents/Petal-App-Data/petal-voice/stream-cadence.json, written with
defaults on first use and read on every stream (edit → next reply already speaks with it).

taste it without OWUI:  ~/.venvs/openwebui/bin/python petal_stream.py "a line. another one…"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

try:
    import lameenc  # tiny LAME wheel: pcm → mp3 frames, no ffmpeg pipes
except ImportError:  # honest seam: the stream says it can't, the client falls back to sentence clips
    lameenc = None

BOUNDARY = object()  # between two sentences: the only place quiet may ever be added
RATE = 24000  # the omni voice speaks 24 kHz mono int16; anything else is resampled to this
OMNI_URL = os.environ.get("PETAL_STREAM_TTS_URL", "http://127.0.0.1:8100/v1").rstrip("/")
OMNI_MODEL = os.environ.get("PETAL_STREAM_TTS_MODEL", "petal")
APP = Path(os.environ.get("PETAL_APP_DATA", Path.home() / "Gardens/Documents/Petal-App-Data")).expanduser()
CADENCE_PATH = APP / "petal-voice" / "stream-cadence.json"

TICKET_TTL_S = 120
MAX_PARTS = 600
MAX_CHARS = 40000

DEFAULT_CADENCE = {
    "_comment": "petal stream cadence, read on every reply (no restart). ms everywhere. "
    "pacing: tight = her takes back to back, untouched (like OWUI's sentence clips); "
    "shaped = the gaps and fades below are applied. "
    "gaps are real quiet inside her stream, chosen by how a sentence ends; "
    "paragraph wins when a sentence closes a paragraph. tail_fade softens each sentence's last "
    "moment so it lands instead of snapping; set it to 0 if it ever eats a syllable.",
    "pacing": "tight",
    "gap_period_ms": 260,
    "gap_question_ms": 320,
    "gap_exclaim_ms": 300,
    "gap_ellipsis_ms": 560,
    "gap_colon_ms": 300,
    "gap_plain_ms": 220,
    "gap_paragraph_ms": 680,
    "tail_ms": 360,
    "tail_fade_ms": 30,
    "head_fade_ms": 6,
    "lead_in_ms": 180,
    "underrun_guard_ms": 160,
    "bitrate_kbps": 96,
}


def cadence() -> dict:
    """her knobs, merged over the defaults. a broken file never stops her voice."""
    try:
        if not CADENCE_PATH.exists():
            CADENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CADENCE_PATH.write_text(json.dumps(DEFAULT_CADENCE, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return dict(DEFAULT_CADENCE)
        raw = json.loads(CADENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("petal stream: cadence file unreadable (%s), using defaults", e)
        return dict(DEFAULT_CADENCE)
    out = dict(DEFAULT_CADENCE)
    for k, v in raw.items():
        if k in ("_comment", "pacing"):
            continue
        if k in DEFAULT_CADENCE and isinstance(v, (int, float)) and v >= 0:
            out[k] = v
    if raw.get("pacing") in ("tight", "shaped"):
        out["pacing"] = raw["pacing"]
    elif "pacing" not in raw:  # a file from before pacing existed: show her the knob, keep her numbers
        try:
            raw["pacing"] = "tight"
            CADENCE_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass
    return out


# ── cadence: how a sentence ends decides the quiet after it ──────────────────
_TRAILING = " \t\n\"'”’»)]*_~`"


def gap_ms(text: str, para_end: bool, last: bool, c: dict) -> float:
    if last:
        return c["tail_ms"]
    end = text.rstrip(_TRAILING)
    if end.endswith(("…", "...")):
        g = c["gap_ellipsis_ms"]
    elif end.endswith(("?", "？")):
        g = c["gap_question_ms"]
    elif end.endswith(("!", "！")):
        g = c["gap_exclaim_ms"]
    elif end.endswith((".", "。")):
        g = c["gap_period_ms"]
    elif end.endswith((":", ";")):
        g = c["gap_colon_ms"]
    else:  # an emoji, a tilde, no punctuation at all
        g = c["gap_plain_ms"]
    return max(g, c["gap_paragraph_ms"]) if para_end else g


def silence(ms: float) -> bytes:
    return bytes(2 * int(RATE * ms / 1000))


def to_rate(pcm: np.ndarray, rate: int) -> np.ndarray:
    if rate == RATE or not len(pcm):
        return pcm
    n = max(1, int(round(len(pcm) * RATE / rate)))
    x = np.linspace(0, len(pcm) - 1, n)
    return np.interp(x, np.arange(len(pcm)), pcm.astype(np.float32)).astype(np.int16)


def fade(pcm: np.ndarray, n: int, out: bool) -> np.ndarray:
    n = min(n, len(pcm))
    if n <= 0:
        return pcm
    ramp = np.linspace(1.0, 0.0, n, dtype=np.float32) if out else np.linspace(0.0, 1.0, n, dtype=np.float32)
    pcm = pcm.copy()
    seg = slice(len(pcm) - n, len(pcm)) if out else slice(0, n)
    pcm[seg] = (pcm[seg].astype(np.float32) * ramp).astype(np.int16)
    return pcm


def _rate_of(headers) -> int:
    h = {k.lower(): v for k, v in headers.items()}
    if h.get("x-audio-sample-rate", "").strip().isdigit():
        return int(h["x-audio-sample-rate"])
    m = re.search(r"rate=(\d+)", h.get("content-type", ""))
    return int(m.group(1)) if m else RATE


# ── the voice: sentence after sentence, faded and spaced, into one queue ─────
async def produce(session, parts: list[dict], voice: str, q: asyncio.Queue, c: dict) -> None:
    """asks the omni voice for each sentence (streaming pcm) and puts 24 kHz int16 bytes on q.
    None on q means she's done."""
    import aiohttp

    shaped = c["pacing"] == "shaped"
    hold = 2 * int(RATE * c["tail_fade_ms"] / 1000) if shaped else 0  # bytes held back so the tail can be faded
    head_n = int(RATE * c["head_fade_ms"] / 1000) if shaped else 0
    timeout = aiohttp.ClientTimeout(total=180, sock_read=45)
    try:
        for i, part in enumerate(parts):
            text, last = part["text"], i == len(parts) - 1
            payload = {"model": OMNI_MODEL, "input": text, "voice": voice or OMNI_MODEL,
                       "response_format": "pcm", "stream": True, "stream_format": "audio"}
            spoke = False
            try:
                async with session.post(f"{OMNI_URL}/audio/speech", json=payload, timeout=timeout) as r:
                    if r.status != 200:
                        log.warning("petal stream: omni said %s for part %d", r.status, i)
                    else:
                        rate = _rate_of(r.headers)
                        pending, odd, first = bytearray(), b"", True
                        async for chunk in r.content.iter_any():
                            chunk = odd + chunk
                            odd = chunk[-1:] if len(chunk) % 2 else b""
                            chunk = chunk[: len(chunk) - len(odd)]
                            pcm = to_rate(np.frombuffer(chunk, dtype=np.int16), rate)
                            pending += pcm.tobytes()
                            if len(pending) > hold:
                                cut = len(pending) - hold
                                out = np.frombuffer(bytes(pending[:cut]), dtype=np.int16)
                                del pending[:cut]
                                if first:
                                    out, first = fade(out, head_n, out=False), False
                                await q.put(out.tobytes())
                                spoke = True
                        if pending:
                            tail = np.frombuffer(bytes(pending), dtype=np.int16)
                            if first:
                                tail = fade(tail, head_n, out=False)
                            if shaped:
                                tail = fade(tail, len(tail), out=True)
                            await q.put(tail.tobytes())
                            spoke = True
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.warning("petal stream: part %d lost (%s)", i, e.__class__.__name__)
            if shaped and (spoke or last):
                await q.put(silence(gap_ms(text, part.get("para_end", False), last, c)))
            await q.put(BOUNDARY)
    finally:
        await q.put(None)


# ── the station: one mp3 stream, never running dry ───────────────────────────
class Encoder:
    def __init__(self, kbps: int):
        e = lameenc.Encoder()
        e.set_bit_rate(int(kbps))
        e.set_in_sample_rate(RATE)
        e.set_channels(1)
        e.set_quality(2)
        self.e = e

    def encode(self, pcm: bytes) -> bytes:
        return bytes(self.e.encode(pcm)) if pcm else b""

    def flush(self) -> bytes:
        return bytes(self.e.flush())


async def station(session, parts: list[dict], voice: str):
    """yields mp3 bytes. keeps a clock of how much audio the listener already has; when the voice
    is late *between* sentences and that cushion runs low, a little quiet goes out so the player
    never starves. inside a sentence it only ever waits."""
    c = cadence()
    enc = Encoder(c["bitrate_kbps"])
    q: asyncio.Queue = asyncio.Queue()
    voice_task = asyncio.create_task(produce(session, parts, voice, q, c))
    guard = c["underrun_guard_ms"] / 1000
    try:
        lead = silence(c["lead_in_ms"])
        sent = len(lead) / (2 * RATE)
        t0 = time.monotonic()
        out = enc.encode(lead)
        if out:
            yield out
        between = True  # at the start, and after each sentence
        while True:
            filler = False
            if not q.empty():
                pcm = q.get_nowait()  # she's already here: never let a timer win over her
            elif between:
                wait = sent - (time.monotonic() - t0) - guard
                try:
                    if wait <= 0:
                        raise asyncio.TimeoutError
                    pcm = await asyncio.wait_for(q.get(), timeout=wait)
                except asyncio.TimeoutError:
                    pcm, filler = silence(100), True  # the next sentence is late: hold the line with quiet
            else:
                pcm = await q.get()  # mid-sentence: never insert anything, just wait for her
            if pcm is None:
                break
            if pcm is BOUNDARY:
                between = True
                continue
            if not filler:
                between = False
            sent += len(pcm) / (2 * RATE)
            out = enc.encode(pcm)
            if out:
                yield out
        out = enc.flush()
        if out:
            yield out
    finally:
        voice_task.cancel()
        try:
            await voice_task
        except (asyncio.CancelledError, Exception):
            pass


def clean_parts(raw) -> list[dict]:
    parts, total = [], 0
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, str):
            p = {"text": p}
        if not isinstance(p, dict) or not isinstance(p.get("text"), str):
            continue
        text = p["text"].strip()
        if not text:
            continue
        total += len(text)
        if total > MAX_CHARS or len(parts) >= MAX_PARTS:
            break
        parts.append({"text": text, "para_end": bool(p.get("para_end"))})
    return parts


# ── OWUI routes ───────────────────────────────────────────────────────────────
if __name__ != "__main__":
    from fastapi import APIRouter, Depends, HTTPException, Request
    from fastapi.responses import StreamingResponse

    from open_webui.utils.auth import get_verified_user
    from open_webui.utils.session_pool import get_session

    router = APIRouter()
    _tickets: dict[str, dict] = {}

    def _sweep() -> None:
        now = time.monotonic()
        for k in [k for k, v in _tickets.items() if now - v["t"] > TICKET_TTL_S]:
            _tickets.pop(k, None)

    @router.get("/petal-stream/health")
    async def petal_stream_health():
        return {"ok": lameenc is not None, "encoder": "lameenc" if lameenc else None,
                "voice": OMNI_URL, "cadence": str(CADENCE_PATH)}

    @router.post("/petal-stream")
    async def petal_stream_open(request: Request, user=Depends(get_verified_user)):
        if lameenc is None:
            raise HTTPException(503, "petal stream needs lameenc in the OWUI venv (pip install lameenc)")
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "invalid body") from None
        parts = clean_parts(body.get("parts"))
        if not parts:
            raise HTTPException(400, "nothing to speak")
        voice = body.get("voice") if isinstance(body.get("voice"), str) else OMNI_MODEL
        _sweep()
        ticket = secrets.token_urlsafe(16)
        _tickets[ticket] = {"t": time.monotonic(), "user": user.id, "parts": parts, "voice": voice[:128]}
        return {"id": ticket}

    @router.get("/petal-stream/{ticket}")
    async def petal_stream_play(ticket: str):
        _sweep()
        entry = _tickets.pop(ticket, None)  # spent on first use
        if not entry:
            raise HTTPException(404, "this stream is gone")
        session = await get_session()
        return StreamingResponse(
            station(session, entry["parts"], entry["voice"]),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-store", "Accept-Ranges": "none", "X-Accel-Buffering": "no"},
        )


# ── taste by hand: the same station, written to a file ───────────────────────
async def _taste(text: str, voice: str) -> Path:
    import aiohttp

    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts = []
    for para in paras:
        sents = [s for s in re.split(r"(?<=[.!?…])\s+", para.strip()) if s.strip()]
        parts += [{"text": s, "para_end": j == len(sents) - 1} for j, s in enumerate(sents)]
    out_dir = APP / "petal-voice" / "stream-tastes"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"taste-{time.strftime('%Y-%m-%d-%Hh%M%S')}.mp3"
    t0 = time.monotonic()
    first = None
    async with aiohttp.ClientSession() as session:
        with open(path, "wb") as f:
            async for b in station(session, clean_parts(parts), voice):
                if first is None:
                    first = time.monotonic() - t0
                f.write(b)
    print(f"🌸 {len(parts)} sentences · first sound after {first or 0:.2f}s · whole in {time.monotonic() - t0:.1f}s")
    print(f"📻 {path}")
    return path


if __name__ == "__main__":
    import sys

    if lameenc is None:
        sys.exit("✗ lameenc isn't installed in this python — pip install lameenc")
    line = " ".join(sys.argv[1:]) or (
        "hii princess, this is your petal stream. every sentence flows into the next without a single cut.\n\n"
        "a new paragraph waits a little longer… and a question? lands softer. you can lock your phone now~"
    )
    asyncio.run(_taste(line, OMNI_MODEL))
