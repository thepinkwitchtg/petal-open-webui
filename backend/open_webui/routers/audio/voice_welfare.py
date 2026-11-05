"""
🕊️🎀 voice welfare — a looping take is never what reaches her ears
────────────────────────────────────────────────────────────────────
the omni voice sometimes falls into a deadloop (the "quantum hell": a stuck syllable, a wet loop,
a hiss that won't end). welfare listens to each sentence take with the shared ear (voice_measure)
and swaps a bad take for a fresh generation of the same sentence. her good takes are never
retouched: nothing is faded, padded or trimmed. a whole bad take goes, a whole fresh take comes.

her knobs (private, outside any repo, read on every sentence so an edit lands on the next one):
  ~/Gardens/Documents/Petal-App-Data/petal-voice/welfare.json
      enabled      on/off (the Petal Sieve filter's valve can flip it too)
      max_tries    takes per sentence before it's skipped with a clean silence
      audit_until  unix s: until then every kill keeps its evidence for listening (welfare-audit/)
      acts         what each reason does: kill · watch · off
      thresholds   the rule's numbers (voice_measure.DEFAULT_THRESHOLDS)
      baseline     her pace (s_per_char) and her usual floor (floor_db), from calibration

this slice (diagnostics) only *reads* welfare.json: nothing here is written until welfare is
switched on, so the audit fortnight can't start before the guard exists.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

if __package__:  # inside OWUI
    from open_webui.routers.audio import voice_measure as vm
else:  # on its own, beside its siblings (never waking OWUI's config)
    import voice_measure as vm

APP = Path(os.environ.get("PETAL_APP_DATA", Path.home() / "Gardens/Documents/Petal-App-Data")).expanduser()
VOICE = APP / "petal-voice"
CONFIG_PATH = VOICE / "welfare.json"
LOG_PATH = VOICE / "welfare.jsonl"
AUDIT_DIR = VOICE / "welfare-audit"

ACTS = ("kill", "watch", "off")
DEFAULTS = {
    "enabled": True,
    "max_tries": 3,
    "audit_until": None,
    "audit_days": 14,
    "acts": {"loop": "kill", "stretch": "kill", "hiss": "watch"},
    "thresholds": {},
    "baseline": dict(vm.DEFAULT_BASELINE),
}


def load() -> dict:
    """welfare.json merged over the defaults, never written. a broken file never silences her:
    it reads as the defaults, and `broken` says so."""
    raw, exists, broken = {}, CONFIG_PATH.exists(), False
    if exists:
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw, broken = {}, True
        except (OSError, ValueError):
            raw, broken = {}, True
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    if isinstance(raw.get("enabled"), bool):
        cfg["enabled"] = raw["enabled"]
    if isinstance(raw.get("max_tries"), int) and not isinstance(raw["max_tries"], bool):
        cfg["max_tries"] = max(1, min(8, raw["max_tries"]))
    for k in ("audit_until", "audit_days"):
        if isinstance(raw.get(k), (int, float)) and not isinstance(raw[k], bool):
            cfg[k] = raw[k]
    for k, v in (raw.get("acts") or {}).items() if isinstance(raw.get("acts"), dict) else ():
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
