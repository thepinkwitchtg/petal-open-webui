"""
🕊️🎀 voice welfare — a looping take is never what reaches her ears
────────────────────────────────────────────────────────────────────
the omni voice sometimes falls into a deadloop (the "quantum hell": a stuck syllable, a wet loop,
a hiss that won't end). welfare listens to each sentence take with the shared ear (voice_measure)
and swaps a bad take for a fresh generation of the same sentence (a new seed, so it truly is
fresh). her good takes are never retouched: nothing is faded, padded or trimmed. a whole bad take
goes, a whole fresh take comes. after max_tries bad takes the sentence is skipped with a clean
silence, so a deadloop never lands raw.

  petal stream   each sentence is judged as it arrives (petal_stream.produce)
  speaker clips  the whole clip is judged before it's returned, and a killed take never reaches
                 OWUI's speech cache (which would replay it every time that line is spoken)
  Siren          never passes through here: studio work keeps its own approve/regen flow

how much is held back before she's heard (welfare.json → "hold"):
  airtight    every take is judged whole before a single sample plays. nothing of a bad take is
              ever heard. her first sound waits for the whole first take
  near-free   a take is still held whole whenever the voice is ahead of her ears (almost always,
              omni runs far faster than she speaks). only while she's actually waiting (the first
              sentence, or if the voice ever falls behind) does audio go out early, always keeping
              the last loop-rule seconds back: a loop's repeats are never heard, but a take killed
              after it started would have its opening heard twice (old take, then the fresh one)

her knobs, private, outside any repo: ~/Gardens/Documents/Petal-App-Data/petal-voice/welfare.json
(read at the start of every reply and every speaker clip). welfare sleeps until she wakes it
(./petal-voice-welfare.sh on): that first waking starts the audit fortnight, 14 days where every
kill also keeps its evidence in welfare-audit/ for her ears, then the keeping stops by itself.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
import threading
import time
import wave
from pathlib import Path

import numpy as np

if __package__:  # inside OWUI
    from open_webui.routers.audio import voice_measure as vm
else:  # on its own, beside its siblings (never waking OWUI's config)
    import voice_measure as vm

log = logging.getLogger(__name__)

APP = Path(os.environ.get("PETAL_APP_DATA", Path.home() / "Gardens/Documents/Petal-App-Data")).expanduser()
VOICE = APP / "petal-voice"
CONFIG_PATH = VOICE / "welfare.json"
LOG_PATH = VOICE / "welfare.jsonl"
AUDIT_DIR = VOICE / "welfare-audit"
VERDICTS_PATH = AUDIT_DIR / "verdicts.jsonl"
RATE = vm.RATE
DAY = 86400

HOLDS = ("airtight", "near-free")
ACTS = ("kill", "watch", "off")
DEFAULTS = {
    "enabled": False,  # asleep until she wakes it
    "max_tries": 3,
    "hold": "airtight",
    "window_s": None,  # near-free's held-back seconds. None = the loop rule's own length
    "skip_silence_ms": 500,
    "audit_until": None,
    "audit_days": 14,
    "enabled_at": None,
    "acts": {"loop": "kill", "stretch": "kill", "hiss": "watch"},
    "thresholds": {},
    "baseline": dict(vm.DEFAULT_BASELINE),
}
ABOUT = ("voice welfare, read at the start of every reply and every speaker clip (no restart). "
         "enabled: the guard is awake. max_tries: takes per sentence before it's skipped with a clean silence "
         "(skip_silence_ms of it). hold: airtight (every take judged whole before it plays) or near-free (held "
         "whole while the voice is ahead of you, a window_s window only while you're waiting). acts: what each "
         "reason does, kill | watch (numbers only, never touched) | off. thresholds: the rule (voice_measure.py). "
         "baseline: your pace (s_per_char) and your usual floor (floor_db), from calibration. audit_until: unix s, "
         "until then every kill keeps its evidence in welfare-audit/ (extend: ./petal-voice-welfare.sh audit 7).")
_lock = threading.Lock()


# ── her knobs ─────────────────────────────────────────────────────────────────
def _read_raw() -> tuple[dict, bool, bool]:
    if not CONFIG_PATH.exists():
        return {}, False, False
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return (raw, True, False) if isinstance(raw, dict) else ({}, True, True)
    except (OSError, ValueError):
        return {}, True, True


_warned: float | None = None


def load() -> dict:
    """welfare.json merged over the defaults. a broken file reads as the defaults (asleep), and
    `broken` says so: a typo can never turn the guard into something that hurts her voice."""
    global _warned
    raw, exists, broken = _read_raw()
    if broken:
        try:
            m = CONFIG_PATH.stat().st_mtime
        except OSError:
            m = 0.0
        if _warned != m:  # once per version of the file, not once per sentence
            _warned = m
            log.warning("🕊️ voice welfare: %s is unreadable, so the guard sleeps until it's fixed", CONFIG_PATH)
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    if exists and not broken:
        cfg["enabled"] = raw.get("enabled", True) is True
    if isinstance(raw.get("max_tries"), int) and not isinstance(raw["max_tries"], bool):
        cfg["max_tries"] = max(1, min(8, raw["max_tries"]))
    if raw.get("hold") in HOLDS:
        cfg["hold"] = raw["hold"]
    for k in ("window_s", "skip_silence_ms", "audit_until", "audit_days", "enabled_at"):
        if isinstance(raw.get(k), (int, float)) and not isinstance(raw[k], bool) and raw[k] >= 0:
            cfg[k] = raw[k]
    if isinstance(raw.get("acts"), dict):
        for k, v in raw["acts"].items():
            if k in cfg["acts"] and v in ACTS:
                cfg["acts"][k] = v
    cfg["thresholds"] = vm.thresholds(raw.get("thresholds") if isinstance(raw.get("thresholds"), dict) else None)
    b = raw.get("baseline") if isinstance(raw.get("baseline"), dict) else {}
    for k in vm.DEFAULT_BASELINE:
        v = b.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cfg["baseline"][k] = float(v)
    cfg["exists"], cfg["broken"] = exists, broken
    return cfg


def window_s(cfg: dict) -> float:
    return float(cfg.get("window_s") or cfg["thresholds"]["loop_run_s"])


def audit_open(cfg: dict, now: float | None = None) -> bool:
    return cfg.get("audit_until") is not None and (now or time.time()) < cfg["audit_until"]


def _write_raw(raw: dict) -> None:
    VOICE.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)


def set_knobs(*, by: str, enabled: bool | None = None, hold: str | None = None, baseline: dict | None = None,
              audit_days: float | None = None) -> dict:
    """the only writer of welfare.json. the first waking starts the audit fortnight."""
    with _lock:
        raw, exists, broken = _read_raw()
        if broken:
            raise ValueError(f"{CONFIG_PATH} is unreadable — fix or remove it first (nothing was changed)")
        now = time.time()
        if enabled and not raw.get("enabled_at"):  # 🌱 the very first waking
            raw = {"_about": ABOUT, **raw}
            raw["enabled_at"] = now
            raw.setdefault("audit_until", now + DEFAULTS["audit_days"] * DAY)
            raw.setdefault("max_tries", DEFAULTS["max_tries"])
            raw.setdefault("hold", DEFAULTS["hold"])
            raw.setdefault("skip_silence_ms", DEFAULTS["skip_silence_ms"])
            raw.setdefault("acts", dict(DEFAULTS["acts"]))
            raw.setdefault("thresholds", {k: v for k, v in vm.DEFAULT_THRESHOLDS.items()})
        if enabled is not None:
            raw["enabled"] = bool(enabled)
        if hold is not None:
            if hold not in HOLDS:
                raise ValueError(f"hold must be one of {HOLDS}")
            raw["hold"] = hold
        if baseline:
            raw["baseline"] = {**(raw.get("baseline") or {}), **{k: v for k, v in baseline.items() if k in vm.DEFAULT_BASELINE}}
        if audit_days is not None:
            raw["audit_until"] = max(raw.get("audit_until") or 0, now) + audit_days * DAY
        raw["set_by"], raw["set_at"] = by, round(now)
        _write_raw(raw)
    return load()


# ── the books (numbers only) ──────────────────────────────────────────────────
def _append(path: Path, row: dict) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except ValueError:
            pass
    return out


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


# ── one sentence's welfare: its tries, the take she hears, its trace ─────────
class Sentence:
    """from the first try to the take she hears (or the clean silence). path: stream | speech.
    temp: True in a temp chat (contract 0: guarded all the same, kept without chat/message links),
    False in a saved chat, None when unknown (speaker clips don't say which chat they're from)."""

    def __init__(self, cfg: dict, *, path: str, text: str, idx: int | None = None, chat_id: str | None = None,
                 message_id: str | None = None, temp: bool | None = None, hold: str = "airtight"):
        self.cfg, self.path, self.text, self.idx, self.temp, self.hold = cfg, path, text, idx, temp, hold
        self.chat_id = chat_id if temp is False else None
        self.message_id = message_id if temp is False else None
        self.t = cfg["thresholds"]
        self.spc = vm.pace(cfg["baseline"]) or vm.FALLBACK_S_PER_CHAR
        self.floor = cfg["baseline"].get("floor_db")
        self.acts = cfg["acts"]
        self.max_tries = cfg["max_tries"]
        self.audit = audit_open(cfg)
        self.at = time.time()
        self.kills: list[dict] = []  # one per killed take: seed, why, the guard's numbers, how much was heard
        self.killed_pcm: list[bytes] = []  # only while the audit fortnight lasts
        self.kept: dict | None = None
        self.kept_pcm: bytes | None = None
        self.watched: list[str] = []
        self.unjudged = False
        self._seed: int | None = None

    def seed(self) -> int:
        """a fresh seed for every take: vLLM-Omni hands it to the talker and to the code predictor, so
        a resample is a truly new generation (and any take can be asked again exactly)"""
        self._seed = secrets.randbits(31)
        return self._seed

    def watch(self) -> vm.TakeWatch:
        return vm.TakeWatch(len(self.text), t=self.t, s_per_char=self.spc, floor_ref=self.floor, acts=self.acts)

    @property
    def spent(self) -> bool:
        return len(self.kills) >= self.max_tries

    @property
    def skipped(self) -> bool:
        return self.spent and self.kept is None

    def kill(self, w: vm.TakeWatch, pcm: bytes, heard_s: float = 0.0) -> None:
        n = w.numbers()
        n["why"] = [r for r in n["why"] if self.acts.get(r) == "kill"] or n["why"]
        self.kills.append({"try": len(self.kills) + 1, "seed": self._seed, "heard_s": round(heard_s, 3), **n})
        if self.audit:
            self.killed_pcm.append(bytes(pcm))

    def keep(self, w: vm.TakeWatch, pcm: bytes) -> None:
        self.kept = {"try": len(self.kills) + 1, "seed": self._seed, **w.numbers()}
        self.watched = [r for r in w.why if self.acts.get(r) == "watch"]
        if self.audit and self.kills:
            self.kept_pcm = bytes(pcm)

    def close(self) -> str | None:
        """after her last take: one numbers-only line in welfare.jsonl (only if something was killed or
        watched) and, during the audit fortnight, the evidence folder. → the audit folder's name"""
        if not self.kills and not self.watched and not self.unjudged:
            return None
        folder = None
        if self.kills and self.audit:
            try:
                folder = self._keep_evidence()
            except OSError as e:
                log.warning("voice welfare: audit evidence not kept (%s)", e)
        k0 = self.kills[0]["why"] if self.kills else []
        row = {"v": 1, "kind": "sentence", "at": round(self.at, 3), "path": self.path, "chat_id": self.chat_id,
               "message_id": self.message_id, "temp": self.temp, "sentence_idx": self.idx,
               "reason": "+".join(k0) if self.kills else None,
               "kills": ["+".join(k["why"]) for k in self.kills],
               "tries": len(self.kills) + (1 if self.kept else 0),
               "recovered": (self.kept is not None) if self.kills else None,
               "hold": self.hold if self.path == "stream" else "whole clip",
               "heard_s": round(sum(k["heard_s"] for k in self.kills), 3),
               "watch": self.watched, "unjudged": self.unjudged or None, "audit": folder,
               "numbers": [{k: v for k, v in kk.items() if k not in ("why",)} for kk in self.kills]
               + ([{"kept": True, **{k: v for k, v in self.kept.items() if k != "why"}}] if self.kept and (self.kills or self.watched) else [])}
        try:
            _append(LOG_PATH, row)
        except OSError as e:
            log.warning("voice welfare: welfare.jsonl not written (%s)", e)
        if self.kills:
            log.info("🕊️ voice welfare: %s sentence %s · killed %s · %s", self.path, self.idx,
                     row["kills"], "a fresh take replaced it" if self.kept else "skipped with a clean silence")
        return folder

    def _keep_evidence(self) -> str:  # noqa: D401 — the audit fortnight's folder for this sentence
        stamp = time.strftime("%Y-%m-%d_%Hh%Mm%S", time.localtime(self.at))
        msg = re.sub(r"[^A-Za-z0-9]", "", self.message_id or "")[:8] or ("t" + secrets.token_hex(4))
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        folder, n = AUDIT_DIR / f"{stamp}_{msg}", 2
        while folder.exists():
            folder, n = AUDIT_DIR / f"{stamp}_{msg}-{n}", n + 1
        folder.mkdir()
        for i, pcm in enumerate(self.killed_pcm, 1):
            write_wav(folder / f"kill-{i}.wav", pcm)
        if self.kept_pcm:
            write_wav(folder / "kept.wav", self.kept_pcm)
        (folder / "sentence.txt").write_text(self.text + "\n", encoding="utf-8")
        (folder / "numbers.json").write_text(json.dumps({
            "at": round(self.at, 3), "when": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.at)),
            "path": self.path, "sentence_idx": self.idx, "temp": self.temp, "chat_id": self.chat_id,
            "message_id": self.message_id, "hold": self.hold, "chars": len(self.text),
            "s_per_char": round(self.spc, 4), "thresholds": self.t, "kills": self.kills, "kept": self.kept,
            "recovered": self.kept is not None,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return folder.name


def log_reply(*, temp: bool, sentences: int, kills: int, skipped: int, heard_s: float) -> None:
    """one numbers-only line per petal stream reply the guard watched, so the stats can say
    "N kills in M sentences" (a kill rate), not only list the kills"""
    try:
        _append(LOG_PATH, {"v": 1, "kind": "reply", "at": round(time.time(), 3), "path": "stream", "temp": temp,
                           "sentences": sentences, "kills": kills, "skipped": skipped, "heard_s": round(heard_s, 3)})
    except OSError as e:
        log.warning("voice welfare: welfare.jsonl not written (%s)", e)


# ── speaker clips: a whole clip, judged before it's returned ─────────────────
HER_VOICE = os.environ.get("PETAL_STREAM_TTS_URL", "http://127.0.0.1:8100/v1")


def is_her_voice(url: str | None) -> bool:
    """welfare guards her voice only: whatever answers on petal-voice's port (:8100, either mode),
    whichever host name OWUI uses to reach it. another provider is never judged against her pace."""
    from urllib.parse import urlsplit

    try:
        a, b = urlsplit(url or ""), urlsplit(HER_VOICE)
        return a.port is not None and a.port == b.port
    except ValueError:
        return False


def decode_clip(data: bytes, content_type: str) -> bytes | None:
    """the voice's reply → 24 kHz mono int16 pcm, or None when it can't be heard here (then welfare
    lets the clip through untouched: an ear that can't hear never silences her)"""
    ct = (content_type or "").split(";")[0].strip().lower()
    try:
        if data[:4] == b"RIFF":
            with wave.open(io.BytesIO(data), "rb") as w:
                ch, sw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
                raw = w.readframes(w.getnframes())
            if sw != 2:
                return None
            x = np.frombuffer(raw[: len(raw) // (2 * ch) * 2 * ch], dtype=np.int16)
        elif ct in ("audio/pcm", "audio/l16", "audio/raw"):
            m = re.search(r"rate=(\d+)", content_type or "")
            rate, ch = (int(m.group(1)) if m else RATE), 1
            x = np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16)
        else:
            return _decode_other(data)
    except Exception as e:  # noqa: BLE001 — any unreadable clip simply passes through
        log.debug("voice welfare: clip not decodable (%s)", e)
        return None
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if rate != RATE and len(x):
        n = max(1, int(round(len(x) * RATE / rate)))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x.astype(np.float32)).astype(np.int16)
    return x.tobytes()


def _decode_other(data: bytes) -> bytes | None:
    """mp3 / opus / flac … → 24 kHz mono pcm: OWUI's own pydub first, ffmpeg itself if pydub can't"""
    try:
        from pydub import AudioSegment

        return AudioSegment.from_file(io.BytesIO(data)).set_channels(1).set_sample_width(2).set_frame_rate(RATE).raw_data
    except Exception:  # noqa: BLE001
        pass
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return None
    out = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(RATE),
                          "pipe:1"], input=data, capture_output=True, timeout=60)
    return out.stdout if out.returncode == 0 and out.stdout else None


