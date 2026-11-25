"""
🚩🎀 voice trace · the station's notes, handed to the voice's black box (V1, nov 24 2026)
──────────────────────────────────────────────────────────────────────────────────────────
the black box lives at the voice now (petal-voice's gate, :8100): every utterance any app asks of
her is kept there, and any app can flag one. petal stream is a station on top of it, so it keeps
only what the voice can't see, in memory, for the last few replies: the stream exactly as it
reached your ears (heard), when each sentence sat on that timeline, the pacing, welfare's kills and
the ceiling.

a flag (the 🚩 on a message, or your earbuds' "next track" while she speaks) goes to the voice:

  POST <voice>/v1/petal/flag                {group: <this trace's id>, at_s, part, note, via, station}
  PUT  <voice>/v1/petal/groups/<id>/heard   what reached her ears, once the stream is over

and the voice plants the incident in Petal-App-Data/petal-voice/incidents/ (700 · 600).

🌙 while studio (qwen) wears the voice there is no gate in front of her yet (Lily decides whether
Siren's studio path shares the floor), so a flag the voice can't take is planted here, as before:
this station still keeps each take's pcm for that. that fallback retires the day studio joins.

the analysis and the numbers-only report are the voice's (voice_report.py, read by path), and they
hear with welfare's ear (voice_measure.py, beside this file):
  ./petal-voice-incidents.sh          (in petal-voice; the fork's helper points there)
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

if __package__:  # inside OWUI (open_webui.routers.audio)
    from open_webui.utils.chat_id import is_saved_chat_id
else:  # on its own: never wake OWUI's config

    def is_saved_chat_id(chat_id: str | None) -> bool:  # same rule as open_webui.utils.chat_id
        return bool(chat_id) and not chat_id.startswith(("temporary:", "local:", "channel:"))

log = logging.getLogger(__name__)

RATE = 24000
APP = Path(os.environ.get("PETAL_APP_DATA", Path.home() / "Gardens/Documents/Petal-App-Data")).expanduser()
INCIDENTS = APP / "petal-voice" / "incidents"
VOICE_URL = os.environ.get("PETAL_VOICE_BOX_URL") or re.sub(
    r"/v1/?$", "", os.environ.get("PETAL_STREAM_TTS_URL", "http://127.0.0.1:8100/v1").rstrip("/"))
DEFAULT_VOICE_DIR = "~/Gardens/Transformation Sequences - Automation/petal_core/petal-voice"
UA = "petal-open-webui/stream"

RING = 8  # replies kept in memory
MAX_REC_BYTES = 80 * 1024 * 1024  # per reply (takes + heard); past this she still speaks, we just stop recording
_lock = threading.Lock()


# ── what one reply leaves behind ──────────────────────────────────────────────
@dataclass
class Take:
    idx: int
    raw: str
    para_end: bool
    fed: str = ""  # what the voice actually ate (after the sieve)
    status: int | None = None
    error: str | None = None
    t_req: float | None = None  # monotonic, relative to the trace start
    t_first: float | None = None
    t_done: float | None = None
    start_s: float | None = None  # where it sits on the heard timeline
    end_s: float | None = None
    pcm: bytearray = field(default_factory=bytearray)  # 🌙 only for the studio fallback
    tries: int = 1  # 🕊️ takes asked of the voice for this sentence (welfare resamples a bad one)
    kills: list = field(default_factory=list)  # why each dropped take was dropped ("loop", "stretch"…)


@dataclass
class Trace:
    id: str
    user: str
    meta: dict
    voice: str
    takes: list[Take]
    wall: float = field(default_factory=time.time)
    t0: float = field(default_factory=time.monotonic)
    pacing: str = "tight"
    sieve_mode: str = "?"  # the mood this reply was spoken in
    heard: bytearray = field(default_factory=bytearray)
    started: bool = False
    done: bool = False
    cut_short: bool = False
    truncated: bool = False
    flags: list[dict] = field(default_factory=list)
    folder: Path | None = None
    ceiling: dict | None = None  # 🛡️ set when the voice ceiling had to turn this reply down
    at_voice: str | None = None  # the incident's name once the voice has planted it

    def rel(self) -> float:
        return round(time.monotonic() - self.t0, 3)

    def rec_bytes(self) -> int:
        return len(self.heard) + sum(len(t.pcm) for t in self.takes)

    def room(self) -> bool:
        if self.rec_bytes() < MAX_REC_BYTES:
            return True
        self.truncated = True
        return False

    def part_at(self, at_s: float | None) -> int | None:
        """the sentence that was playing at at_s (or the last one that started before it)"""
        if at_s is None:
            return None
        best = None
        for t in self.takes:
            if t.start_s is None:
                continue
            if t.start_s <= at_s:
                best = t.idx
            if t.end_s is not None and t.start_s <= at_s <= t.end_s:
                return t.idx
        return best

    def station(self) -> dict:
        """what only the station knows: the heard timeline, pacing, welfare, the ceiling"""
        return {"pacing": self.pacing, "cut_short": self.cut_short, "complete": self.done and not self.cut_short,
                "truncated": self.truncated, "ceiling": self.ceiling, "sieve_mood": self.sieve_mode,
                "heard_s": max((t.end_s or 0 for t in self.takes), default=0), "source": self.meta.get("source"),
                "takes": [{"idx": t.idx, "start_s": t.start_s, "end_s": t.end_s, "t_req": t.t_req,
                           "t_first": t.t_first, "t_done": t.t_done, "tries": t.tries, "welfare_kills": t.kills,
                           "status": t.status, "error": t.error} for t in self.takes]}

    def headers(self, idx: int, mood: str) -> dict:
        """what each sentence tells her voice's gate (mood + where it belongs in the black box)"""
        h = {"User-Agent": UA, "X-Petal-Mood": mood, "X-Petal-Group": self.id, "X-Petal-Idx": str(idx)}
        if idx < len(self.takes):
            h["X-Petal-Para-End"] = "1" if self.takes[idx].para_end else "0"
        for k, hk in (("chat_id", "X-Petal-Chat"), ("message_id", "X-Petal-Message"), ("model", "X-Petal-Model")):
            if self.meta.get(k):
                h[hk] = self.meta[k][:200]
        return h


