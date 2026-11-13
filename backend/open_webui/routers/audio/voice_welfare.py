"""
🕊️🎀 voice welfare — a looping take is never what reaches her ears
────────────────────────────────────────────────────────────────────
the omni voice sometimes falls into a deadloop (the "quantum hell": a stuck syllable, a wet loop,
a hiss that won't end) or, rarer and worse, a runaway that clips at full scale. welfare listens to
each sentence take with the shared ear (voice_measure) and swaps a bad take for a fresh generation
of the same sentence (a new seed, so it truly is fresh). her good takes are never retouched:
nothing is faded, padded or trimmed. a whole bad take goes, a whole fresh take comes. after
max_tries bad takes the sentence is skipped with a clean silence, so a deadloop never lands raw.

  kills    loop · stretch (runs far past its text) · clip (hot peaks) · surge (louder and harsher
           than her own voice, once her baseline knows both) · broken (the voice ended the take
           with an error, or gave no audio: every take is judged, error or not, and a broken one
           is never played as it arrived. always a kill)
  watches  cover · hiss (numbers only, never touched)
  ceiling  🛡️ apart from all of it, awake or asleep: nothing that plays ever goes above
           ceiling_dbfs (voice_ceiling.py), in the stream, the speaker clips and the speech cache

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
    from open_webui.routers.audio import voice_ceiling as vc
    from open_webui.routers.audio import voice_measure as vm
else:  # on its own, beside its siblings (never waking OWUI's config)
    import voice_ceiling as vc
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
ALWAYS_KILL = ("broken",)  # a take the voice ended with an error is never played as it arrived (nov 13 2026)
DEFAULTS = {
    "enabled": False,  # asleep until she wakes it
    "max_tries": 3,
    "hold": "airtight",
    "window_s": None,  # near-free's held-back seconds. None = the loop rule's own length
    "skip_silence_ms": 500,
    "audit_until": None,
    "audit_days": 14,
    "enabled_at": None,
    # cover watches only: its 9 would-be kills in her cache (nov 5 2026) were all her normal voice.
    # clip · surge · broken: born nov 13 2026, after a broken runaway take reached her raw
    "acts": {"loop": "kill", "cover": "watch", "stretch": "kill", "hiss": "watch",
             "clip": "kill", "surge": "kill", "broken": "kill"},
    "ceiling_dbfs": -3.0,  # 🛡️ the hard safety ceiling on everything that plays (voice_ceiling.py). null = off
    "thresholds": {},
    "baseline": dict(vm.DEFAULT_BASELINE),
}
ABOUT = ("voice welfare, read at the start of every reply and every speaker clip (no restart). "
         "enabled: the guard is awake. max_tries: takes per sentence before it's skipped with a clean silence "
         "(skip_silence_ms of it). hold: airtight (every take judged whole before it plays) or near-free (held "
         "whole while the voice is ahead of you, a window_s window only while you're waiting). acts: what each "
         "reason does, kill | watch (numbers only, never touched) | off. thresholds: the rule (voice_measure.py). "
         "baseline: your pace (s_per_char), usual floor (floor_db), loudness (level_db) and zero-crossing rate (zcr_hz), "
         "from calibration (./petal-voice-welfare.sh baseline). audit_until: unix s, until then every kill keeps its "
         "evidence in welfare-audit/ (extend: ./petal-voice-welfare.sh audit 7). broken: a take the voice ended with an "
         "error is never played as it arrived. ceiling_dbfs: no sample that plays ever goes above it, welfare awake or "
         "asleep (null turns it off).")
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
    if "ceiling_dbfs" in raw:  # null turns the ceiling off; anything else is held between -24 and 0 dBFS
        v = raw["ceiling_dbfs"]
        cfg["ceiling_dbfs"] = None if v is None else max(-24.0, min(0.0, float(v))) \
            if isinstance(v, (int, float)) and not isinstance(v, bool) else cfg["ceiling_dbfs"]
    for k in ("window_s", "skip_silence_ms", "audit_until", "audit_days", "enabled_at"):
        if isinstance(raw.get(k), (int, float)) and not isinstance(raw[k], bool) and raw[k] >= 0:
            cfg[k] = raw[k]
    if isinstance(raw.get("acts"), dict):
        for k, v in raw["acts"].items():
            if k in cfg["acts"] and v in ACTS and k not in ALWAYS_KILL:
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
              audit_days: float | None = None, thresholds: dict | None = None, acts: dict | None = None,
              valve: bool | None = None) -> dict:
    """the only writer of welfare.json (the helper and the Petal Sieve filter's valve both come
    through here). the first waking starts the audit fortnight."""
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
        if thresholds:
            for k, v in thresholds.items():
                if k not in vm.DEFAULT_THRESHOLDS:
                    raise ValueError(f"no rule called {k} (rules: {', '.join(vm.DEFAULT_THRESHOLDS)})")
                if not (v is None and vm.DEFAULT_THRESHOLDS[k] is None) and \
                        not (isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0):
                    raise ValueError(f"{k} wants a number ≥ 0")
            raw["thresholds"] = {**(raw.get("thresholds") or {}), **thresholds}
        if acts:
            for k, v in acts.items():
                if k not in DEFAULTS["acts"] or v not in ACTS:
                    raise ValueError(f"acts: {', '.join(DEFAULTS['acts'])} → {' | '.join(ACTS)}")
                if k in ALWAYS_KILL and v != "kill":
                    raise ValueError(f"{k} is always a kill: a take the voice ended with an error is never played "
                                     "as it arrived")
            raw["acts"] = {**DEFAULTS["acts"], **(raw.get("acts") or {}), **acts}
        if valve is not None:
            raw["valve"] = bool(valve)  # what the Sieve filter's switch last said (last action wins)
        raw["set_by"], raw["set_at"] = by, round(now)
        _write_raw(raw)
    return load()


def from_valve(on: bool, by: str = "petal-sieve filter") -> str | None:
    """the Petal Sieve filter's 🕊️ switch, last action wins: only a *flip* of the switch touches
    "enabled", so the helper's on/off and hand edits hold in between. before the first waking it
    does nothing (that goes through ./petal-voice-welfare.sh on: the sweep check, her pace, the
    audit fortnight). → what it did: None · "first sight" · "on" · "off" """
    raw, exists, broken = _read_raw()
    if not exists or broken or not raw.get("enabled_at"):
        return None
    last = raw.get("valve")
    if last is None:  # first time the filter sees welfare awake: remember the switch, only ever turn off
        set_knobs(by=by, valve=on, enabled=None if on else False)
        return "first sight"
    if bool(last) != bool(on):
        set_knobs(by=by, valve=on, enabled=on)
        return "on" if on else "off"
    return None


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
        self.pcm: bytes | None = None  # the last speaker clip, decoded (for the ceiling)
        self._seed: int | None = None

    def seed(self) -> int:
        """a fresh seed for every take: vLLM-Omni hands it to the talker and to the code predictor, so
        a resample is a truly new generation (and any take can be asked again exactly)"""
        self._seed = secrets.randbits(31)
        return self._seed

    def watch(self) -> vm.TakeWatch:
        b = self.cfg["baseline"]
        return vm.TakeWatch(len(self.text), t=self.t, s_per_char=self.spc, floor_ref=self.floor, acts=self.acts,
                            level_ref=b.get("level_db"), zcr_ref=b.get("zcr_hz"))

    @property
    def spent(self) -> bool:
        return len(self.kills) >= self.max_tries

    @property
    def skipped(self) -> bool:
        return self.spent and self.kept is None

    def kill(self, w: vm.TakeWatch, pcm: bytes, heard_s: float = 0.0, broken: str | None = None) -> None:
        """broken: the error the voice ended this take with (it is never played as it arrived)"""
        if broken:
            w.why = ["broken"] + [r for r in w.why if r != "broken"]
        n = w.numbers()
        n["why"] = [r for r in n["why"] if self.acts.get(r) == "kill"] or n["why"]
        n["violent"] = bool(set(n["why"]) & vm.VIOLENT)  # never auto-played back: numbers are enough
        if broken:
            n["error"] = broken
        self.kills.append({"try": len(self.kills) + 1, "seed": self._seed, "heard_s": round(heard_s, 3), **n})
        if self.audit:
            self.killed_pcm.append(bytes(pcm))

    @property
    def violent(self) -> bool:
        return any(k.get("violent") for k in self.kills)

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
            "recovered": self.kept is not None, "violent": self.violent,
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
    """heavy (decode + listen): run it in a thread. True = keep this clip (sent.pcm holds it decoded)"""
    pcm = decode_clip(data, content_type)
    sent.pcm = pcm
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


def broken_clip(sent: Sentence, err: str) -> None:
    """the voice answered a speaker clip with an error: a kill like any other, asked again"""
    sent.kill(sent.watch(), b"", broken=err)


def is_broken_take(e: BaseException) -> bool:
    """an error a fresh take can heal: the voice broke off mid-take (payload cut, disconnect,
    timeout) or failed it (5xx). not one saying the voice isn't there (no connection) or that the
    ask itself is wrong (4xx): those still surface as the honest error, and nothing plays"""
    import aiohttp

    if isinstance(e, aiohttp.ClientResponseError):
        return e.status >= 500
    if isinstance(e, aiohttp.ClientConnectorError):
        return False
    return isinstance(e, (aiohttp.ClientError, TimeoutError))


# ── 🛡️ the ceiling on speaker clips and the speech cache ─────────────────────
def _wav_bytes(pcm: bytes) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return b.getvalue()


def _under(dbfs: float, pcm: bytes) -> tuple[bytes, vc.Ceiling] | None:
    """→ (the turned-down pcm, its ceiling) when pcm runs above dbfs, else None (untouched)"""
    c = vc.Ceiling(dbfs)
    low = c.process(pcm)
    return (low, c) if c.touched else None


def ceiling_clip(cfg: dict, sent: Sentence | None, data: bytes, content_type: str) -> tuple[bytes, str]:
    """a speaker clip's last pass before it's returned and cached, welfare awake or asleep (sync: run
    it in a thread). untouched, byte for byte, unless it runs above the ceiling: then turned down and
    re-encoded as mp3 (wav if lameenc is missing). a clip that can't be decoded goes out as it came"""
    dbfs = cfg.get("ceiling_dbfs")
    if dbfs is None:
        return data, content_type
    pcm = sent.pcm if sent is not None and sent.pcm is not None else decode_clip(data, content_type)
    hot = _under(dbfs, pcm) if pcm else None
    if hot is None:
        return data, content_type
    low, c = hot
    if c.ran_hot:
        log_ceiling(path="speech", touched_s=c.touched_s, peak_in_db=c.peak_in_db, temp=sent.temp if sent else None)
    mp3 = vc.encode_mp3(low)
    return (mp3, "audio/mpeg") if mp3 else (_wav_bytes(low), "audio/wav")


