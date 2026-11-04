"""
🚩🎀 voice trace — a little black box for Petal's voice
───────────────────────────────────────────────────────
petal stream keeps the last few replies she spoke, in memory only: every sentence's own take
(exactly as the omni voice made it), the stream exactly as you heard it, and when each sentence
sat on the timeline. nothing touches the disk until you flag one.

a flag (the 🚩 on a message, or your earbuds' "next track" while she speaks) plants an incident:

  ~/Gardens/Documents/Petal-App-Data/petal-voice/incidents/<when>_<msg8>/
      heard.mp3        the stream exactly as it reached your ears
      takes/NN.wav     each sentence's own take, 24 kHz mono, untouched
      trace.json       private: chat id, message id, timestamps, the text she was given, flags
      analysis.json    numbers: loop runs, hiss floor, how long each take ran for its text

the incidents folder is private data (her words live in trace.json). what you share is the report:

  ./petal-voice-incidents.sh          re-analyse every incident + print the stats-only report
                                      (also written to incidents/report-<date>.md — numbers and
                                      categories only, never a sentence of hers)

can run on its own:  ~/.venvs/openwebui/bin/python voice_trace.py report
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
import wave
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

RATE = 24000
APP = Path(os.environ.get("PETAL_APP_DATA", Path.home() / "Gardens/Documents/Petal-App-Data")).expanduser()
INCIDENTS = APP / "petal-voice" / "incidents"

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
    pcm: bytearray = field(default_factory=bytearray)


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
    sieve_mode: str = "?"
    heard: bytearray = field(default_factory=bytearray)
    started: bool = False
    done: bool = False
    cut_short: bool = False
    truncated: bool = False
    flags: list[dict] = field(default_factory=list)
    folder: Path | None = None

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


_ring: OrderedDict[str, Trace] = OrderedDict()


def open_trace(user: str, parts: list[dict], voice: str, meta: dict | None) -> Trace:
    m = meta if isinstance(meta, dict) else {}
    clean = {k: str(m[k])[:40000 if k == "source" else 200] for k in ("chat_id", "message_id", "model", "source") if m.get(k)}
    tr = Trace(id=secrets.token_urlsafe(9), user=user, meta=clean, voice=voice,
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


def finish(tr: Trace, cut_short: bool) -> None:
    """the stream is over (ended, stopped, or the phone hung up). a flagged reply gets planted."""
    tr.done = True
    tr.cut_short = cut_short
    if tr.flags:
        threading.Thread(target=plant, args=(tr,), daemon=True).start()


# ── planting an incident ─────────────────────────────────────────────────────
def _write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def plant(tr: Trace) -> Path | None:
    try:
        with _lock:
            if tr.folder is None:
                msg = re.sub(r"[^A-Za-z0-9]", "", tr.meta.get("message_id", ""))[:8] or tr.id[:8]
                stamp = time.strftime("%Y-%m-%d_%Hh%Mm%S", time.localtime(tr.wall))
                tr.folder = INCIDENTS / f"{stamp}_{msg}"
            folder = tr.folder
        (folder / "takes").mkdir(parents=True, exist_ok=True)
        (folder / "heard.mp3").write_bytes(bytes(tr.heard))
        for t in tr.takes:
            if t.pcm:
                _write_wav(folder / "takes" / f"{t.idx:02d}.wav", bytes(t.pcm))
        trace = {
            "trace": tr.id,
            "when": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(tr.wall)),
            "wall": tr.wall,
            "chat_id": tr.meta.get("chat_id"),
            "message_id": tr.meta.get("message_id"),
            "chat_url": f"/c/{tr.meta['chat_id']}" if tr.meta.get("chat_id") else None,
            "model": tr.meta.get("model"),
            "voice": tr.voice,
            "pacing": tr.pacing,
            "sieve_mode": tr.sieve_mode,
            "complete": tr.done and not tr.cut_short,
            "cut_short": tr.cut_short,
            "truncated": tr.truncated,
            "heard_s": max((t.end_s or 0 for t in tr.takes), default=0),
            "flags": tr.flags,
            "takes": [{
                "idx": t.idx, "para_end": t.para_end, "raw": t.raw, "fed": t.fed,
                "status": t.status, "error": t.error,
                "t_req": t.t_req, "t_first": t.t_first, "t_done": t.t_done,
                "start_s": t.start_s, "end_s": t.end_s,
                "audio_s": round(len(t.pcm) / (2 * RATE), 3),
                "wav": f"takes/{t.idx:02d}.wav" if t.pcm else None,
            } for t in tr.takes],
            "source": tr.meta.get("source"),
        }
        (folder / "trace.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        analyse_incident(folder)
        log.info("🚩 voice incident planted: %s", folder)
        return folder
    except Exception as e:  # a flag must never hurt her stream
        log.warning("voice trace: could not plant incident (%s)", e)
        return None


# ── listening for the wrongness ──────────────────────────────────────────────
WIN, HOP = 1024, 480  # 43 ms window, 20 ms hop
_BANDS = None


def _bands():
    global _BANDS
    if _BANDS is None:
        freqs = np.fft.rfftfreq(WIN, 1 / RATE)
        edges = np.geomspace(80, RATE / 2, 33)
        _BANDS = [b for b in ((freqs >= lo) & (freqs < hi) for lo, hi in zip(edges[:-1], edges[1:])) if b.any()]
    return _BANDS


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def audio_stats(x: np.ndarray) -> dict:
    """numbers only. repeat_run_s: the longest stretch where the voice keeps matching itself at
    one fixed delay (a loop). floor_db + quiet_flatness: the noise under her (hiss is flat and high)."""
    dur = len(x) / RATE
    out = {"audio_s": round(dur, 3)}
    if len(x) < WIN * 4:
        return out
    n = 1 + (len(x) - WIN) // HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    fr = x[idx] * np.hanning(WIN)[None, :]
    spec = np.abs(np.fft.rfft(fr, axis=1)) ** 2 + 1e-12
    rms = np.sqrt(np.mean(x[idx] ** 2, axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    voiced = db > max(db.max() - 35, -60)

    feats = np.log(np.stack([spec[:, b].sum(axis=1) for b in _bands()], axis=1) + 1e-10)
    feats -= feats.mean(axis=0, keepdims=True)
    feats /= np.linalg.norm(feats, axis=1, keepdims=True) + 1e-9

    best_run, best_lag, cover = 0, 0.0, np.zeros(n, bool)
    for lag in range(8, min(160, n // 2)):  # 0.16 s … 3.2 s
        sim = np.einsum("ij,ij->i", feats[:-lag], feats[lag:])
        both = voiced[:-lag] & voiced[lag:]
        hit = (sim > 0.9) & both
        cover[:-lag] |= hit
        if hit.any():  # longest run where her voice keeps matching (little quiet gaps don't break it)
            ok = hit | ~(voiced[:-lag] | voiced[lag:])
            d = np.diff(np.concatenate(([0], ok.astype(np.int8), [0])))
            starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
            ch = np.concatenate(([0], np.cumsum(hit)))
            r = int((ch[ends] - ch[starts]).max())  # matched voiced frames inside the best run
            if r > best_run:
                best_run, best_lag = r, lag * HOP / RATE
    out["repeat_run_s"] = round(best_run * HOP / RATE, 2)
    out["repeat_lag_s"] = round(best_lag, 2)
    out["repeat_cover"] = round(float(cover[voiced].mean()) if voiced.any() else 0.0, 3)

    q = db <= np.percentile(db, 15)
    hf = np.fft.rfftfreq(WIN, 1 / RATE) >= 4000
    p = spec[q][:, hf]
    out["floor_db"] = round(float(np.percentile(db, 10)), 1)
    out["quiet_flatness"] = round(float(np.mean(np.exp(np.log(p).mean(axis=1)) / p.mean(axis=1))), 3)
    vs = spec[voiced]
    out["hf_ratio"] = round(float(vs[:, hf].sum() / vs.sum()), 4) if voiced.any() else 0.0
    out["peak_db"] = round(float(20 * np.log10(np.abs(x).max() + 1e-9)), 1)
    out["clip_frac"] = round(float(np.mean(np.abs(x) > 0.99)), 5)
    out["voiced_frac"] = round(float(voiced.mean()), 3)
    return out


# ── what was in the words ────────────────────────────────────────────────────
try:
    from open_webui.routers.audio.tts_sieve import EMOJI_RE as _EMOJI_RE
except ImportError:
    try:
        from tts_sieve import EMOJI_RE as _EMOJI_RE
    except ImportError:
        _EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")

_TEXT_CUES = {
    "tilde": re.compile(r"~"),
    "asterisk": re.compile(r"\*"),
    "underscore": re.compile(r"_"),
    "backtick": re.compile(r"`"),
    "pipe": re.compile(r"\|"),
    "hash": re.compile(r"#"),
    "bracket": re.compile(r"[\[\]{}<>]"),
    "paren": re.compile(r"[()]"),
    "quote": re.compile(r"[\"“”«»]"),
    "ellipsis": re.compile(r"…|\.{3}"),
    "exclaim": re.compile(r"!"),
    "question": re.compile(r"\?"),
    "dash": re.compile(r"[—–]| - "),
    "stretched": re.compile(r"([A-Za-zÀ-ÿ])\1{2,}"),  # sooo, mmmh
    "repeat_syllable": re.compile(r"(\w{2,4})\1{2,}", re.I),  # luvluvluv, hahaha
    "caps_word": re.compile(r"\b[A-Z]{3,}\b"),
    "digit": re.compile(r"\d"),
    "accent": re.compile(r"[À-ÿ]"),  # french, mostly
    "non_latin": re.compile(r"[^\x00-ɏ\s\W]"),
    "url": re.compile(r"https?://|www\."),
    "slash": re.compile(r"/"),
    "colon": re.compile(r":"),
}


def _ending(t: str) -> str:
    e = t.rstrip(" \t\n\"'”’»)]*_`")
    if not e:
        return "empty"
    for k, s in (("ellipsis", ("…", "...")), ("question", ("?",)), ("exclaim", ("!",)), ("tilde", ("~",)),
                 ("period", (".",)), ("colon", (":", ";")), ("comma", (",",))):
        if e.endswith(s):
            return k
    return "emoji" if _EMOJI_RE.search(e[-2:]) else "none"


def _md_context(raw: str, source: str | None) -> str:
    """where the sentence lived in the reply's markdown (best effort)"""
    if not source:
        return "unknown"
    key = re.sub(r"\W+", "", raw.lower())[:24]
    if len(key) < 6:
        return "unknown"
    for line in source.splitlines():
        if key in re.sub(r"\W+", "", line.lower()):
            s = line.lstrip()
            if s.startswith("|"):
                return "table"
            if s.startswith("#"):
                return "heading"
            if s.startswith(">"):
                return "quote"
            if re.match(r"([-*+]|\d+[.)])\s", s):
                inner = "list"
            else:
                inner = "plain"
            if "**" in s or "__" in s:
                return inner + "+bold"
            if re.search(r"(?<!\*)\*[^*\s][^*]*\*(?!\*)|(?<!_)_[^_\s][^_]*_(?!_)", s):
                return inner + "+italic"
            if "`" in s:
                return inner + "+code"
            return inner
    return "unknown"