_ring: OrderedDict[str, Trace] = OrderedDict()


def open_trace(user: str, parts: list[dict], voice: str, meta: dict | None) -> Trace:
    m = meta if isinstance(meta, dict) else {}
    clean = {k: str(m[k])[:40000 if k == "source" else 200] for k in ("chat_id", "message_id", "model", "source") if m.get(k)}
    tr = Trace(id="st-" + secrets.token_urlsafe(9), user=user, meta=clean, voice=voice,
               takes=[Take(idx=i, raw=p["text"], para_end=bool(p.get("para_end"))) for i, p in enumerate(parts)])
    with _lock:
        _ring[tr.id] = tr
        while len(_ring) > RING:
            _ring.popitem(last=False)
    return tr


def find(user: str, trace_id: str | None = None, message_id: str | None = None) -> Trace | None:
    with _lock:
        traces = [t for t in reversed(_ring.values()) if t.user == user]
    if trace_id:
        for t in traces:
            if t.id == trace_id:
                return t
    if message_id:
        for t in traces:
            if t.meta.get("message_id") == message_id:
                return t
        return None
    return traces[0] if traces else None


def flag(tr: Trace, at_s, note, via) -> dict:
    at = float(at_s) if isinstance(at_s, (int, float)) and at_s >= 0 else None
    f = {"wall": time.time(), "local": time.strftime("%Y-%m-%d %H:%M:%S"), "at_s": at,
         "part": tr.part_at(at), "via": str(via or "button")[:24],
         "note": str(note)[:2000] if note else None, "while_speaking": not tr.done}
    tr.flags.append(f)
    return f


