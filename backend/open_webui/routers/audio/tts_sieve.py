#!/usr/bin/env python3
"""
tts_sieve · a thin door to the voice's own sieve (V1, nov 24 2026: one sieve, at the voice)

the sieve no longer lives here. words in, voice out is petal-voice's own rule now: its gate holds
:8100 and every caller meets the same floor there (a line with no words never reaches the model;
every emoji goes by Unicode property; private-use and control characters go; markdown leftovers
become plain words or nothing). no request can lower it.

what stays in the fork:
  · the mood. the Petal Sieve filter's valves pick it and write it to tts-sieve.json ("mood"); the
    fork names it on every line (X-Petal-Mood), and the voice applies it above the floor
  · the same sieve, run here too, by path (never copied): $PETAL_VOICE_SIEVE, else voice_sieve.py in
    $PETAL_VOICE_DIR, else petal_core/petal-voice. so a line that would be silence never costs a
    request, the speech cache keys on the words she really speaks, and the speaker button stays
    sieved while studio (qwen) wears the voice. it is the voice's own code: running it twice
    changes nothing (the floor is idempotent)

without petal-voice beside the fork, words go to the voice as written and the voice's gate (if
there is one) sieves them; this says so once in the log.

  python3 tts_sieve.py "🎀 Are you feeling me deeper, my Doll~?"     the voice's own CLI, every mood
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_DATA = Path(os.environ.get("PETAL_APP_DATA", Path.home() / "Gardens/Documents/Petal-App-Data")).expanduser()
DATA_DIR = APP_DATA / "petal-voice"  # the same place the Petal Sieve filter writes to
CONFIG_PATH = DATA_DIR / "tts-sieve.json"
DEFAULT_VOICE_DIR = "~/Gardens/Transformation Sequences - Automation/petal_core/petal-voice"
LEGACY = {"emoji": "strict", "soft": "soft", "select": "palette", "off": "every"}  # the old modes, as moods

_vs = None
_tried = False


def voice_sieve():
    """the voice's voice_sieve module, loaded by path once (None if petal-voice isn't beside us)"""
    global _vs, _tried
    if _tried:
        return _vs
    _tried = True
    path = os.environ.get("PETAL_VOICE_SIEVE")
    if not path:
        path = str(Path(os.environ.get("PETAL_VOICE_DIR") or DEFAULT_VOICE_DIR).expanduser() / "voice_sieve.py")
    p = Path(path).expanduser()
    if not p.exists():
        log.warning("🎀 tts sieve: the voice's sieve isn't at %s — words go as written; her gate sieves them", p.parent)
        return None
    try:
        added = str(p.parent) not in sys.path
        if added:
            sys.path.insert(0, str(p.parent))  # its emoji table sits beside it
        try:
            spec = importlib.util.spec_from_file_location("petal_voice_sieve", p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["petal_voice_sieve"] = mod
            spec.loader.exec_module(mod)
        finally:
            if added:
                sys.path.remove(str(p.parent))
        _vs = mod
    except Exception as e:  # a broken sieve never silences her: the gate still holds the floor
        log.warning("🎀 tts sieve: couldn't load the voice's sieve (%s)", e.__class__.__name__)
        _vs = None
    return _vs


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def chosen_mood(cfg: dict | None = None) -> str:
    """the mood her valves picked ("mood"; an older file's "mode" is read as its mood). no choice → strict"""
    cfg = load_config() if cfg is None else cfg
    m = cfg.get("mood")
    if isinstance(m, str) and m:
        return m
    return LEGACY.get(cfg.get("mode"), "strict")


def sieve(text: str, mood: str | None = None, group: str | None = None) -> str:
    """what the voice will eat ("" = nothing to say). never raises; without the voice's sieve the
    words go as written (her gate is the floor then). group: where the line belongs in her voice's
    black box (st-… a reply, clip-<msg> the speaker button), so Lily's open floor (V2) keeps its scope here too"""
    vs = voice_sieve()
    if vs is None:
        return text
    try:
        try:
            return vs.sift(text, mood or chosen_mood(), group=group).text
        except TypeError:  # a voice older than V2: no open floor there either
            return vs.sift(text, mood or chosen_mood()).text
    except Exception:
        return text


def clip_group(message_id) -> str | None:
    """the speaker button's group for a message (the same one its X-Petal-Group header names)"""
    if not message_id:
        return None
    return 'clip-' + ''.join(ch for ch in str(message_id) if ch.isalnum() or ch in '-_')[:64]


def sieve_speech_body(body: bytes, mood: str | None = None, group: str | None = None) -> tuple[bytes, bool]:
    """for OWUI's /audio/speech: sieve the JSON body's "input" → (body, emptied).
    an untouched text returns the original bytes, so the speech cache keeps its keys"""
    try:
        payload = json.loads(body)
        text = payload.get("input") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            return body, False
        out = sieve(text, mood, group)
        if out == text:
            return body, False
        if not out.strip():
            return body, True
        payload["input"] = out
        return json.dumps(payload, ensure_ascii=False).encode("utf-8"), False
    except Exception:
        return body, False


_SILENT_MP3: bytes | None = None


def silent_mp3(ms: int = 60) -> bytes | None:
    """a whisper of nothing, for a line with no words: the player moves on without a sound.
    None if lameenc isn't in this venv."""
    global _SILENT_MP3
    if _SILENT_MP3 is None:
        try:
            import lameenc
            e = lameenc.Encoder()
            e.set_bit_rate(64)
            e.set_in_sample_rate(24000)
            e.set_channels(1)
            e.set_quality(2)
            _SILENT_MP3 = bytes(e.encode(b"\x00\x00" * (24 * ms))) + bytes(e.flush())
        except Exception:
            return None
    return _SILENT_MP3


if __name__ == "__main__":
    vs = voice_sieve()
    if vs is None:
        sys.exit("✗ the voice's sieve isn't beside the fork (set $PETAL_VOICE_DIR)")
    sys.exit(vs._cli(sys.argv[1:]))