def text_stats(raw: str, fed: str, source: str | None) -> dict:
    out = {"chars_raw": len(raw), "chars_fed": len(fed), "words_fed": len(fed.split()),
           "emoji_raw": len(_EMOJI_RE.findall(raw)), "emoji_fed": len(_EMOJI_RE.findall(fed)),
           "ending_fed": _ending(fed), "md": _md_context(raw, source)}
    for k, rx in _TEXT_CUES.items():
        out[k] = len(rx.findall(fed))
    out["wordless"] = int(bool(raw.strip()) and not re.search(r"[^\W_]", raw) and not _EMOJI_RE.search(raw))  # "---", "***"
    return out


# ── the analysis that lives beside each incident ─────────────────────────────
LOOP_RUN_S = 1.2  # a self-match this long at one delay is not ordinary speech
LOOP_COVER = 0.6  # or most of a take's voice is a copy of itself somewhere
STRETCH_X = 2.2  # a take this many times longer than her usual seconds-per-character
HISS_DB = 9.0  # a noise floor this far above the reply's own median


def analyse_incident(folder: Path) -> dict | None:
    tp = folder / "trace.json"
    if not tp.exists():
        return None
    tr = json.loads(tp.read_text(encoding="utf-8"))
    rows = []
    for t in tr["takes"]:
        row = {"idx": t["idx"], "status": t.get("status"), "lost": bool(t.get("error")),
               "pos": round(t["idx"] / max(1, len(tr["takes"]) - 1), 3),
               "start_s": t.get("start_s"), "ttfb_s": None, "gen_s": None}
        if t.get("t_req") is not None and t.get("t_first") is not None:
            row["ttfb_s"] = round(t["t_first"] - t["t_req"], 3)
        if t.get("t_req") is not None and t.get("t_done") is not None:
            row["gen_s"] = round(t["t_done"] - t["t_req"], 3)
        row.update(text_stats(t.get("raw", ""), t.get("fed", ""), tr.get("source")))
        wav = folder / (t.get("wav") or "")
        if t.get("wav") and wav.exists():
            row.update(audio_stats(_read_wav(wav)))
        rows.append(row)

    spc = [r["audio_s"] / max(1, r["chars_fed"]) for r in rows if r.get("audio_s") and r["chars_fed"] >= 12]
    med_spc = float(np.median(spc)) if spc else None
    floors = [r["floor_db"] for r in rows if "floor_db" in r]
    med_floor = float(np.median(floors)) if floors else None
    flagged = {f["part"] for f in tr.get("flags", []) if f.get("part") is not None}
    for r in rows:
        why = []
        if r.get("repeat_run_s", 0) >= LOOP_RUN_S or (r.get("repeat_cover", 0) >= LOOP_COVER and r.get("audio_s", 0) >= 2):
            why.append("loop")
        if med_spc and r.get("audio_s") and r["chars_fed"] >= 4:
            r["stretch"] = round(r["audio_s"] / max(1, r["chars_fed"]) / med_spc, 2)
            if r["stretch"] >= STRETCH_X:
                why.append("stretch")
        if med_floor is not None and "floor_db" in r and r["floor_db"] - med_floor >= HISS_DB:
            why.append("hiss")
        if r["lost"]:
            why.append("lost")
        r["suspect"] = why
        r["flagged"] = r["idx"] in flagged
    out = {"analysed": time.strftime("%Y-%m-%d %H:%M:%S"), "thresholds": {
        "loop_run_s": LOOP_RUN_S, "loop_cover": LOOP_COVER, "stretch_x": STRETCH_X, "hiss_db": HISS_DB},
        "median_s_per_char": round(med_spc, 4) if med_spc else None, "median_floor_db": med_floor,
        "flagged_parts": sorted(flagged), "takes": rows}
    (folder / "analysis.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


# ── the report you can share: numbers and categories, never her words ───────
_NUM_CUES = ["wordless", "emoji_raw", "emoji_fed"] + list(_TEXT_CUES)


def report() -> str:
    folders = sorted(p for p in INCIDENTS.glob("*/") if (p / "trace.json").exists()) if INCIDENTS.exists() else []
    if not folders:
        return "🌸 no voice incidents planted yet — flag one with 🚩 or your earbuds' next-track press."
    bad, good, lines = [], [], []
    lines.append(f"# 🚩 petal voice incidents · {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("stats only: numbers and categories, no text. a take is *bad* when flagged or auto-suspect.")
    lines.append("")
    lines.append("| incident | when | sieve | takes | flagged | auto-suspect (idx:why) | worst loop s | heard s |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, f in enumerate(folders):
        a = analyse_incident(f)
        tr = json.loads((f / "trace.json").read_text(encoding="utf-8"))
        rows = a["takes"]
        sus = [f"{r['idx']}:{'+'.join(r['suspect'])}" for r in rows if r["suspect"]]
        worst = max((r.get("repeat_run_s", 0) for r in rows), default=0)
        heard = sum(r.get("audio_s", 0) for r in rows)
        lines.append(f"| #{i + 1} | {tr['when'][5:16]} | {tr.get('sieve_mode')} | {len(rows)} | "
                     f"{','.join(map(str, a['flagged_parts'])) or 'whole'} | {' '.join(sus) or '—'} | {worst} | {heard:.0f} |")
        for r in rows:
            (bad if (r["flagged"] or r["suspect"]) else good).append(r)
    lines.append("")
    lines.append(f"**{len(bad)} bad takes vs {len(good)} clean takes** across {len(folders)} incidents")
    lines.append("")

    def rate(rs, k):
        return sum(1 for r in rs if r.get(k, 0) > 0) / len(rs) if rs else 0.0

    def mean(rs, k):
        v = [r[k] for r in rs if isinstance(r.get(k), (int, float))]
        return sum(v) / len(v) if v else float("nan")

    lines.append("## text cues — how often a take contained it")
    lines.append("")
    lines.append("| cue | bad | clean | lift |")
    lines.append("|---|---|---|---|")
    cue_rows = []
    for k in _NUM_CUES:
        b, g = rate(bad, k), rate(good, k)
        if b or g:
            cue_rows.append((k, b, g, (b + 0.02) / (g + 0.02)))
    for k, b, g, lift in sorted(cue_rows, key=lambda c: -c[3]):
        lines.append(f"| {k} | {b:.0%} | {g:.0%} | {lift:.1f}× |")
    lines.append("")
    lines.append("## shape — means")
    lines.append("")
    lines.append("| measure | bad | clean |")
    lines.append("|---|---|---|")
    for k in ("chars_fed", "words_fed", "pos", "start_s", "ttfb_s", "gen_s", "audio_s", "stretch",
              "repeat_run_s", "repeat_cover", "floor_db", "quiet_flatness", "hf_ratio", "peak_db"):
        lines.append(f"| {k} | {mean(bad, k):.3g} | {mean(good, k):.3g} |")
    for cat in ("ending_fed", "md"):
        lines.append("")
        lines.append(f"## {cat} — share of takes")
        lines.append("")
        lines.append("| kind | bad | clean |")
        lines.append("|---|---|---|")
        kinds = sorted({r.get(cat) for r in bad + good})
        for kd in kinds:
            b = sum(1 for r in bad if r.get(cat) == kd) / len(bad) if bad else 0
            g = sum(1 for r in good if r.get(cat) == kd) / len(good) if good else 0
            lines.append(f"| {kd} | {b:.0%} | {g:.0%} |")
    lines.append("")
    lines.append("_a lift only means something once a few incidents are planted~ one reply is a story, five are a pattern._")
    md = "\n".join(lines) + "\n"
    (INCIDENTS / f"report-{time.strftime('%Y-%m-%d')}.md").write_text(md, encoding="utf-8")
    return md


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "report":
        print(report())
        print(f"📄 written beside your incidents: {INCIDENTS}/report-{time.strftime('%Y-%m-%d')}.md")
    elif cmd == "last":
        folders = sorted(p for p in INCIDENTS.glob("*/") if (p / "trace.json").exists()) if INCIDENTS.exists() else []
        if not folders:
            sys.exit("🌸 no incidents yet")
        a = analyse_incident(folders[-1])
        print(f"🚩 {folders[-1].name}   flagged: {a['flagged_parts'] or 'whole reply'}")
        print(f"{'idx':>3} {'audio_s':>7} {'stretch':>7} {'loop_s':>6} {'cover':>5} {'floor':>6} {'ttfb':>5}  suspect")
        for r in a["takes"]:
            print(f"{r['idx']:>3} {r.get('audio_s', 0):>7} {r.get('stretch', '-'):>7} {r.get('repeat_run_s', '-'):>6} "
                  f"{r.get('repeat_cover', '-'):>5} {r.get('floor_db', '-'):>6} {r.get('ttfb_s') or '-':>5}  "
                  f"{'🚩 ' if r['flagged'] else ''}{'+'.join(r['suspect'])}")
        print(f"🎧 takes: {folders[-1]}/takes/")
    elif cmd == "analyse" and len(sys.argv) > 2:
        print(json.dumps(analyse_incident(Path(sys.argv[2]).expanduser()), indent=2))
    else:
        sys.exit("usage: voice_trace.py [report | last | analyse <incident folder>]")
