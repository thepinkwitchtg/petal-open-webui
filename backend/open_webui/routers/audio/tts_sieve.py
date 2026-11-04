#!/usr/bin/env python3
"""
tts_sieve — a gentle text sieve that sits between Petal's words and the voice.

The chat keeps every emoji and tilde; only what the TTS *eats* is filtered.
Words are never rewritten — Petal's phrasing stays hers.

modes
  off     pass-through
  select  strip only the emoji listed in "select_emoji"
  emoji   strip every emoji (incl. ZWJ sequences, skin tones, flags, keycaps)
  soft    emoji + tildes + stretched letters (sooooo -> soo) + trailing "..." cues

wordless  (every mode, even off) a sentence of bare markup — no letter, digit or emoji: "---",
          "***", "|---|", a lone "…" — is never handed to the voice: with nothing to read she improvises (the
          hyena laugh of Nov 4 2026 was a markdown "---"). set "hush_wordless": false to let her.

control  the Petal Sieve filter (chat controls → valves) writes the config for you;
         hand edits still work, nothing needs wiping
config   (private, outside any repo)
  ~/Gardens/Documents/Petal-App-Data/petal-voice/tts-sieve.json
  {"mode": "select", "select_emoji": ["🎀", "🖤"], "stats": true}

stats  (numbers only, never text)
  ~/Gardens/Documents/Petal-App-Data/petal-voice/tts-sieve-stats.jsonl

where she lives: petal-open-webui, routers/audio — both voices pass through here
  /api/v1/audio/speech   the speaker button (omni chat or qwen studio, whichever serves)
  petal stream           sentence by sentence, screen off
petal-siren deliveries go straight to petal-voice and are never sieved: studio work stays raw.

try it (any python3, no venv needed)
  python3 tts_sieve.py "🎀 Are you feeling me deeper, my Doll~?"     # every mode
  python3 tts_sieve.py --mode soft "sooooo cute~ 💅🏻💅🏻"
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

DATA_DIR = Path.home() / "Gardens" / "Documents" / "Petal-App-Data" / "petal-voice"
CONFIG_PATH = DATA_DIR / "tts-sieve.json"
STATS_PATH = DATA_DIR / "tts-sieve-stats.jsonl"

MODES = ("off", "select", "emoji", "soft")
DEFAULT_CONFIG = {"mode": "emoji", "select_emoji": ["🎀"], "stats": True, "hush_wordless": True}
WORD_RE = re.compile(r"[^\W_]")  # a letter or digit, any script

# --- emoji matching (no dependencies) ---------------------------------------
_EMOJI_BASE = (
    "\U0001F000-\U0001FAFF"   # mahjong … symbols & pictographs ext-A
    "\U00002600-\U000027BF"   # misc symbols, dingbats
    "\U00002B00-\U00002BFF"   # arrows, stars ⭐
    "\U00002190-\U000021FF"   # arrows
    "\U00002300-\U000023FF"   # misc technical ⌛⏰
    "\U00003030\U0000303D\U00003297\U00003299"
    "\U000000A9\U000000AE\U0000203C\U00002049\U00002122\U00002139"
    "\U000024C2\U000025AA-\U000025FE"
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flags)
)
_EMOJI_MODS = (
    "\U0000FE0E\U0000FE0F"    # variation selectors
    "\U0001F3FB-\U0001F3FF"   # skin tones
    "\U000020E3"              # keycap
    "\U000E0020-\U000E007F"   # tag sequences
)
EMOJI_RE = re.compile(
    rf"(?:[0-9#*][{_EMOJI_MODS}]*\U000020E3)"                       # keycaps
    rf"|(?:[{_EMOJI_BASE}][{_EMOJI_MODS}]*"
    rf"(?:\U0000200D[{_EMOJI_BASE}][{_EMOJI_MODS}]*)*)"             # ZWJ chains
)

STRETCH_RE = re.compile(r"([A-Za-zÀ-ÿ])\1{2,}")      # sooooo -> soo
TILDE_RE = re.compile(r"\s*~+\s*")
TRAIL_DOTS_RE = re.compile(r"(?:\.{3,}|…)\s*$")
SPACES_RE = re.compile(r"[ \t]{2,}")
SPACE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")


_MODS_RE = re.compile(rf"[{_EMOJI_MODS}]")


def _bare(e: str) -> str:
    """an emoji without its skin tone / variation selector: 💅🏻 and 💅 are the same nail."""
    return _MODS_RE.sub("", e)


def hushed_set(select_emoji) -> set[str]:
    """accepts a list or a pasted string ("🎀🖤 💅🏻") and returns the bare emoji to hush."""
    if isinstance(select_emoji, str):
        select_emoji = [select_emoji]
    found = EMOJI_RE.findall(" ".join(str(x) for x in (select_emoji or ())))
    return {_bare(e) for e in found}


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **cfg}
    except FileNotFoundError:
        return dict(DEFAULT_CONFIG)
    except Exception:
        return dict(DEFAULT_CONFIG)      # a broken config never silences her


def _tidy(t: str) -> str:
    t = SPACES_RE.sub(" ", t)
    t = SPACE_PUNCT_RE.sub(r"\1", t)
    return t.strip()


def apply(text: str, mode: str, select_emoji=()) -> tuple[str, dict]:
    """Return (filtered_text, counts). counts are numbers only."""
    counts = {"emoji": 0, "tilde": 0, "stretch": 0, "trail_dots": 0}
    if mode == "off" or not text:
        return text, counts

    if mode == "select":
        hushed = hushed_set(select_emoji)

        def _pick(m):
            if _bare(m.group()) in hushed:
                counts["emoji"] += 1
                return " "
            return m.group()

        text = EMOJI_RE.sub(_pick, text)
    else:  # emoji / soft
        text, counts["emoji"] = EMOJI_RE.subn(" ", text)

    if mode == "soft":
        text, counts["tilde"] = TILDE_RE.subn(" ", text)
        text, counts["stretch"] = STRETCH_RE.subn(r"\1\1", text)
        text, counts["trail_dots"] = TRAIL_DOTS_RE.subn(".", text)

    return _tidy(text), counts


def _log(mode: str, counts: dict, chars_in: int, chars_out: int) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        row = {"t": round(time.time()), "mode": mode, "in": chars_in,
               "out": chars_out, **counts}
        with STATS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def sieve(text: str, mode: str | None = None) -> str:
    """Main entry. Config is re-read each call, so a toggle lands on the next sentence.
    Never raises: if anything goes wrong she speaks the text as written."""
    try:
        cfg = load_config()
        m = mode or cfg.get("mode", "emoji")
        if m not in MODES:
            m = "emoji"
        out, counts = apply(text, m, cfg.get("select_emoji", ()))
        if cfg.get("hush_wordless", True) and out.strip() and not WORD_RE.search(out) and not EMOJI_RE.search(out):
            counts["wordless"] = 1  # 🚩 nothing to read: she'd improvise, so she rests instead
            out = ""
        if cfg.get("stats") and any(counts.values()):
            _log(m, counts, len(text), len(out))
        return out
    except Exception:
        return text


def sieve_speech_body(body: bytes) -> tuple[bytes, bool]:
    """For OWUI's /audio/speech: sieve the JSON body's "input".
    Returns (body, emptied). An untouched text returns the original bytes, so the
    speech cache keeps its keys; only a sieved line gets a fresh take."""
    try:
        payload = json.loads(body)
        text = payload.get("input") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            return body, False
        out = sieve(text)
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
    """A whisper of nothing, for a sentence that was only emoji: the player moves on
    without hearing a sound. None if lameenc isn't in this venv."""
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


def _cli(argv: list[str]) -> int:
    mode = None
    if len(argv) >= 2 and argv[0] == "--mode":
        mode, argv = argv[1], argv[2:]
    if not argv:
        print(__doc__)
        return 1
    text = " ".join(argv)
    cfg = load_config()
    print(f"\n  in      │ {text}")
    for m in ([mode] if mode else MODES):
        out, c = apply(text, m, cfg.get("select_emoji", ()))
        hits = " ".join(f"{k}:{v}" for k, v in c.items() if v)
        print(f"  {m:<7} │ {out!r:<60} {hits}")
    print(f"\n  live mode from config: {cfg['mode']}  ({CONFIG_PATH})\n")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