# ── the voice's black box ────────────────────────────────────────────────────
def _voice(method: str, path: str, body: bytes | None = None, ctype: str = "application/json", timeout: float = 15):
    req = urllib.request.Request(f"{VOICE_URL}{path}", data=body, method=method,
                                 headers={"Content-Type": ctype, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError):
        return None, {}


def to_voice(tr: Trace, f: dict | None = None) -> dict | None:
    """a flag (and, once she's done, the station's notes + what she heard) → the voice's black box.
    → the voice's answer, or None when her box isn't there (studio, or the gate asleep)"""
    body = {"group": tr.id, "station": tr.station(), "wait": not tr.done}
    if f:
        body.update({"at_s": f["at_s"], "part": f["part"], "note": f["note"], "via": f["via"]})
        code, out = _voice("POST", "/v1/petal/flag", json.dumps(body, ensure_ascii=False).encode("utf-8"))
    else:
        code, out = _voice("POST", f"/v1/petal/groups/{tr.id}/station",
                           json.dumps(body["station"], ensure_ascii=False).encode("utf-8"))
    if code != 200:
        return None
    if tr.done and tr.heard:
        _voice("PUT", f"/v1/petal/groups/{tr.id}/heard", bytes(tr.heard), "audio/mpeg", timeout=60)
    if out.get("incident"):
        tr.at_voice = out["incident"]
    return out


def finish(tr: Trace, cut_short: bool) -> None:
    """the stream is over (ended, stopped, or the phone hung up). a flagged reply's notes go to the voice"""
    tr.done = True
    tr.cut_short = cut_short
    if tr.flags:
        threading.Thread(target=_settle, args=(tr,), daemon=True).start()


def _settle(tr: Trace) -> None:
    if to_voice(tr) is None:
        plant_here(tr)  # 🌙 no box at the voice (studio): kept here, as before


# ── 🌙 the studio fallback: planted here, exactly as the black box always did ─
def _write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def plant_here(tr: Trace) -> Path | None:
    # 🧪 contract 0: a flag is her choice, so it's honored in a temp chat too, but kept with no
    # chat/message link and "temp": true
    saved = is_saved_chat_id(tr.meta.get("chat_id"))
    try:
        with _lock:
            if tr.folder is None:
                msg = (re.sub(r"[^A-Za-z0-9]", "", tr.meta.get("message_id", ""))[:8] if saved else "") or tr.id[-8:]
                stamp = time.strftime("%Y-%m-%d_%Hh%Mm%S", time.localtime(tr.wall))
                tr.folder = INCIDENTS / f"{stamp}_{msg}"
            folder = tr.folder
        (folder / "takes").mkdir(parents=True, exist_ok=True)
        for d in (INCIDENTS, folder, folder / "takes"):
            os.chmod(d, 0o700)
        (folder / "heard.mp3").write_bytes(bytes(tr.heard))
        for t in tr.takes:
            if t.pcm:
                _write_wav(folder / "takes" / f"{t.idx:02d}.wav", bytes(t.pcm))
        st = tr.station()
        trace = {
            "trace": tr.id, "planted_by": "petal-open-webui (studio fallback)",
            "when": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(tr.wall)), "wall": tr.wall,
            "chat_id": tr.meta.get("chat_id") if saved else None,
            "message_id": tr.meta.get("message_id") if saved else None,
            "chat_url": f"/c/{tr.meta['chat_id']}" if saved else None, "temp": not saved,
            "caller": UA, "model": tr.meta.get("model"), "voice": tr.voice, "mode": "studio?",
            "pacing": tr.pacing, "sieve_mode": tr.sieve_mode,
            "complete": st["complete"], "cut_short": tr.cut_short, "truncated": tr.truncated,
            "heard_s": st["heard_s"], "heard": True, "flags": tr.flags, "ceiling": tr.ceiling,
            "takes": [{
                "idx": t.idx, "para_end": t.para_end, "raw": t.raw, "fed": t.fed, "mood": tr.sieve_mode,
                "silenced": not t.fed.strip(), "status": t.status, "error": t.error,
                "t_req": t.t_req, "t_first": t.t_first, "t_done": t.t_done,
                "start_s": t.start_s, "end_s": t.end_s, "audio_s": round(len(t.pcm) / (2 * RATE), 3),
                "wav": f"takes/{t.idx:02d}.wav" if t.pcm else None,
                "tries": t.tries, "welfare_kills": t.kills,
            } for t in tr.takes],
            "source": tr.meta.get("source") if saved else None,
        }
        for p in [folder / "heard.mp3", *(folder / "takes").glob("*.wav")]:
            os.chmod(p, 0o600)
        tp = folder / "trace.json"
        tp.write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.chmod(tp, 0o600)
        try:
            analyse_incident(folder)
        except Exception as e:
            log.info("voice trace: the analysis waits for the voice's report (%s)", e.__class__.__name__)
        log.info("🚩 voice incident planted here (studio fallback): %s", folder)
        return folder
    except Exception as e:  # a flag must never hurt her stream
        log.warning("voice trace: could not plant incident (%s)", e)
        return None


# ── the analysis + the report: the voice's, read by path ─────────────────────
_report = None


def voice_report():
    """petal-voice's voice_report.py ($PETAL_VOICE_REPORT, else in $PETAL_VOICE_DIR, else petal_core/petal-voice)"""
    global _report
    if _report is not None:
        return _report
    path = os.environ.get("PETAL_VOICE_REPORT")
    if not path:
        path = str(Path(os.environ.get("PETAL_VOICE_DIR") or DEFAULT_VOICE_DIR).expanduser() / "voice_report.py")
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"the voice's report isn't at {p} (set $PETAL_VOICE_DIR)")
    os.environ.setdefault("PETAL_OWUI_DIR", str(Path(__file__).resolve().parents[4]))  # its ear is the one beside us
    spec = importlib.util.spec_from_file_location("petal_voice_report", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["petal_voice_report"] = mod
    spec.loader.exec_module(mod)
    _report = mod
    return mod


def analyse_incident(folder: Path) -> dict | None:
    return voice_report().analyse_incident(folder)


def report() -> str:
    return voice_report().report()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "report":
        print(report())
    elif cmd == "last":
        print(voice_report().last())
    elif cmd == "analyse" and len(sys.argv) > 2:
        print(json.dumps(analyse_incident(Path(sys.argv[2]).expanduser()), indent=2, default=str))
    else:
        sys.exit("usage: voice_trace.py [report | last | analyse <incident folder>]")
