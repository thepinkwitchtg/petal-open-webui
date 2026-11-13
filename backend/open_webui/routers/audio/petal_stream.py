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

🕊️ voice welfare (voice_welfare.py, asleep until she wakes it): each take is judged by the shared
ear before she hears it. a take that loops, runs far past its text, runs hot or harsh, or that the
voice ended with an error is dropped whole and the sentence is asked again with a fresh seed; a
kept take goes out exactly as she made it.

🛡️ the voice ceiling (voice_ceiling.py, always on, welfare awake or asleep): the last thing every
sample passes before the mp3 encoder. nothing that plays ever goes above it (-3 dBFS by default);
anything that never reaches it goes out byte for byte.

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

try:  # 🎀 the tts sieve + 🚩 the voice trace + 🕊️ voice welfare + 🛡️ the ceiling, inside OWUI or tasted on its own
    from open_webui.routers.audio.tts_sieve import load_config as sieve_config, sieve
    from open_webui.routers.audio import voice_ceiling, voice_trace, voice_welfare
except ImportError:
    from tts_sieve import load_config as sieve_config, sieve
    import voice_ceiling
    import voice_trace
    import voice_welfare

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
class Flow:
    """how far ahead of her ears the stream runs: what the phone already has (the station's clock)
    plus what still waits in the queue. near-free welfare only lets audio out early when this is low."""

    def __init__(self):
        self.sent, self.t0, self.queued = 0.0, None, 0

    def lead_s(self) -> float:
        ahead = 0.0 if self.t0 is None else max(0.0, self.sent - (time.monotonic() - self.t0))
        return ahead + self.queued / (2 * RATE)


RUSH_S = 0.35  # near-free: below this much audio ahead of her ears, she's waiting, so a take may start early