def judge_clip(sent: Sentence, data: bytes, content_type: str) -> bool:
    """heavy (decode + listen): run it in a thread. True = keep this clip"""
    pcm = decode_clip(data, content_type)
    if pcm is None:
        sent.unjudged = True
        return True
    w = sent.watch()
    w.pcm += pcm
    if w.listen(pcm):
        sent.kill(w, pcm)
        return False
    sent.keep(w, pcm)
    return True


_SILENCE: dict[int, tuple[bytes, str]] = {}


def skip_clip(ms: int) -> tuple[bytes, str]:
    """a clean silence for a skipped sentence (never cached) → (bytes, media type)"""
    ms = int(max(20, min(5000, ms)))
    if ms not in _SILENCE:
        pcm = bytes(2 * int(RATE * ms / 1000))
        try:
            import lameenc

            e = lameenc.Encoder()
            e.set_bit_rate(64)
            e.set_in_sample_rate(RATE)
            e.set_channels(1)
            e.set_quality(2)
            _SILENCE[ms] = (bytes(e.encode(pcm)) + bytes(e.flush()), "audio/mpeg")
        except Exception:  # noqa: BLE001
            b = io.BytesIO()
            with wave.open(b, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(pcm)
            _SILENCE[ms] = (b.getvalue(), "audio/wav")
    return _SILENCE[ms]