def mark_ceiling(path, cfg: dict) -> None:
    """the cached clip at path has passed the ceiling (so a replay never decodes it again)"""
    if cfg.get("ceiling_dbfs") is None:
        return
    try:
        Path(path).with_suffix(".ceil").write_text(f"{cfg['ceiling_dbfs']}\n", encoding="utf-8")
    except OSError as e:
        log.debug("voice ceiling: mark not written (%s)", e)


def ceiling_cached(path) -> None:
    """a cached speaker clip passes the ceiling once: clips cached before it existed (or under a
    higher one) are turned down in place the first time they're replayed, then marked. sync: run it
    in a thread. anything it can't read is left as it is (the cache is OWUI's, never broken here)"""
    cfg = load()
    dbfs = cfg["ceiling_dbfs"]
    if dbfs is None:
        return
    path = Path(path)
    mark = path.with_suffix(".ceil")
    try:
        if float(mark.read_text(encoding="utf-8").strip()) <= dbfs + 1e-6:
            return
    except (OSError, ValueError):
        pass
    try:
        if time.time() - path.stat().st_mtime < 10:
            return  # still being written by the clip path (which marks it itself): never touch a half file
        mime = path.with_suffix(".mime")  # slim installs keep the clip's type beside it
        ct = mime.read_text(encoding="utf-8").strip() if mime.exists() else \
            ("audio/wav" if path.suffix == ".wav" else "audio/mpeg")
        pcm = decode_clip(path.read_bytes(), ct)
        hot = _under(dbfs, pcm) if pcm else None
        if hot is not None:
            low, c = hot
            wav = path.suffix == ".wav" or ct in ("audio/wav", "audio/x-wav")
            out = None if wav else vc.encode_mp3(low)
            new_ct = "audio/mpeg" if out else "audio/wav"
            out = out or _wav_bytes(low)
            tmp = path.with_suffix(path.suffix + ".ceil-tmp")
            tmp.write_bytes(out)
            os.replace(tmp, path)
            if mime.exists():
                mime.write_text(new_ct, encoding="utf-8")
            if c.ran_hot:
                log_ceiling(path="speech-cache", touched_s=c.touched_s, peak_in_db=c.peak_in_db)
        mark_ceiling(path, cfg)
    except Exception as e:  # noqa: BLE001 — a replay must never break over this
        log.warning("voice ceiling: cached clip %s not checked (%s)", path.name, e)


def log_ceiling(*, path: str, touched_s: float, peak_in_db: float | None, temp: bool | None = None) -> None:
    """one numbers-only line whenever the ceiling had to turn something down (it should be rare)"""
    try:
        _append(LOG_PATH, {"v": 1, "kind": "ceiling", "at": round(time.time(), 3), "path": path, "temp": temp,
                           "touched_s": round(touched_s, 3), "peak_in_db": peak_in_db})
    except OSError as e:
        log.warning("voice welfare: welfare.jsonl not written (%s)", e)


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