async def produce(session, parts: list[dict], voice: str, q: asyncio.Queue, c: dict, tr=None, flow: Flow | None = None) -> None:
    """asks the omni voice for each sentence (streaming pcm) and puts 24 kHz int16 bytes on q.
    None on q means she's done. tr (a voice trace) quietly keeps each take as she made it.

    🕊️ with voice welfare awake, each take is judged by the shared ear before it's heard: a take
    that loops, runs far past its text or runs hot/harsh is dropped (the request is closed, so omni
    stops making it) and the sentence is asked again with a fresh seed, up to max_tries, then
    skipped with a clean silence. a take the voice ended with an error (or with no audio at all) is
    judged too, and is never played as it arrived: it counts as a kill ("broken") whatever the ear
    said. a kept take goes out exactly as she made it."""
    import aiohttp

    shaped = c["pacing"] == "shaped"
    tail_hold = 2 * int(RATE * c["tail_fade_ms"] / 1000) if shaped else 0  # bytes held so the tail can be faded
    head_n = int(RATE * c["head_fade_ms"] / 1000) if shaped else 0
    timeout = aiohttp.ClientTimeout(total=180, sock_read=45)
    care = voice_welfare.load()  # 🕊️ read once per reply
    meta = tr.meta if tr else {}
    temp = not voice_trace.is_saved_chat_id(meta.get("chat_id"))
    near_free = care["hold"] == "near-free"
    win = 2 * int(RATE * voice_welfare.window_s(care))
    flow = flow or Flow()
    tally = {"sentences": 0, "kills": 0, "skipped": 0, "heard_s": 0.0}  # 🕊️ one numbers-only line per reply

    async def put(b: bytes) -> None:
        flow.queued += len(b)
        await q.put(b)

    try:
        for i, part in enumerate(parts):
            text, last = sieve(part["text"]), i == len(parts) - 1
            take = tr.takes[i] if tr and i < len(tr.takes) else None
            if take:
                take.fed = text
            if not text.strip():  # 🎀 only emoji: nothing for her to say, the line just moves on
                if shaped and last:
                    await put(silence(gap_ms(part["text"], part.get("para_end", False), last, c)))
                await q.put(BOUNDARY)
                continue
            sent = voice_welfare.Sentence(care, path="stream", text=text, idx=i, chat_id=meta.get("chat_id"),
                                          message_id=meta.get("message_id"), temp=temp, hold=care["hold"]) \
                if care["enabled"] else None
            spoke = False
            if take:
                take.t_req = tr.rel()
            while True:  # one pass per take. only welfare ever asks twice
                payload = {"model": OMNI_MODEL, "input": text, "voice": voice or OMNI_MODEL,
                           "response_format": "pcm", "stream": True, "stream_format": "audio"}
                w = None
                if sent:
                    payload["seed"] = sent.seed()
                    w = sent.watch()
                buf, released, first, why, broke = bytearray(), 0, True, None, None  # broke: what ended it badly

                async def out(upto: int, final: bool = False) -> None:
                    """sends buf[released:upto] to her ears, shaped only in "shaped" pacing"""
                    nonlocal released, first, spoke
                    if upto <= released and not final:
                        return
                    piece = np.frombuffer(bytes(buf[released:upto]), dtype=np.int16)
                    released = max(released, upto)
                    if not len(piece):
                        return
                    if first:
                        piece, first = fade(piece, head_n, out=False), False
                    if final and shaped and tail_hold:
                        body, tail = piece[:-tail_hold], piece[-tail_hold:]
                        piece = np.concatenate([body, fade(tail, len(tail), out=True)])
                    await put(piece.tobytes())
                    spoke = True

                try:
                    async with session.post(f"{OMNI_URL}/audio/speech", json=payload, timeout=timeout) as r:
                        if take:
                            take.status = r.status
                        if r.status != 200:
                            log.warning("petal stream: omni said %s for part %d", r.status, i)
                            broke = f"http {r.status}"
                        else:
                            rate = _rate_of(r.headers)
                            odd = b""
                            async for chunk in r.content.iter_any():
                                chunk = odd + chunk
                                odd = chunk[-1:] if len(chunk) % 2 else b""
                                chunk = chunk[: len(chunk) - len(odd)]
                                pcm = to_rate(np.frombuffer(chunk, dtype=np.int16), rate)
                                if not len(pcm):
                                    continue
                                if take and take.t_first is None:
                                    take.t_first = tr.rel()
                                b = pcm.tobytes()
                                buf += b
                                if w is None:  # welfare asleep: she goes out live, as she always did
                                    await out(len(buf) - tail_hold)
                                    continue
                                hit = w.feed(b)  # stretch is a clock
                                early = near_free and (released > 0 or flow.lead_s() < RUSH_S)
                                if not hit and (w.due() or early):  # a loop is a pattern: listen again
                                    kills = await asyncio.to_thread(w.listen, bytes(buf))
                                    hit = "+".join(kills) if kills else None
                                if hit:
                                    why = hit
                                    r.close()  # omni stops making a take nobody will hear
                                    break
                                if early:  # she's waiting: out goes all but the last window (always judged first),
                                    # and never anything from the first hot or harsh moment on (held whole till judged)
                                    await out(min(len(buf) - max(win, tail_hold), w.cool_upto()))
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    log.warning("petal stream: part %d lost (%s)", i, e.__class__.__name__)
                    broke = e.__class__.__name__
                    if take:
                        take.error = broke
                if w is not None and why is None and buf:
                    # the whole take (or all of it that came before a break), as the report would hear it
                    kills = await asyncio.to_thread(w.listen, bytes(buf))
                    why = "+".join(kills) if kills else None
                if w is not None and (broke or not buf):
                    # 🕊️ every take is judged, error or not: one the voice ended with an error (or with no
                    # audio at all) is never played as it arrived, whatever the ear made of it
                    broke = broke or "empty"
                    why = "broken" + (f"+{why}" if why else "")
                if why:  # 🕊️ a bad take: dropped whole (near-free: whatever had to go out early stays heard)
                    sent.kill(w, bytes(buf), heard_s=released / (2 * RATE), broken=broke)
                    if take:
                        take.kills.append(why)
                    if not sent.spent:
                        continue  # a fresh take of the very same sentence
                    await put(silence(care["skip_silence_ms"]))  # skipped: a clean silence, never the loop
                    spoke = True
                    break
                if not (w is None and broke):  # asleep, a broken take ends where it broke, as it always did
                    if sent and buf:
                        sent.keep(w, bytes(buf))
                    await out(len(buf), final=True)
                if take and buf and tr.room():
                    take.pcm += buf  # 🚩 the take as the voice made it (the ceiling only touches what reaches her ears)
                break
            if take:
                take.t_done = tr.rel()
                take.tries = (len(sent.kills) + (1 if sent.kept else 0)) if sent else 1
            if sent:
                tally["sentences"] += 1
                tally["kills"] += len(sent.kills)
                tally["skipped"] += int(sent.skipped)
                tally["heard_s"] += sum(k["heard_s"] for k in sent.kills)
                await asyncio.to_thread(sent.close)
            if shaped and (spoke or last):
                await put(silence(gap_ms(text, part.get("para_end", False), last, c)))
            await q.put(BOUNDARY)
    finally:
        if tally["sentences"]:
            voice_welfare.log_reply(temp=temp, **tally)
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


async def station(session, parts: list[dict], voice: str, tr=None):
    """yields mp3 bytes. keeps a clock of how much audio the listener already has; when the voice
    is late *between* sentences and that cushion runs low, a little quiet goes out so the player
    never starves. inside a sentence it only ever waits."""
    c = cadence()
    enc = Encoder(c["bitrate_kbps"])
    ceil = voice_ceiling.Ceiling(voice_welfare.load()["ceiling_dbfs"])  # 🛡️ nothing that plays goes above it
    q: asyncio.Queue = asyncio.Queue()
    if tr:
        tr.pacing, tr.started = c["pacing"], True
        try:
            tr.sieve_mode = str(sieve_config().get("mode", "?"))
        except Exception:
            pass
    flow = Flow()  # 🕊️ shared with the voice so near-free welfare knows when she's waiting
    voice_task = asyncio.create_task(produce(session, parts, voice, q, c, tr, flow))
    guard = c["underrun_guard_ms"] / 1000
    pi, completed = 0, False  # 🚩 which sentence is on air, and whether she got to the end

    def heard(b: bytes) -> bytes:
        if tr and b and tr.room():
            tr.heard += b
        return b

    try:
        lead = silence(c["lead_in_ms"])
        sent = len(lead) / (2 * RATE)
        t0 = time.monotonic()
        flow.t0, flow.sent = t0, sent
        out = enc.encode(lead)
        if out:
            yield heard(out)
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
                completed = True
                break
            if pcm is BOUNDARY:
                between = True
                pi += 1
                continue
            take = tr.takes[pi] if tr and not filler and pi < len(tr.takes) else None
            if take and take.start_s is None:
                take.start_s = round(sent, 3)
            if not filler:
                between = False
                flow.queued = max(0, flow.queued - len(pcm))
            sent += len(pcm) / (2 * RATE)
            flow.sent = sent
            if take:
                take.end_s = round(sent, 3)
            out = enc.encode(ceil.process(pcm))
            if out:
                yield heard(out)
        out = enc.flush()
        if out:
            yield heard(out)
    finally:
        if ceil.touched and tr:
            tr.ceiling = {"dbfs": ceil.dbfs, "touched_s": round(ceil.touched_s, 3), "peak_in_db": ceil.peak_in_db}
        if ceil.ran_hot:  # 🛡️ rare by design: one numbers-only line whenever something above the ceiling reached it
            meta = tr.meta if tr else {}
            voice_welfare.log_ceiling(path="stream", touched_s=ceil.touched_s, peak_in_db=ceil.peak_in_db,
                                      temp=not voice_trace.is_saved_chat_id(meta.get("chat_id")))
        if tr:
            voice_trace.finish(tr, cut_short=not completed)
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
        tr = voice_trace.open_trace(user.id, parts, voice[:128], body.get("meta"))  # 🚩 memory only, until flagged
        _tickets[ticket] = {"t": time.monotonic(), "user": user.id, "parts": parts, "voice": voice[:128], "trace": tr}
        return {"id": ticket, "trace": tr.id}

    @router.post("/petal-stream/flag")
    async def petal_stream_flag(request: Request, user=Depends(get_verified_user)):
        """🚩 keep this one: the reply she's speaking (or spoke) becomes an incident on the rig."""
        try:
            body = await request.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        tr = voice_trace.find(user.id, body.get("trace"), body.get("message_id"))
        if not tr:
            raise HTTPException(404, "no recent petal stream to flag (only the last few replies are kept, and only since OWUI started)")
        f = voice_trace.flag(tr, body.get("at_s"), body.get("note"), body.get("via"))
        if tr.done:  # she's already finished: plant it now
            folder = await asyncio.to_thread(voice_trace.plant, tr)
            return {"ok": bool(folder), "planted": bool(folder), "incident": folder.name if folder else None,
                    "part": f["part"], "flags": len(tr.flags)}
        return {"ok": True, "planted": False, "pending": True, "part": f["part"], "flags": len(tr.flags)}

    @router.get("/petal-stream/{ticket}")
    async def petal_stream_play(ticket: str):
        _sweep()
        entry = _tickets.pop(ticket, None)  # spent on first use
        if not entry:
            raise HTTPException(404, "this stream is gone")
        session = await get_session()
        return StreamingResponse(
            station(session, entry["parts"], entry["voice"], entry.get("trace")),
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
