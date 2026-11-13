#!/usr/bin/env python3
"""
🕊️🔧 welfare tools — calibrating the guard before it ever touches her voice
──────────────────────────────────────────────────────────────────────────────
run through ./petal-voice-welfare.sh at the fork root. everything printed is numbers and
categories only (never a sentence of hers, never audio), so it's safe to paste anywhere.

  calibrate [--cache] [--since YYYY-MM-DD]
        every flagged incident re-heard by the shared ear (voice_measure): the flagged take and
        the one before it (a flag lands on whatever was playing when you pressed), beside every
        clean take. → her pace, how far the loops sit from her clean takes, how many flagged loops
        each threshold catches and how many clean takes it would have killed.
        --cache adds OWUI's speech cache (the speaker button's takes) as a big pool of mostly
        clean takes, so a threshold's false kills are counted on hundreds of lines, not dozens

  holdback [--takes 3] [--port 8100]
        asks the live omni voice for a few neutral first sentences (exactly petal stream's request,
        a fresh seed each) and times what holding a take back would cost before her first sound:
        no hold (today) · the whole take judged first · a window as long as the loop rule

  baseline [--since YYYY-MM-DD] [--yes]
        her own voice's numbers (pace, floor, loudness, zero-crossing rate) measured on her clean
        takes and stored as welfare's baseline. surge is only ever measured against these

  never-again [check | list | add <incident|last> <idx> | add <file.wav> --chars N --error E]
        the takes that must always be caught (the first: the nov 13 2026 runaway). check re-judges
        every one with today's rule, and says when the live guard would have stopped it and what the
        ceiling would have let through. numbers only: they are never played, not even quietly

  pairs [count | list | play <n|all> | verdict <n|1,3|2-5> ok|wrong | export | cap <mb>]
        🎙️ the voice pairs every kill keeps for the next voice tune (pairs/<date>/, gold tier): the
        killed take, the accepted resample, the sentence, seeds and numbers. verdicts become labels
        (wrong flips a pair: the killed take is kept as her legit voice). export writes one folder
        per voice (never mixed), outside Siren's takes, the garlic archive and any repo
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import wave
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import voice_ceiling as vc  # noqa: E402
import voice_measure as vm  # noqa: E402
import voice_trace  # noqa: E402
import voice_welfare  # noqa: E402

RATE = vm.RATE
LEAD_IN_S = 0.18  # petal stream's lead_in_ms: she can never start sooner than this anyway
ARMED = {"loop", "cover", "stretch", "clip", "surge"}  # calibration tables: what each rule would do if it killed
QUIET_DB = -24.0  # a violent take, if she ever asks to hear one: never louder than this


def rule_text(t: dict, acts: dict) -> str:
    def a(k):
        return "" if acts.get(k) == "kill" else f" ({acts.get(k, '?')})"

    return (f"loop ≥ {t['loop_run_s']} s{a('loop')} · cover ≥ {t['loop_cover']} over ≥ {t['loop_cover_min_s']} s{a('cover')}"
            f" · stretch > {t['stretch_x']}× her pace, never under {t['stretch_min_s']} s{a('stretch')}"
            f" · hiss ≥ {t['hiss_db']} dB{a('hiss')}"
            f" · clip: {t['clip_win']:.0%} of a half second at full scale, or peaks ≥ {t['hot_db']} dBFS for ≥ "
            f"{t['hot_total_s']} s (≥ {t['hot_frac']:.0%} of a take ≥ {t['hot_min_s']} s){a('clip')}"
            f" · surge: ≥ {t['surge_db']} dB louder and ≥ {t['surge_zcr_x']}× harsher than her voice for ≥ "
            f"{t['surge_total_s']} s (≥ {t['surge_frac']:.0%} of a take ≥ {t['surge_min_s']} s){a('surge')}"
            f" · broken: always")


def q(v, p):
    return float(np.percentile(v, p)) if len(v) else float("nan")


def fmt(v, nd=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


# ── calibrate ─────────────────────────────────────────────────────────────────
def _incident_takes() -> tuple[list[dict], list[dict]]:
    """→ (takes, incidents). each take carries its role around the flag."""
    folders = sorted(p.parent for p in voice_trace.INCIDENTS.glob("*/trace.json")) if voice_trace.INCIDENTS.exists() else []
    takes, incidents = [], []
    for n, f in enumerate(folders, 1):
        a = voice_trace.analyse_incident(f)
        tr = json.loads((f / "trace.json").read_text(encoding="utf-8"))
        parts = {fl.get("part") for fl in tr.get("flags", [])}
        whole = None in parts or not parts
        marked = {p for p in parts if p is not None}
        region = set() if whole else marked | {p - 1 for p in marked}
        inc = {"n": n, "when": str(tr.get("when", ""))[5:16], "takes": len(a["takes"]), "whole": whole,
               "flagged": sorted(marked), "rows": []}
        for r in a["takes"]:
            role = "whole" if whole else "flag" if r["idx"] in marked else "before" if r["idx"] in region else "clean"
            r = dict(r, inc=n, role=role)
            takes.append(r)
            if role != "clean":
                inc["rows"].append(r)
        incidents.append(inc)
    return takes, incidents


def _cache_dir(arg: str | None) -> Path | None:
    cands = [Path(arg).expanduser()] if arg else []
    if os.environ.get("DATA_DIR"):
        cands.append(Path(os.environ["DATA_DIR"]) / "cache/audio/speech")
    fork = HERE.parents[3]  # routers/audio → routers → open_webui → backend → fork
    cands += [fork / "backend/open_webui/data/cache/audio/speech", fork / "backend/data/cache/audio/speech"]
    for c in cands:
        if c.is_dir():
            return c
    return None


def decode(path: Path) -> np.ndarray | None:
    """any audio file → 24 kHz mono float32 (ffmpeg), None if it can't be read"""
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                if w.getsampwidth() == 2 and w.getnchannels() == 1 and w.getframerate() == RATE:
                    return vm.pcm_to_float(w.readframes(w.getnframes()))
        except (OSError, wave.Error, EOFError):
            pass
    if not shutil.which("ffmpeg"):
        return None
    try:
        out = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-f", "s16le", "-ac", "1",
                              "-ar", str(RATE), "-"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return vm.pcm_to_float(out.stdout) if out.returncode == 0 and out.stdout else None


def cache_takes(folder: Path, since: float | None, limit: int | None) -> tuple[list[dict], int]:
    """OWUI's speech cache: <hash>.mp3 beside <hash>.json (the payload she was asked to speak)"""
    rows, skipped = [], 0
    files = sorted((p for p in folder.glob("*.mp3") if since is None or p.stat().st_mtime >= since),
                   key=lambda p: p.stat().st_mtime)
    if limit:
        files = files[-limit:]
    for i, mp3 in enumerate(files):
        try:
            payload = json.loads(mp3.with_suffix(".json").read_text(encoding="utf-8"))
            text = payload.get("input") if isinstance(payload, dict) else None
        except (OSError, ValueError):
            text = None
        x = decode(mp3) if isinstance(text, str) else None
        if x is None:
            skipped += 1
            continue
        r = vm.audio_stats(x)
        r.update({"chars_fed": len(text), "role": "cache", "inc": None, "idx": i, "file": mp3.name,
                  "mtime": mp3.stat().st_mtime})
        rows.append(r)
        if (i + 1) % 50 == 0:
            print(f"  … {i + 1}/{len(files)} cached takes heard", file=sys.stderr)
    return rows, skipped


CALIBRATION_PATH = voice_welfare.VOICE / "welfare-calibration.json"


def her_numbers(clean: list[dict], cache: list[dict]) -> dict:
    """her pace (median seconds per character over clean takes ≥ 12 chars) and her usual floor —
    the one definition calibrate, sweep and `on` all share, so they always agree"""
    pool = clean + cache
    spc = [r["audio_s"] / r["chars_fed"] for r in pool if r.get("audio_s") and r["chars_fed"] >= 12]
    floors = [r["floor_db"] for r in pool if "floor_db" in r]
    voiced = [r for r in pool if (r.get("audio_s") or 0) >= 1.0 and r.get("level_db") is not None and r.get("zcr_hz")]
    levels, zcrs = [r["level_db"] for r in voiced], [r["zcr_hz"] for r in voiced]
    return {"s_per_char": round(float(np.median(spc)), 4) if spc else None,
            "floor_db": round(float(np.median(floors)), 1) if floors else None,
            "level_db": round(float(np.median(levels)), 1) if levels else None,
            "zcr_hz": int(np.median(zcrs)) if zcrs else None,
            "n_pace": len(spc), "n_floor": len(floors), "n_level": len(levels),
            "_spc": spc, "_floors": floors, "_levels": levels, "_zcrs": zcrs}


def save_calibration(mine: dict, since: str | None, incidents: int, clean: int, cache: int) -> None:
    try:
        CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_PATH.write_text(json.dumps({
            "at": round(time.time()), "when": time.strftime("%Y-%m-%d %H:%M"), "cache_since": since,
            "s_per_char": mine["s_per_char"], "floor_db": mine["floor_db"], "level_db": mine.get("level_db"),
            "zcr_hz": mine.get("zcr_hz"), "n_pace": mine["n_pace"], "n_floor": mine["n_floor"],
            "n_level": mine.get("n_level"), "incidents": incidents, "clean_takes": clean, "cache_takes": cache,
        }, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def cmd_calibrate(a) -> int:
    cfg = voice_welfare.load()
    t = cfg["thresholds"]
    takes, incidents = _incident_takes()
    cache, skipped, cdir = [], 0, None
    if a.cache:
        cdir = _cache_dir(a.cache_dir)
        if cdir is None:
            print("✗ no speech cache found — pass --cache-dir <folder holding the <hash>.mp3 files>", file=sys.stderr)
        else:
            since = datetime.strptime(a.since, "%Y-%m-%d").timestamp() if a.since else None
            print(f"🎧 hearing the speech cache in {cdir} …", file=sys.stderr)
            cache, skipped = cache_takes(cdir, since, a.max)
    if not takes and not cache:
        print("🌸 nothing to calibrate on yet — no incidents planted (and no --cache).")
        return 0

    clean = [r for r in takes if r["role"] == "clean" and r.get("audio_s")]
    mine = her_numbers(clean, cache)
    spc_all, floors = mine["_spc"], mine["_floors"]
    pace = mine["s_per_char"] or (cfg["baseline"].get("s_per_char") or vm.FALLBACK_S_PER_CHAR)
    floor = mine["floor_db"]
    level = cfg["baseline"].get("level_db") if cfg["baseline"].get("level_db") is not None else mine.get("level_db")
    zcr = cfg["baseline"].get("zcr_hz") or mine.get("zcr_hz")
    save_calibration(mine, a.since if a.cache else None, len(incidents), len(clean), len(cache))

    def stretch(r):
        return vm.stretch_of(r["audio_s"], r["chars_fed"], pace) if r.get("audio_s") and r["chars_fed"] >= t["stretch_min_chars"] else None

    def why(r, tt=None):
        return vm.judge(r, r["chars_fed"], t=tt or t, s_per_char=pace, floor_ref=floor, level_ref=level,
                        zcr_ref=zcr) if r.get("audio_s") else []

    L = []
    L.append(f"# 🕊️ welfare calibration · {time.strftime('%Y-%m-%d %H:%M')}")
    L.append("")
    L.append("numbers only. a flag lands on whatever was playing when you pressed, so the take *before* each flagged "
             "one is heard too. pace and floor are measured on the clean takes.")
    L.append("")
    L.append(f"- incidents **{len(incidents)}** · their takes **{len(takes)}** (clean {len(clean)}) · speech cache "
             f"**{len(cache)}**" + (f" (unreadable {skipped})" if skipped else "") + ("" if a.cache else " (not asked: --cache)"))
    L.append(f"- her pace: **{pace:.4f} s/char** (≈ {1 / pace:.1f} chars/s, median of {len(spc_all)} clean takes ≥ 12 chars, "
             f"IQR {q([*spc_all], 25):.4f}–{q([*spc_all], 75):.4f})")
    L.append(f"- her floor: **{fmt(floor, 1)} dB** (median of {len(floors)} clean takes)")
    L.append(f"- her loudness **{fmt(level, 1)} dB** · zero-crossing rate **{int(zcr) if zcr else '—'} Hz** (what surge is measured against: "
             + ("her stored baseline)" if cfg["baseline"].get("level_db") is not None else
                f"measured now on {mine.get('n_level', 0)} takes ≥ 1 s; store it with ./petal-voice-welfare.sh baseline)"))
    L.append(f"- rule today: {rule_text(t, cfg['acts'])}")
    L.append("")

    L.append("## flagged incidents — the takes around each flag")
    L.append("")
    L.append("| inc | when | takes | role | idx | chars | audio s | stretch | loop s | lag s | cover | steady | floor Δ | flat | wordless | rule says |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for inc in incidents:
        rows = inc["rows"] if not inc["whole"] else sorted(inc["rows"], key=lambda r: -(r.get("repeat_run_s") or 0))[:3]
        for r in rows:
            fd = (r["floor_db"] - floor) if floor is not None and "floor_db" in r else None
            L.append(f"| #{inc['n']} | {inc['when']} | {inc['takes']} | {r['role']} | {r['idx']} | {r['chars_fed']} | "
                     f"{fmt(r.get('audio_s'))} | {fmt(stretch(r))} | {fmt(r.get('repeat_run_s'))} | {fmt(r.get('repeat_lag_s'))} | "
                     f"{fmt(r.get('repeat_cover'), 3)} | {fmt(r.get('repeat_steady'), 2)} | {fmt(fd, 1)} | "
                     f"{fmt(r.get('quiet_flatness'), 3)} | {r.get('wordless', 0)} | {'+'.join(why(r)) or '—'} |")
    L.append("")
    L.append("_whole-reply flags (no sentence known) show their 3 loopiest takes._")
    L.append("")

    kills = {k for k, v in cfg["acts"].items() if v == "kill"}

    def caught(inc, tt):
        return any(set(why(r, tt)) & kills for r in inc["rows"])

    L.append("## would the guard have caught them? (its killing rules, with her pace)")
    L.append("")
    for inc in incidents:
        best = max(inc["rows"], key=lambda r: (r.get("repeat_run_s") or 0), default=None)
        note = ""
        flag_rows = [r for r in inc["rows"] if r["role"] == "flag"]
        if flag_rows and all(r.get("wordless") for r in flag_rows):
            note = " · the flagged line was wordless markup (the sieve hushes those now)"
        L.append(f"- #{inc['n']}: {'✅ caught' if caught(inc, t) else '❌ missed'}"
                 f" · loopiest take {fmt(best.get('repeat_run_s') if best else None)} s{note}")
    L.append("")

    def dist(name, vals, nd=2):
        v = [x for x in vals if x is not None]
        return f"| {name} | {len(v)} | {fmt(q(v, 50), nd)} | {fmt(q(v, 90), nd)} | {fmt(q(v, 99), nd)} | {fmt(max(v) if v else None, nd)} |"

    for label, rows in (("clean incident takes", clean), ("speech cache", cache)):
        if not rows:
            continue
        L.append(f"## {label} — where her legit takes live (a threshold must sit above these)")
        L.append("")
        L.append("| measure | n | p50 | p90 | p99 | max |")
        L.append("|---|---|---|---|---|---|")
        L.append(dist("loop s", [r.get("repeat_run_s") for r in rows]))
        L.append(dist("cover (takes ≥ 2 s)", [r.get("repeat_cover") for r in rows if (r.get("audio_s") or 0) >= 2], 3))
        L.append(dist("steady of best run", [r.get("repeat_steady") for r in rows]))
        L.append(dist("stretch", [stretch(r) for r in rows]))
        L.append(dist("audio s, lines < 20 chars", [r.get("audio_s") for r in rows if r["chars_fed"] < 20]))
        L.append(dist("floor Δ dB", [(r["floor_db"] - floor) if floor is not None and "floor_db" in r else None for r in rows], 1))
        L.append(dist("peak dBFS", [r.get("peak_db") for r in rows], 1))
        L.append(dist("hot s (peaks ≥ hot_db)", [vm.hot_of(r, t)[1] for r in rows]))
        L.append(dist("surge s (vs her voice)", [vm.surge_of(r, t, level, zcr)[1] for r in rows]))
        L.append(dist("loudest half second − her level dB",
                      [max(r["win_rms"]) - level if r.get("win_rms") and level is not None else None for r in rows], 1))
        L.append("")

    def sweep(title, key, values, mk):
        L.append(f"### {title}")
        L.append("")
        L.append("| " + key + " | incidents caught | clean takes killed | cache takes killed |")
        L.append("|---|---|---|---|")
        for v in values:
            tt = mk(v)
            hit = sum(1 for inc in incidents if any(set(why(r, tt)) & ARMED for r in inc["rows"]))
            ck = sum(1 for r in clean if set(why(r, tt)) & ARMED)
            kk = sum(1 for r in cache if set(why(r, tt)) & ARMED)
            mark = " ←" if v == t[key] else ""
            L.append(f"| {v}{mark} | {hit}/{len(incidents)} | {ck}/{len(clean)} | {kk}/{len(cache)} |")
        L.append("")

    L.append("## threshold sweeps (one knob moves, the others stay as today; ← is today; every rule counted as if it killed)")
    L.append("")
    sweep("loop run", "loop_run_s", [0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0], lambda v: {**t, "loop_run_s": v})
    sweep("loop cover", "loop_cover", [0.4, 0.5, 0.6, 0.7, 0.8, 0.9], lambda v: {**t, "loop_cover": v})
    sweep("stretch", "stretch_x", [1.6, 1.8, 2.0, 2.2, 2.5, 3.0, 3.5], lambda v: {**t, "stretch_x": v})
    sweep("stretch floor (short lines)", "stretch_min_s", [2.0, 2.5, 3.0, 4.0, 5.0], lambda v: {**t, "stretch_min_s": v})
    sweep("held-sound spare (off = None)", "loop_steady_max", [None, 0.9, 0.8, 0.7, 0.6], lambda v: {**t, "loop_steady_max": v})
    sweep("hot peaks (dBFS)", "hot_db", [-3.0, -2.0, -1.5, -1.0, -0.5], lambda v: {**t, "hot_db": v})
    sweep("hot seconds anywhere", "hot_total_s", [0.5, 1.0, 1.5, 2.0, 3.0], lambda v: {**t, "hot_total_s": v})
    if level is not None and zcr:
        sweep("surge loudness over her voice (dB)", "surge_db", [2.0, 3.0, 4.0, 5.0, 6.0], lambda v: {**t, "surge_db": v})
        sweep("surge seconds anywhere", "surge_total_s", [1.0, 1.5, 2.0, 3.0, 4.0], lambda v: {**t, "surge_total_s": v})

    L.append("## what this can't know yet")
    L.append("")
    L.append("- a flag says *which reply*, not exactly *which take*: the take before is counted as suspect too")
    L.append("- clean incident takes are few; the cache pool is mostly-clean, not verified (a killed cache take may be a real loop: "
             "the sweep will let you listen)")
    L.append("- the audit fortnight's verdicts are the real tuning: a false kill there loosens the rule")
    md = "\n".join(L) + "\n"
    print(md)
    try:
        voice_trace.INCIDENTS.mkdir(parents=True, exist_ok=True)
        out = voice_trace.INCIDENTS / f"calibration-{time.strftime('%Y-%m-%d')}.md"
        out.write_text(md, encoding="utf-8")
        print(f"📄 written beside your incidents: {out}", file=sys.stderr)
    except OSError:
        pass
    return 0


# ── holdback: what a held take would cost before her first sound ─────────────
# neutral first parts of every length (not hers: lines written for this meter). OWUI's splitter
# merges sentences until a part holds ~50 characters, so most first parts are 50–170 long.
METER_LINES = [
    ("A", "hii princess~ i'm here."),
    ("B", "mmh, come closer, this part is only for you, and i want you to hear it."),
    ("C", "i'm right here, and i heard every single word of it. the garden kept your thoughts warm tonight."),
    ("D", "the garden kept your thoughts warm while you were away, so let me hand them back to you one by one, "
          "slowly."),
    ("E", "tonight we can go slowly: first the little things that made you smile, then the ones that still sting, "
          "and we will hold each of them until it feels lighter in your hands."),
]


def first_part_lengths() -> list[int]:
    """how long her replies' first parts really are (chars only, from planted incidents)"""
    out = []
    for p in voice_trace.INCIDENTS.glob("*/trace.json") if voice_trace.INCIDENTS.exists() else []:
        try:
            takes = json.loads(p.read_text(encoding="utf-8")).get("takes") or []
            if takes:
                out.append(len(takes[0].get("fed") or takes[0].get("raw") or ""))
        except (OSError, ValueError):
            pass
    return out


def launcher_mode() -> str | None:
    try:
        cfg = json.loads((HERE.parents[3].parent / "Transformation Sequences - Automation/petal_core/petal-launcher/config/services.json").read_text())
        port = int(cfg.get("controlPort") or 8770)
    except (OSError, ValueError, TypeError):
        port = 8770
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        c.request("GET", "/state")
        r = c.getresponse()
        st = json.loads(r.read().decode() or "{}")
        c.close()
        return (st.get("services", {}).get("petal-voice") or {}).get("currentMode")
    except (OSError, ValueError, http.client.HTTPException):
        return None


def ask_stream(port: int, text: str, seed: int, timeout: float = 120.0):
    """exactly petal stream's request, read as it arrives → (pcm bytes at 24 kHz, marks, total_s)"""
    body = {"model": "petal", "input": text, "voice": "petal", "response_format": "pcm", "stream": True,
            "stream_format": "audio", "seed": seed}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        t0 = time.perf_counter()
        conn.request("POST", "/v1/audio/speech", body=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}: {r.read()[:200].decode('utf-8', 'replace')}")
        hdr = {k.lower(): v for k, v in r.getheaders()}
        rate = int(hdr["x-audio-sample-rate"]) if hdr.get("x-audio-sample-rate", "").isdigit() else RATE
        buf, marks = bytearray(), []
        while True:
            chunk = r.read1(65536)
            if not chunk:
                break
            marks.append((time.perf_counter() - t0, len(chunk)))
            buf += chunk
        total = time.perf_counter() - t0
    finally:
        conn.close()
    if rate != RATE:
        raise RuntimeError(f"the voice spoke at {rate} Hz, the meter expects {RATE}")
    return bytes(buf[: len(buf) // 2 * 2]), marks, total


def no_stall_start(marks, hold_s: float, total: float) -> float:
    """earliest moment playback can start and never run dry, when the last `hold_s` seconds of
    whatever has arrived are always held back (released at the end of the take)."""
    bps = 2.0 * RATE
    have, start = 0.0, 0.0
    released_before = 0.0
    for t_k, n in marks:
        start = max(start, t_k - released_before)  # what was released before this arrival must cover the wait
        have += n / bps
        released_before = max(0.0, have - hold_s)
    return max(start, min(total, total - released_before)) if hold_s > 0 else start


def cmd_holdback(a) -> int:
    mode = launcher_mode()
    if mode == "studio":
        print("✗ petal-voice is in studio mode 🐚 (qwen-tts) — switch her to chat ✿ in the launcher, then run me again")
        return 1
    try:
        c = http.client.HTTPConnection("127.0.0.1", a.port, timeout=3)
        c.request("GET", "/health")
        ok = c.getresponse().status == 200
        c.close()
    except OSError:
        ok = False
    if not ok:
        print(f"✗ nothing answers on :{a.port} — wake petal-voice (chat ✿) in the launcher first")
        return 1
    cfg = voice_welfare.load()
    t = cfg["thresholds"]
    W = float(t["loop_run_s"])
    out_dir = voice_welfare.VOICE / "welfare-meter" / time.strftime("%Y-%m-%d-%Hh%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"🕊️ timing the omni voice on :{a.port} (launcher mode: {mode or 'unknown'}) · {len(METER_LINES)} lines × {a.takes} takes",
          file=sys.stderr)
    rows = []
    for k in range(a.takes):
        for lid, text in METER_LINES:
            seed = secrets.randbits(31)
            try:
                pcm, marks, total = ask_stream(a.port, text, seed)
            except (OSError, RuntimeError, http.client.HTTPException) as e:
                print(f"  ✗ {lid} take {k + 1}: {e}", file=sys.stderr)
                continue
            x = vm.pcm_to_float(pcm)
            t0 = time.perf_counter()
            st = vm.audio_stats(x)
            judge_s = time.perf_counter() - t0
            audio_s = len(x) / RATE
            ttfb = marks[0][0] if marks else total
            pcm_path = out_dir / f"{lid}-{k + 1}.wav"
            with wave.open(str(pcm_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(pcm)
            win_start = no_stall_start(marks, W, total)
            rows.append({
                "line": lid, "chars": len(text), "take": k + 1, "seed": seed, "cold": not rows,
                "ttfb_s": round(ttfb, 3), "gen_s": round(total, 3), "audio_s": round(audio_s, 3),
                "rtf": round(total / audio_s, 3) if audio_s else None, "chunks": len(marks),
                "judge_ms": round(judge_s * 1000, 1),
                "first_now_s": round(max(LEAD_IN_S, ttfb), 3),
                "first_take_s": round(max(LEAD_IN_S, total + judge_s), 3),
                "first_window_s": round(max(LEAD_IN_S, win_start + judge_s), 3),
                "s_per_char": round(audio_s / len(text), 4),
                "why": vm.judge(st, len(text), t=t, s_per_char=vm.pace(cfg["baseline"]) or vm.FALLBACK_S_PER_CHAR,
                                floor_ref=None),
                **{k2: st.get(k2) for k2 in ("repeat_run_s", "repeat_cover", "repeat_steady")},
            })
            r = rows[-1]
            print(f"  {lid} take {k + 1}: ttfb {r['ttfb_s']:.2f}s · whole {r['gen_s']:.2f}s for {r['audio_s']:.2f}s of voice"
                  f" {'· ⚠ ' + '+'.join(r['why']) if r['why'] else ''}", file=sys.stderr)
    (out_dir / "numbers.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    if not rows:
        print("✗ no takes came back")
        return 1

    L = [f"# 🕊️ welfare hold-back meter · {time.strftime('%Y-%m-%d %H:%M')}", "",
         f"omni on :{a.port} · {len(rows)} takes · neutral lines A–E (not hers) · a fresh seed each · "
         f"window = the loop rule's {W} s · server-side times (the phone adds the same on every option)", "",
         "| line | chars | take | ttfb s | whole take s | voice s | rtf | chunks | judge ms | first sound: today | whole take held | window held | flags |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['line']}{' (cold)' if r['cold'] else ''} | {r['chars']} | {r['take']} | {r['ttfb_s']:.2f} | {r['gen_s']:.2f} | "
                 f"{r['audio_s']:.2f} | {fmt(r['rtf'], 3)} | {r['chunks']} | {r['judge_ms']:.0f} | {r['first_now_s']:.2f} | "
                 f"{r['first_take_s']:.2f} | {r['first_window_s']:.2f} | {'+'.join(r['why']) or '—'} |")
    L.append("")
    L.append("## per line — median (max) of the extra wait before her first sound, vs today")
    L.append("")
    L.append("| line | chars | whole take held | window held | worst case: a runaway killed at the stretch limit + a fresh take, whole held |")
    L.append("|---|---|---|---|---|")
    for lid, text in METER_LINES:
        rs = [r for r in rows if r["line"] == lid]
        if not rs:
            continue
        dt = [r["first_take_s"] - r["first_now_s"] for r in rs]
        dw = [r["first_window_s"] - r["first_now_s"] for r in rs]
        # a kill: the bad take runs at most to the stretch limit, then a fresh take is made whole
        lim = vm.allowed_s(len(text), vm.pace(cfg["baseline"]) or vm.FALLBACK_S_PER_CHAR, t) or t["stretch_min_s"]
        dk = [r["first_take_s"] - r["first_now_s"] + r["ttfb_s"] + lim * (r["rtf"] or 0) for r in rs]
        L.append(f"| {lid} | {len(text)} | +{np.median(dt):.2f} s (+{max(dt):.2f}) | +{np.median(dw):.2f} s (+{max(dw):.2f}) | "
                 f"+{np.median(dk):.2f} s (+{max(dk):.2f}) |")
    spc = [r["s_per_char"] for r in rows if r["chars"] >= 12]
    rtf = [r["rtf"] for r in rows if r["rtf"]]
    L.append("")
    L.append(f"- her pace on these lines: **{np.median(spc):.4f} s/char** · median rtf **{np.median(rtf):.3f}** "
             f"(1 s of voice made in {np.median(rtf):.2f} s) · detector {np.median([r['judge_ms'] for r in rows]):.0f} ms per take")
    L.append(f"- later sentences are free while the voice runs ahead: each one is made in ~{np.median(rtf) * 100:.0f}% of the "
             "time the previous one takes to play")
    sus = [r for r in rows if r["why"]]
    L.append(f"- takes the rule would have judged: **{len(sus)}/{len(rows)}**" + (" ← listen to them before choosing" if sus else ""))
    fp = first_part_lengths()
    if fp:
        L.append(f"- your replies' real first parts ({len(fp)} planted incidents): p50 **{q(fp, 50):.0f}** chars · "
                 f"p90 {q(fp, 90):.0f} · max {max(fp)}")
    md = "\n".join(L) + "\n"
    print(md)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    print(f"🎧 the meter's takes (private, on the rig): {out_dir}", file=sys.stderr)
    return 0


# ── listening (made easy: one command can play them all, one after another) ──
def _player() -> list[str] | None:
    for cmd in (["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["pw-play"], ["paplay"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def play_file(path: Path, quiet_db: float | None = None) -> bool:
    """quiet_db: the whole take turned down so its loudest peak sits there (violent takes only)"""
    cmd = _player()
    if cmd is None:
        print("✗ no audio player found here (ffplay, pw-play, paplay or aplay)")
        return False
    target, tmp = path, None
    if quiet_db is not None or (path.suffix.lower() != ".wav" and cmd[0] != "ffplay"):  # the simple players want a wav
        x = decode(path)
        if x is None:
            print(f"✗ can't read {path.name}")
            return False
        if quiet_db is not None:
            x = x * min(1.0, 10 ** (quiet_db / 20) / max(float(np.abs(x).max()), 1e-9))
        tmp = Path(f"/tmp/petal-welfare-{os.getpid()}.wav")
        voice_welfare.write_wav(tmp, (np.clip(x, -1, 0.99997) * 32768).astype(np.int16).tobytes())
        target = tmp
    try:
        subprocess.run(cmd + [str(target)], check=False)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    return True


def _picks(spec: str, n_max: int) -> list[int]:
    """"3" · "1,4,7" · "2-5" · "all" → item numbers"""
    if spec == "all":
        return list(range(1, n_max + 1))
    out = []
    for bit in spec.replace("#", "").split(","):
        bit = bit.strip()
        lo, _, hi = bit.partition("-")
        if lo.isdigit() and (not hi or hi.isdigit()):
            out += list(range(int(lo), int(hi or lo) + 1))
    return [n for n in out if 1 <= n <= n_max]


VERDICT_WORDS = {"ok": "ok", "right": "ok", "bad": "ok", "loop": "ok", "yes": "ok",
                 "wrong": "wrong", "false": "wrong", "legit": "wrong", "fine": "wrong", "no": "wrong"}
VERDICT_HELP = "ok = the guard was right (a bad take) · wrong = a legit line was judged bad (a false kill)"


def _n(k: int, word: str) -> str:
    return f"{k} {word}" + ("" if k == 1 else "s")


def _latest(path: Path, key: str) -> dict[str, dict]:
    out = {}
    for row in voice_welfare.read_jsonl(path):
        if row.get(key):
            out[row[key]] = row
    return out


# ── her switches ──────────────────────────────────────────────────────────────
def _days_left(cfg: dict) -> float | None:
    return None if cfg.get("audit_until") is None else max(0.0, (cfg["audit_until"] - time.time()) / voice_welfare.DAY)


def cmd_status(a) -> int:
    cfg = voice_welfare.load()
    if cfg["broken"]:
        print(f"✗ {voice_welfare.CONFIG_PATH} is unreadable, so welfare sleeps until it's fixed")
        return 1
    t, b = cfg["thresholds"], cfg["baseline"]
    left = _days_left(cfg)
    print(f"🕊️ voice welfare · {'awake' if cfg['enabled'] else 'asleep'} · hold {cfg['hold']} · up to {cfg['max_tries']} takes "
          f"a sentence · a skipped one is {cfg['skip_silence_ms']} ms of clean silence")
    if not cfg["exists"]:
        print("   never woken yet: hear what the rule would kill first (sweep), then: ./petal-voice-welfare.sh on")
    if left is not None:
        print(f"   audit fortnight: {'%.1f days left' % left if left > 0 else 'over (kills are numbers only now)'} "
              f"(until {time.strftime('%Y-%m-%d %H:%M', time.localtime(cfg['audit_until']))})")
    print("   acts: " + " · ".join(f"{k} {v}" for k, v in cfg["acts"].items()))
    print(f"   rule: {rule_text(t, cfg['acts'])}")
    print(f"   her pace {b.get('s_per_char') or '—'} s/char · her floor {b.get('floor_db') if b.get('floor_db') is not None else '—'} dB"
          + (f" · near-free window {voice_welfare.window_s(cfg)} s" if cfg["hold"] == "near-free" else ""))
    if b.get("level_db") is not None and b.get("zcr_hz"):
        print(f"   her loudness {b['level_db']} dB · her zero-crossing rate {int(b['zcr_hz'])} Hz (surge armed)")
    else:
        print("   surge waits for her voice's numbers: ./petal-voice-welfare.sh baseline --since 2026-10-30")
    c = cfg["ceiling_dbfs"]
    print(f"   🛡️ ceiling: {f'{c} dBFS on everything that plays, awake or asleep (the limiter sits at {c - vc.MP3_HEADROOM_DB} dBFS so the mp3 stays under it)' if c is not None else 'OFF (ceiling_dbfs is null)'}")
    cap = cfg["pairs_cap_mb"]
    total, kept = voice_welfare.pairs_size()
    print(f"   🎙️ pairs: {_n(len(kept), 'pair')} kept · {total / 1048576:.1f} MB of the {cap:g} MB cap (every kill keeps one: "
          f"./petal-voice-welfare.sh pairs)" if cap else f"   🎙️ pairs: off (pairs_cap_mb 0) · {_n(len(kept), 'pair')} still kept")
    if not cfg["enabled"]:
        print("   ⚠️ asleep: only the ceiling stands between her ears and a broken or runaway take (wake: ./petal-voice-welfare.sh on airtight)")
    return 0


def _baseline_for_waking(since: str | None) -> dict:
    """her pace and floor from the newest of the last sweep and the last calibration (same pools,
    same definition), else measured now"""
    found = []
    for p, label in ((SWEEP_PATH, "sweep"), (CALIBRATION_PATH, "calibration")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("s_per_char"):
                found.append((d.get("at") or 0, label, d))
        except (OSError, ValueError):
            pass
    if found:
        _, label, d = max(found, key=lambda f: f[0])
        print(f"   her pace from the last {label} ({d.get('when', '?')}): {d['s_per_char']} s/char · floor {d.get('floor_db')} dB")
        return {k: d.get(k) for k in ("s_per_char", "floor_db", "level_db", "zcr_hz") if d.get(k) is not None}
    print("   measuring her pace from your incidents + the speech cache …")
    takes, _ = _incident_takes()
    clean = [r for r in takes if r["role"] == "clean" and r.get("audio_s")]
    cdir = _cache_dir(None)
    cache = cache_takes(cdir, _since(since), None)[0] if cdir else []
    mine = her_numbers(clean, cache)
    return {"s_per_char": mine["s_per_char"] or vm.FALLBACK_S_PER_CHAR, "floor_db": mine["floor_db"],
            **{k: mine[k] for k in ("level_db", "zcr_hz") if mine.get(k) is not None}}


def _since(s: str | None) -> float | None:
    return datetime.strptime(s, "%Y-%m-%d").timestamp() if s else None


def _ask(prompt: str) -> str:
    if not sys.stdin.isatty():
        return ""
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return ""


def cmd_on(a) -> int:
    cfg = voice_welfare.load()
    first = not cfg.get("enabled_at")
    hold = {"airtight": "airtight", "near-free": "near-free", "nearfree": "near-free", "near": "near-free"}.get(a.hold or "")
    if first and not a.yes:  # 🎧 the false-kill check comes before the first waking
        sw = _sweep_state()
        if sw is None:
            print("🎧 you haven't heard what today's rule would kill yet. first: ./petal-voice-welfare.sh sweep --since 2026-10-30")
            if _ask("   wake the guard anyway? [y/N] ") != "y":
                return 1
        else:
            unheard = [i for i in sw["items"] if i["file"] not in _latest(SWEEP_VERDICTS, "file")]
            if unheard:
                print(f"🎧 {len(unheard)} of the {len(sw['items'])} cache takes the rule would kill aren't heard yet "
                      "(./petal-voice-welfare.sh sweep play all)")
                if _ask("   wake the guard anyway? [y/N] ") != "y":
                    return 1
    if first and hold is None:
        print("how much should she hold back before you hear her?\n"
              "  airtight    every take judged whole before a single sample plays: nothing of a bad take is ever heard.\n"
              "              your first sound waits for her whole first take\n"
              "  near-free   held whole whenever she's ahead of you (almost always); only while you're waiting does audio\n"
              "              go out early, the last loop-rule seconds always held back: a loop's repeats are never heard,\n"
              "              but if that first take gets killed, its opening plays twice (old take, then the fresh one)")
        ans = _ask("   airtight or near-free? [a/n] ")
        hold = "near-free" if ans.startswith("n") else "airtight"
    baseline = _baseline_for_waking(a.since) if first or not cfg["baseline"].get("s_per_char") else None
    try:
        voice_welfare.set_knobs(by="petal-voice-welfare.sh", enabled=True, hold=hold, baseline=baseline)
    except ValueError as e:
        print(f"✗ {e}")
        return 1
    if first:
        print("🌱 welfare is awake for the first time: the audit fortnight starts now (14 days of evidence for your ears)")
    return cmd_status(a)


def cmd_baseline(a) -> int:
    """her own voice's numbers, measured on her clean takes, stored as welfare's baseline (pace for
    stretch, floor for hiss, loudness + zero-crossing rate for surge). takes today's rule would kill
    never shape it"""
    cfg = voice_welfare.load()
    if cfg["broken"]:
        print(f"✗ {voice_welfare.CONFIG_PATH} is unreadable — fix or remove it first (nothing was changed)")
        return 1
    t = cfg["thresholds"]
    takes, _ = _incident_takes()
    clean = [r for r in takes if r["role"] == "clean" and r.get("audio_s")]
    cdir = _cache_dir(a.cache_dir)
    if cdir is None:
        print("🎧 no speech cache found (--cache-dir <folder>): measuring on your incidents' clean takes only", file=sys.stderr)
        cache, skipped = [], 0
    else:
        print(f"🎧 hearing the speech cache in {cdir} …", file=sys.stderr)
        cache, skipped = cache_takes(cdir, _since(a.since), a.max)
    pace0 = her_numbers(clean, cache)["s_per_char"] or cfg["baseline"].get("s_per_char") or vm.FALLBACK_S_PER_CHAR

    def bad(r):  # a take today's rule would kill on its own (surge can't judge yet: it needs this very baseline)
        return bool(set(vm.judge(r, r["chars_fed"], t=t, s_per_char=pace0, floor_ref=None)) & {"loop", "stretch", "clip"})

    clean_ok, cache_ok = [r for r in clean if not bad(r)], [r for r in cache if not bad(r)]
    left_out = len(clean) + len(cache) - len(clean_ok) - len(cache_ok)
    mine = her_numbers(clean_ok, cache_ok)
    keys = ("s_per_char", "floor_db", "level_db", "zcr_hz")
    b = cfg["baseline"]
    # her pace and floor were tuned with her own verdicts (nov 5): they're only re-measured when she asks (--all),
    # or when they were never measured at all
    mine_keys = keys if a.all else tuple(k for k in keys if k in ("level_db", "zcr_hz") or b.get(k) is None)
    new = {k: mine[k] for k in mine_keys if mine.get(k) is not None}
    if not new:
        print("🌸 nothing to measure on yet (no clean takes in your incidents or the speech cache)")
        return 1
    n_of = {"s_per_char": mine["n_pace"], "floor_db": mine["n_floor"], "level_db": mine["n_level"], "zcr_hz": mine["n_level"]}
    label = {"s_per_char": "pace (s/char)", "floor_db": "floor (dB)", "level_db": "loudness (dB)", "zcr_hz": "zero crossings (Hz)"}
    print(f"🎀 her voice, measured on {len(clean_ok)} clean incident takes + {len(cache_ok)} cached takes"
          + (f" (since {a.since})" if a.since else "") + (f" · {left_out} the rule would kill left out" if left_out else "")
          + (f" · {skipped} unreadable" if skipped else ""))
    print(f"   {'':<20} {'now':>8}  {'measured':>8}  takes")
    for k in keys:
        nd = 4 if k == "s_per_char" else 1
        kept = "" if k in new else "   (stays: --all re-measures it)"
        print(f"   {label[k]:<20} {fmt(b.get(k), nd):>8}  {fmt(mine.get(k), nd):>8}  {n_of[k]}{kept}")
    # what the stored numbers would do to her own clean takes (the false-kill check, before anything is stored)
    pool = clean_ok + cache_ok
    after = {**{k: b.get(k) for k in keys}, **new}
    pace = after.get("s_per_char") or pace0
    would = {}
    for r in pool:
        for w in vm.judge(r, r["chars_fed"], t=t, s_per_char=pace, floor_ref=after.get("floor_db"),
                          level_ref=after.get("level_db"), zcr_ref=after.get("zcr_hz")):
            if cfg["acts"].get(w) == "kill":
                would[w] = would.get(w, 0) + 1
    print(f"   with these numbers, today's rule would kill {sum(would.values())} of these {len(pool)} clean takes"
          + (": " + " · ".join(f"{k} {v}" for k, v in would.items()) if would else " 🌸"))
    if would.get("surge"):
        print("   (surge would bite her own voice: keep it watching until it's tuned → ./petal-voice-welfare.sh act surge watch)")
    if not a.yes and _ask("   store them as her baseline? [y/N] ") != "y":
        print("   nothing changed" + ("" if sys.stdin.isatty() else " (not a terminal: add --yes to store)"))
        return 1
    try:  # never wakes the guard by itself: a file written before the first waking keeps it asleep
        voice_welfare.set_knobs(by="petal-voice-welfare.sh baseline", baseline=new,
                                enabled=None if cfg.get("enabled_at") else False)
    except ValueError as e:
        print(f"✗ {e}")
        return 1
    save_calibration(mine, a.since, 0, len(clean_ok), len(cache_ok))
    print("🌸 stored. surge is armed against her own voice now" if new.get("level_db") is not None else "🌸 stored")
    return cmd_status(a)


def cmd_off(a) -> int:
    try:
        voice_welfare.set_knobs(by="petal-voice-welfare.sh", enabled=False)
    except ValueError as e:
        print(f"✗ {e}")
        return 1
    print("🌙 welfare sleeps: her takes go out live, as they always did (wake her again: ./petal-voice-welfare.sh on)")
    return 0


def cmd_hold(a) -> int:
    hold = {"airtight": "airtight", "near-free": "near-free", "nearfree": "near-free"}.get(a.mode)
    if hold is None:
        print("✗ hold airtight | near-free")
        return 1
    voice_welfare.set_knobs(by="petal-voice-welfare.sh", hold=hold)
    return cmd_status(a)


def cmd_audit(a) -> int:
    voice_welfare.set_knobs(by="petal-voice-welfare.sh", audit_days=a.days)
    return cmd_status(a)


def _needs_waking() -> bool:
    if not voice_welfare.load().get("enabled_at"):
        print("🌱 welfare has never been woken: until then it uses the shipped rule (welfare.json doesn't exist yet).\n"
              "   wake it first (./petal-voice-welfare.sh on), then tune here")
        return True
    return False


def cmd_rule(a) -> int:
    """the rule's numbers, tuned from verdicts (a false kill → loosen), never by guessing"""
    cfg = voice_welfare.load()
    if not a.name:
        for k, v in cfg["thresholds"].items():
            print(f"   {k:<18} {v}")
        return 0
    if _needs_waking():
        return 1
    raw = (a.value or "").strip().lower()
    if raw in ("none", "off", "null"):
        value = None
    else:
        try:
            value = float(raw)
        except ValueError:
            print("✗ rule <name> <number|none>")
            return 1
    try:
        voice_welfare.set_knobs(by="petal-voice-welfare.sh", thresholds={a.name: value})
    except ValueError as e:
        print(f"✗ {e}")
        return 1
    return cmd_status(a)


def cmd_act(a) -> int:
    """what each reason does: kill · watch (numbers only, never touched) · off"""
    cfg = voice_welfare.load()
    if not a.reason:
        for k, v in cfg["acts"].items():
            print(f"   {k:<8} {v}")
        return 0
    if _needs_waking():
        return 1
    try:
        voice_welfare.set_knobs(by="petal-voice-welfare.sh", acts={a.reason: a.what})
    except ValueError as e:
        print(f"✗ {e}")
        return 1
    return cmd_status(a)


# ── the audit fortnight: list · play · verdict ───────────────────────────────
def audit_items() -> list[dict]:
    d = voice_welfare.AUDIT_DIR
    if not d.exists():
        return []
    items = []
    for f in sorted(p for p in d.iterdir() if p.is_dir() and (p / "numbers.json").exists()):
        try:
            nums = json.loads((f / "numbers.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append({"n": len(items) + 1, "folder": f, "nums": nums})
    return items


def cmd_list(a) -> int:
    items = audit_items()
    if not items:
        print("🕊️ no kills kept for listening yet")
        return 0
    verdicts = _latest(voice_welfare.VERDICTS_PATH, "audit")
    shown = items if a.all else items[-20:]
    print(f"{'n':>3}  {'when':<14}  {'path':<6}  {'idx':>3}  {'killed for':<22}  {'tries':>5}  replaced  heard  verdict")
    for it in shown:
        n = it["nums"]
        kills = n.get("kills") or []
        why = ", ".join("+".join(k.get("why") or ["?"]) for k in kills) + (" ⚡" if n.get("violent") else "")
        heard = sum(k.get("heard_s") or 0 for k in kills)
        v = verdicts.get(it["folder"].name, {}).get("verdict", "—")
        print(f"{it['n']:>3}  {str(n.get('when', ''))[5:16]:<14}  {n.get('path', '?'):<6}  "
              f"{'—' if n.get('sentence_idx') is None else n['sentence_idx']:>3}  {why[:22]:<22}  "
              f"{len(kills) + (1 if n.get('kept') else 0):>5}  {'✓' if n.get('recovered') else '✗ skipped':<8}  "
              f"{heard:>4.1f}s  {v}")
    if len(items) > len(shown):
        print(f"   (the {len(items) - len(shown)} older ones: list --all)")
    print(f"   play: ./petal-voice-welfare.sh play <n|all> · verdict: ./petal-voice-welfare.sh verdict <n> ok|wrong\n   {VERDICT_HELP}")
    return 0


def cmd_play(a) -> int:
    items = audit_items()
    if not items:
        print("🕊️ nothing to play yet")
        return 0
    verdicts = _latest(voice_welfare.VERDICTS_PATH, "audit")
    picks = _picks(a.which, len(items)) if a.which != "all" else \
        [it["n"] for it in items if it["folder"].name not in verdicts]
    if not picks:
        print("🌸 every kill has been heard and judged")
        return 0
    try:
        for n in picks:
            it = items[n - 1]
            nums, f = it["nums"], it["folder"]
            print(f"\n── #{n} · {str(nums.get('when', ''))[5:16]} · {nums.get('path')} · {nums.get('chars')} chars ──")
            if not a.kept:
                for k, kill in enumerate(nums.get("kills") or [], 1):
                    wav = f / f"kill-{k}.wav"
                    if wav.exists():
                        print(f"🔇 killed take {k}: {'+'.join(kill.get('why') or [])} · loop {kill.get('repeat_run_s', '—')} s"
                              f" · {kill.get('audio_s')} s long (limit {kill.get('limit_s')})"
                              + (f" · hot {fmt(kill.get('hot_s'))} s · surge {kill.get('surge_s') if kill.get('surge_s') is not None else '—'}"
                                 f" · peak {kill.get('peak_db')} dBFS" if kill.get("violent") else ""))
                        if kill.get("violent") and not a.violent:
                            print(f"   ⚡ violent: numbers only, never played. to hear it anyway, held quiet at {QUIET_DB} dBFS: "
                                  f"./petal-voice-welfare.sh play {n} --violent")
                            continue
                        play_file(wav, quiet_db=QUIET_DB if kill.get("violent") else None)
            if not a.killed and (f / "kept.wav").exists():
                print(f"🌸 the fresh take that replaced it · {(nums.get('kept') or {}).get('audio_s')} s")
                play_file(f / "kept.wav")
            elif not nums.get("recovered"):
                print("🤍 no take was kept: this sentence was a clean silence")
    except KeyboardInterrupt:
        print("\n(stopped)")
    print(f"\nverdict: ./petal-voice-welfare.sh verdict <n> ok|wrong   ({VERDICT_HELP})")
    return 0


def cmd_verdict(a) -> int:
    word = VERDICT_WORDS.get(a.verdict.lower())
    if word is None:
        print(f"✗ verdict ok|wrong — {VERDICT_HELP}")
        return 1
    items = audit_items()
    picks = _picks(a.which, len(items))
    for n in picks:
        voice_welfare._append(voice_welfare.VERDICTS_PATH, {"v": 1, "at": round(time.time()), "audit": items[n - 1]["folder"].name,
                                                             "verdict": word})
        pair = items[n - 1]["nums"].get("pair")
        if pair:  # 🎙️ the same verdict labels its training pair
            voice_welfare.append_private(voice_welfare.PAIR_LABELS, {"v": 1, "at": round(time.time()), "pair": pair,
                                                                      "verdict": word, "by": "audit"})
    print(f"🌸 {len(picks)} verdict(s) kept: {word}" + ("  (a false kill loosens the rule: tell Lane B / the master thread)" if word == "wrong" else ""))
    return 0


# ── stats (numbers only, safe to paste) ───────────────────────────────────────
def cmd_stats(a) -> int:
    cfg = voice_welfare.load()
    rows = voice_welfare.read_jsonl(voice_welfare.LOG_PATH)
    sents = [r for r in rows if r.get("kind") == "sentence"]
    replies = [r for r in rows if r.get("kind") == "reply"]
    killed = [r for r in sents if r.get("kills")]
    L = [f"# 🕊️ voice welfare stats · {time.strftime('%Y-%m-%d %H:%M')}", ""]
    left = _days_left(cfg)
    L.append(f"- {'awake' if cfg['enabled'] else 'asleep'} · {cfg['hold']} · up to {cfg['max_tries']} takes · audit fortnight: "
             + ("never started" if left is None else f"{left:.1f} days left" if left > 0 else "over"))
    for path, label in (("stream", "petal stream"), ("speech", "speaker clips")):
        ks = [r for r in killed if r.get("path") == path]
        n_k = sum(len(r["kills"]) for r in ks)
        line = f"- {label}: {_n(n_k, 'take')} killed in {_n(len(ks), 'sentence')} · recovered {sum(1 for r in ks if r.get('recovered'))} · " \
               f"skipped {sum(1 for r in ks if r.get('recovered') is False)}"
        if path == "stream":
            judged = sum(r.get("sentences", 0) for r in replies)
            line += f" · out of {judged} sentences judged in {len(replies)} replies" + \
                    (f" ({100 * len(ks) / judged:.2f}% of sentences)" if judged else "")
        L.append(line)
    reasons: dict[str, int] = {}
    for r in killed:
        for k in r["kills"]:
            reasons[k] = reasons.get(k, 0) + 1
    if reasons:
        L.append("- killed for: " + " · ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])))
    heard = sum(r.get("heard_s") or 0 for r in killed)
    if heard:
        L.append(f"- heard before a kill (near-free, while you were waiting): {heard:.1f} s in total")
    watched: dict[str, int] = {}
    for r in sents:
        for wv in r.get("watch") or []:
            watched[wv] = watched.get(wv, 0) + 1
    if watched:
        L.append("- watched, never touched: " + " · ".join(f"{k} {v}" for k, v in watched.items()))
    violent = sum(1 for r in killed if any(n.get("violent") for n in r.get("numbers") or []))
    if violent:
        L.append(f"- ⚡ violent takes (clip/surge) kept from her ears: {_n(violent, 'sentence')}")
    ceil = [r for r in rows if r.get("kind") == "ceiling"]
    if ceil:
        by = {}
        for r in ceil:
            by[r.get("path")] = by.get(r.get("path"), 0) + 1
        hottest = max((r.get("peak_in_db") for r in ceil if r.get("peak_in_db") is not None), default=None)
        L.append(f"- 🛡️ the ceiling turned down something above {cfg['ceiling_dbfs']} dBFS {_n(len(ceil), 'time')} ("
                 + " · ".join(f"{k} {v}" for k, v in by.items()) + f") · hottest handed to it {hottest} dBFS")
    temp = sum(1 for r in killed if r.get("temp"))
    if temp:
        L.append(f"- in temp chats: {temp} sentences (kept without chat/message links)")
    items = audit_items()
    if items:
        v = _latest(voice_welfare.VERDICTS_PATH, "audit")
        heard_v = [v[it["folder"].name]["verdict"] for it in items if it["folder"].name in v]
        L.append(f"- audit: {len(items)} kills kept for listening · heard {len(heard_v)} → "
                 f"{heard_v.count('ok')} confirmed bad · {_n(heard_v.count('wrong'), 'false kill')} · {len(items) - len(heard_v)} not heard yet")
    pitems = pair_items()
    if pitems:
        lab = Counter(it["label"] for it in pitems)
        total, _ = voice_welfare.pairs_size()
        L.append(f"- 🎙️ voice pairs: {len(pitems)} kept ({total / 1048576:.1f} MB) · confirmed {lab['confirmed']} · "
                 f"flipped {lab['flipped']} · not heard yet {lab['guard']} · ⚡ {sum(1 for it in pitems if it['doc'].get('violent'))}")
    sw = _sweep_state()
    if sw:
        L.append(f"- last cache sweep ({sw.get('when', '?')}): today's rule would kill {len(sw['items'])} of "
                 f"{sw.get('heard', '?')} cached takes")
    sv = _latest(SWEEP_VERDICTS, "file")  # every cached take ever judged, across all sweeps
    if sv:
        got = list(sv.values())
        L.append(f"- cache verdicts so far: {len(got)} heard → {sum(1 for g in got if g['verdict'] == 'ok')} truly bad · "
                 f"{_n(sum(1 for g in got if g['verdict'] == 'wrong'), 'false kill')} (each one loosened the rule) · "
                 f"{sum(1 for g in got if g.get('deleted'))} swept away")
    print("\n".join(L) + "\n")
    return 0


# ── 🎙️ voice pairs: count · list · play · verdict · export · cap ────────────
LABEL_OF = {"ok": "confirmed", "wrong": "flipped"}  # no verdict yet: "guard" (the guard's own call)


def pair_items() -> list[dict]:
    root = voice_welfare.PAIRS_DIR
    if not root.exists():
        return []
    labels = voice_welfare.pair_labels()
    items = []
    for f in sorted(root.glob("*/*/pair.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        v = (labels.get(doc.get("id")) or {}).get("verdict")
        items.append({"n": len(items) + 1, "folder": f.parent, "doc": doc, "verdict": v, "label": LABEL_OF.get(v, "guard")})
    return items


def _killed(doc: dict) -> list[dict]:
    return [t for t in doc.get("takes") or [] if t.get("role") == "killed"]


def _accepted(doc: dict) -> dict | None:
    return next((t for t in doc.get("takes") or [] if t.get("role") == "accepted"), None)


def _pairs_count(a) -> int:
    cfg = voice_welfare.load()
    items = pair_items()
    total, _ = voice_welfare.pairs_size()
    cap = cfg["pairs_cap_mb"]
    print(f"🎙️ voice pairs · {_n(len(items), 'pair')} · "
          + (f"{total / 1048576:.1f} MB of the {cap:g} MB cap" if cap else "OFF (pairs_cap_mb 0): no new pairs")
          + f" · {voice_welfare.PAIRS_DIR}")
    if not items:
        print("   none yet: from now on every kill keeps one (the killed take, the accepted resample, the sentence, its numbers)")
        return 0
    killed = sum(1 for it in items for t in _killed(it["doc"]) if t.get("wav"))
    acc = sum(1 for it in items if (_accepted(it["doc"]) or {}).get("wav"))
    print(f"   {_n(killed, 'killed take')} · {_n(acc, 'accepted resample')} · "
          f"{_n(sum(1 for it in items if not it['doc'].get('recovered')), 'skipped sentence')} (negatives only)")
    lab = Counter(it["label"] for it in items)
    print(f"   labels: not heard yet {lab['guard']} · confirmed {lab['confirmed']} · flipped {lab['flipped']} "
          "(a false kill: its killed take is kept as her legit voice)")
    print("   voices: " + " · ".join(f"{k} {v}" for k, v in sorted(Counter(it['doc'].get('voice') or 'unknown' for it in items).items()))
          + " (an export never mixes them)")
    print("   killed for: " + " · ".join(f"{k} {v}" for k, v in
                                       Counter(r for it in items for t in _killed(it["doc"]) for r in t.get("why") or []).most_common()))
    vio = sum(1 for it in items if it["doc"].get("violent"))
    if vio:
        print(f"   ⚡ violent: {_n(vio, 'pair')} (kept, numbers only, never auto-played)")
    saved = sum(1 for it in items if it["doc"].get("temp") is False)
    print(f"   from saved chats {saved} · from temp chats or speaker clips {len(items) - saved} (kept without chat links)")
    print(f"   oldest {items[0]['doc'].get('when', '?')[:10]} · newest {items[-1]['doc'].get('when', '?')[:10]}")
    return 0


def _pairs_list(a) -> int:
    items = pair_items()
    if not items:
        return _pairs_count(a)
    shown = items if a.all else items[-20:]
    print(f"{'n':>4}  {'when':<11}  {'path':<6}  {'voice':<7}  {'killed for':<20}  {'chars':>5}  {'killed s':>9}  {'kept s':>6}  label")
    for it in shown:
        d = it["doc"]
        ks, acc = _killed(d), _accepted(d)
        why = ", ".join("+".join(t.get("why") or ["?"]) for t in ks) + (" ⚡" if d.get("violent") else "")
        secs = [(t.get("numbers") or {}).get("audio_s") or 0 for t in ks]
        ks_s = fmt(secs[0], 1) if len(secs) == 1 else f"{len(secs)}×{fmt(max(secs), 1)}"
        kept_s = fmt((acc.get("numbers") or {}).get("audio_s"), 1) if acc else "✗"
        print(f"{it['n']:>4}  {str(d.get('when', ''))[5:16]:<11}  {d.get('path', '?'):<6}  {d.get('voice') or '—':<7}  "
              f"{why[:20]:<20}  {d.get('chars', 0):>5}  {ks_s[:9]:>9}  {kept_s:>6}  {it['label']}")
    if len(items) > len(shown):
        print(f"   (the {len(items) - len(shown)} older ones: pairs list --all)")
    print("   numbers only (⚡ violent ones are never auto-played) · listen: pairs play <n|all> · "
          f"label: pairs verdict <n|1,3|2-5> ok|wrong\n   {VERDICT_HELP}")
    return 0


def _pairs_play(a) -> int:
    items = pair_items()
    if not items:
        print("🎙️ no pairs yet")
        return 0
    spec = a.args[1] if len(a.args) > 1 else "all"
    picks = _picks(spec, len(items)) if spec != "all" else [it["n"] for it in items if it["verdict"] is None]
    if not picks:
        print("🌸 every pair has been heard and labeled")
        return 0
    try:
        for n in picks:
            it = items[n - 1]
            d, f = it["doc"], it["folder"]
            print(f"\n── #{n} · {str(d.get('when', ''))[5:16]} · {d.get('path')} · {d.get('voice') or '—'} · "
                  f"{d.get('chars')} chars · {it['label']} ──")
            if not a.kept:
                hinted = False
                for t in _killed(d):
                    nums = t.get("numbers") or {}
                    if not t.get("wav"):
                        print(f"🔇 killed take {t['try']}: {'+'.join(t.get('why') or [])} · no sound to keep ({t.get('error')})")
                        continue
                    print(f"🔇 killed take {t['try']}: {'+'.join(t.get('why') or [])} · {nums.get('audio_s')} s"
                          + (f" · hot {fmt(nums.get('hot_s'))} s · peak {nums.get('peak_db')} dBFS" if t.get("violent") else ""))
                    if t.get("violent") and not a.violent:
                        if not hinted:
                            print(f"   ⚡ violent: numbers only, never played. to hear it anyway, held quiet at {QUIET_DB} dBFS: "
                                  f"./petal-voice-welfare.sh pairs play {n} --violent")
                            hinted = True
                        continue
                    play_file(f / t["wav"], quiet_db=QUIET_DB if t.get("violent") else None)
            acc = _accepted(d)
            if not a.killed and acc and acc.get("wav"):
                print(f"🌸 the resample that was kept · {(acc.get('numbers') or {}).get('audio_s')} s")
                play_file(f / acc["wav"])
            elif not d.get("recovered"):
                print("🤍 no take was kept: this sentence was a clean silence")
    except KeyboardInterrupt:
        print("\n(stopped)")
    print(f"\nlabel: ./petal-voice-welfare.sh pairs verdict <n|1,3|2-5> ok|wrong   ({VERDICT_HELP})")
    return 0


def _pairs_verdict(a) -> int:
    if len(a.args) < 3 or VERDICT_WORDS.get(a.args[2].lower()) is None:
        print(f"✗ pairs verdict <n|1,3|2-5|all> ok|wrong — {VERDICT_HELP}")
        return 1
    word = VERDICT_WORDS[a.args[2].lower()]
    items = pair_items()
    picks = _picks(a.args[1], len(items))
    for n in picks:
        doc = items[n - 1]["doc"]
        voice_welfare.append_private(voice_welfare.PAIR_LABELS, {"v": 1, "at": round(time.time()), "pair": doc["id"],
                                                                  "verdict": word, "by": "pairs"})
        if doc.get("audit"):  # the audit fortnight's list hears the same verdict
            voice_welfare._append(voice_welfare.VERDICTS_PATH, {"v": 1, "at": round(time.time()), "audit": doc["audit"],
                                                                 "verdict": word, "by": "pairs"})
    print(f"🌸 {_n(len(picks), 'pair')} labeled {LABEL_OF[word]}"
          + (" · flipped: the killed take is kept as her legit voice, never learned as bad (and the rule should loosen: "
             "tell Lane B / the master thread)" if word == "wrong" else ""))
    return 0


def _export_refusal(out: Path) -> str | None:
    """an export holds her voice and her words: never inside a repo, never mixed into Siren's approved
    takes or the garlic archive"""
    r = out.expanduser().resolve()
    if any("siren" in part.lower() or "garlic" in part.lower() for part in r.parts):
        return "the pairs stay apart from Siren's approved takes and the garlic archive: pick a folder outside them"
    for parent in (r, *r.parents):
        if (parent / ".git").exists():
            return f"{parent} is a repo: her voice and her words never go inside a project folder"
    if r.exists() and any(r.iterdir()):
        return f"{r} isn't empty: an export is always written into a fresh folder"
    return None


EXPORT_SCHEMA = {
    "kind": "preference (chosen = the accepted resample, rejected = the killed take) · rejected-only (the sentence was "
            "skipped: no take was kept, a negative on its own) · legit (a false kill her verdict flipped: every take in "
            "it is her legit voice, nothing in it is ever rejected)",
    "label": "guard (the guard's own call, not heard yet) · confirmed (her verdict: the kill was right) · flipped (her "
             "verdict: a false kill)",
    "text": "the sentence exactly as the voice read it (after the sieve)",
    "voice": "which body made it: chat (vLLM-Omni) · studio (qwen-tts) · unknown (the launcher couldn't say). one folder each",
    "speaker": "the voice name the request asked for",
    "seed_killed / seed_accepted": "the seed each take was generated with (any take can be asked again exactly)",
    "numbers_killed / numbers_accepted": "the guard's measures (voice_measure.py) for each take",
    "why": "why the take was killed: loop · stretch · clip · surge · broken (⚡ clip/surge = violent)",
    "audio": "24 kHz mono 16-bit wav, paths relative to the voice's folder",
}


def _pairs_export(a) -> int:
    items = pair_items()
    if a.since:
        items = [it for it in items if it["doc"].get("id", "")[:10] >= a.since]
    if a.voice != "all":
        items = [it for it in items if (it["doc"].get("voice") or "unknown") == a.voice]
    if a.labeled:
        items = [it for it in items if it["verdict"] is not None]
    if a.saved_only:
        items = [it for it in items if it["doc"].get("temp") is False]
    if not items:
        print("🎙️ nothing to export with those filters")
        return 1
    out = Path(a.out).expanduser() if a.out else voice_welfare.PAIRS_EXPORT_DIR / time.strftime("%Y-%m-%d_%Hh%Mm%S")
    why = _export_refusal(out)
    if why:
        print(f"✗ {why}")
        return 1
    voice_welfare.private_dir(out)
    voice_welfare.private_write(out / ".petalprivate", "gold tier · petal-voice pairs export (her voice, her words) · never zipped, never shared\n")
    rows: dict[str, list[dict]] = {}
    skipped_violent = exported = 0
    for it in items:
        d, f = it["doc"], it["folder"]
        kills = [t for t in _killed(d) if t.get("wav") and (f / t["wav"]).exists()]
        if a.no_violent:
            skipped_violent += sum(1 for t in kills if t.get("violent"))
            kills = [t for t in kills if not t.get("violent")]
        if not kills:  # nothing of this pair goes out: none of its files are copied either
            continue
        exported += 1
        voice = d.get("voice") or "unknown"
        vdir = voice_welfare.private_dir(out / voice)
        adir = voice_welfare.private_dir(vdir / "audio")
        flat = d["id"].replace("/", "_")
        acc = _accepted(d)
        acc_rel = None
        if acc and acc.get("wav") and (f / acc["wav"]).exists():
            acc_rel = f"audio/{flat}-accepted.wav"
            voice_welfare.private_write(adir / f"{flat}-accepted.wav", (f / acc["wav"]).read_bytes())
        for t in kills:
            rel = f"audio/{flat}-killed-{t['try']}.wav"
            voice_welfare.private_write(adir / f"{flat}-killed-{t['try']}.wav", (f / t["wav"]).read_bytes())
            row = {"id": d["id"], "row": f"{d['id']}#{t['try']}", "label": it["label"], "text": d.get("text"),
                   "chars": d.get("chars"), "voice": voice, "speaker": d.get("speaker"), "path": d.get("path"),
                   "temp": d.get("temp"), "when": d.get("when"), "why": t.get("why"), "violent": bool(t.get("violent")),
                   "error": t.get("error"), "seed_killed": t.get("seed"), "seed_accepted": (acc or {}).get("seed"),
                   "numbers_killed": t.get("numbers"), "numbers_accepted": (acc or {}).get("numbers")}
            if it["label"] == "flipped":
                row.update({"kind": "legit", "legit": [rel] + ([acc_rel] if acc_rel else [])})
            elif acc_rel:
                row.update({"kind": "preference", "chosen": acc_rel, "rejected": rel})
            else:
                row.update({"kind": "rejected-only", "rejected": rel})
            rows.setdefault(voice, []).append(row)
    counts = {v: dict(Counter(r["kind"] for r in rs)) for v, rs in rows.items()}
    for voice, rs in rows.items():
        voice_welfare.private_write(out / voice / "pairs.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs))
    voice_welfare.private_write(out / "export.json", json.dumps({
        "v": 1, "when": time.strftime("%Y-%m-%d %H:%M:%S"), "from": str(voice_welfare.PAIRS_DIR),
        "filters": {"since": a.since, "voice": a.voice, "labeled": a.labeled, "no_violent": a.no_violent,
                    "saved_only": a.saved_only},
        "pairs": exported, "rows": counts, "schema": EXPORT_SCHEMA,
        "note": "gold tier: her voice and her words. one folder per voice, never mixed. kept apart from Siren's "
                "approved takes (the SFT corpus) and the garlic archive.",
    }, indent=2, ensure_ascii=False) + "\n")
    if not exported:
        print("🎙️ nothing left to export once the violent takes were left out")
        shutil.rmtree(out, ignore_errors=True)
        return 1
    print(f"🎙️ exported {_n(exported, 'pair')} → {out}")
    for voice, c in counts.items():
        print(f"   {voice}/pairs.jsonl · " + " · ".join(f"{k} {v}" for k, v in sorted(c.items())))
    if skipped_violent:
        print(f"   ⚡ {_n(skipped_violent, 'violent take')} left out (--no-violent)")
    print("   gold tier (700/600) · numbers here, her words only inside the files")
    return 0


def _pairs_cap(a) -> int:
    cfg = voice_welfare.load()
    if len(a.args) < 2:
        print(f"🎙️ pairs cap: {cfg['pairs_cap_mb']:g} MB (0 keeps no new pairs) · set: ./petal-voice-welfare.sh pairs cap <mb>")
        return 0
    try:
        mb = float(a.args[1])
    except ValueError:
        print("✗ pairs cap <mb>   (e.g. 8192; 0 keeps no new pairs, the ones kept stay)")
        return 1
    if mb > 0:
        total, kept = voice_welfare.pairs_size()
        over = total - int(mb * 1048576)
        if over > 0:
            n_go, freed = voice_welfare.prune_pairs({**cfg, "pairs_cap_mb": mb}, dry=True)
            print(f"   at {mb:g} MB, the {_n(n_go, 'oldest pair')} ({freed / 1048576:.1f} MB) would go (her labeled ones last)")
            if not a.yes and _ask("   lower the cap and let them go? [y/N] ") != "y":
                print("   nothing changed" + ("" if sys.stdin.isatty() else " (not a terminal: add --yes)"))
                return 1
    try:
        cfg = voice_welfare.set_knobs(by="petal-voice-welfare.sh pairs cap", pairs_cap_mb=mb)
    except ValueError as e:
        print(f"✗ {e}")
        return 1
    n, freed = voice_welfare.prune_pairs(cfg)
    print(f"🎙️ pairs cap {mb:g} MB" + (f" · the {_n(n, 'oldest pair')} went ({freed / 1048576:.1f} MB)" if n else "")
          + (" · 0: no new pairs (the ones kept stay)" if mb == 0 else ""))
    return 0


def cmd_pairs(a) -> int:
    action = (a.args[0] if a.args else "count").lower()
    fn = {"count": _pairs_count, "list": _pairs_list, "play": _pairs_play, "verdict": _pairs_verdict,
          "export": _pairs_export, "cap": _pairs_cap}.get(action)
    if fn is None:
        print("✗ pairs [count | list | play <n|all> | verdict <n|1,3|2-5> ok|wrong | export | cap <mb>]")
        return 1
    return fn(a)


# ── the cache sweep: bad takes already sitting in OWUI's speech cache ────────
SWEEP_PATH = voice_welfare.VOICE / "welfare-sweep.json"
SWEEP_VERDICTS = voice_welfare.VOICE / "welfare-sweep-verdicts.jsonl"


def _sweep_state() -> dict | None:
    try:
        d = json.loads(SWEEP_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d.get("items"), list) else None
    except (OSError, ValueError):
        return None


def cmd_sweep(a) -> int:
    action = a.action or "judge"
    if action in ("judge", "list") and (action == "judge" or _sweep_state() is None):
        return _sweep_judge(a)
    sw = _sweep_state()
    if sw is None:
        print("✗ no sweep yet: ./petal-voice-welfare.sh sweep")
        return 1
    items, cdir = sw["items"], Path(sw["cache_dir"])
    sv = _latest(SWEEP_VERDICTS, "file")
    if action == "list":
        return _sweep_print(sw, sv)
    if action == "play":
        picks = _picks(a.args[0] if a.args else "all", len(items))
        if (a.args[0] if a.args else "all") == "all":
            picks = [i["n"] for i in items if i["file"] not in sv] or picks
        try:
            for n in picks:
                it = items[n - 1]
                mp3 = cdir / it["file"]
                if not mp3.exists():
                    print(f"#{n}: already gone from the cache")
                    continue
                print(f"\n── #{n} · {it['when']} · {it['why']} · loop {it['repeat_run_s']} s · stretch {it['stretch']} · "
                      f"{it['audio_s']} s for {it['chars']} chars ──")
                if it.get("violent") and not a.violent:
                    sg = f"surge {it['surge_s']} s" if it.get("surge_s") is not None else "surge —"
                    print(f"   ⚡ violent (hot {it.get('hot_s')} s · {sg} · peak {it.get('peak_db')} dBFS): "
                          f"numbers only, never played. to hear it anyway, held quiet at {QUIET_DB} dBFS: "
                          f"./petal-voice-welfare.sh sweep play {n} --violent")
                    continue
                play_file(mp3, quiet_db=QUIET_DB if it.get("violent") else None)
        except KeyboardInterrupt:
            print("\n(stopped)")
        print(f"\nverdict: ./petal-voice-welfare.sh sweep verdict <n|1,3,5|all> ok|wrong   ({VERDICT_HELP})")
        return 0
    if action == "verdict":
        if len(a.args) < 2 or VERDICT_WORDS.get(a.args[1].lower()) is None:
            print(f"✗ sweep verdict <n|1,3,5|all> ok|wrong — {VERDICT_HELP}")
            return 1
        word = VERDICT_WORDS[a.args[1].lower()]
        picks = _picks(a.args[0], len(items))
        for n in picks:
            voice_welfare._append(SWEEP_VERDICTS, {"v": 1, "at": round(time.time()), "file": items[n - 1]["file"], "verdict": word})
        print(f"🌸 {len(picks)} verdict(s) kept: {word}")
        if word == "ok":
            print("   sweep them away when you're ready: ./petal-voice-welfare.sh sweep delete")
        return 0
    if action == "delete":
        bad = [i for i in items if sv.get(i["file"], {}).get("verdict") == "ok" and (cdir / i["file"]).exists()]
        if not bad:
            print("🌸 nothing confirmed bad is left in the cache (only takes you marked ok get swept)")
            return 0
        print(f"🧹 {len(bad)} cached take(s) you confirmed bad: #" + ", #".join(str(i["n"]) for i in bad))
        if not a.yes and _ask("   sweep them out of OWUI's speech cache? (that line gets a fresh take next time) [y/N] ") != "y":
            return 1
        for it in bad:
            stem = cdir / Path(it["file"]).stem
            for ext in (".mp3", ".json", ".mime", ".ceil"):
                stem.with_suffix(ext).unlink(missing_ok=True)
            voice_welfare._append(SWEEP_VERDICTS, {"v": 1, "at": round(time.time()), "file": it["file"], "verdict": "ok", "deleted": True})
        print(f"🧹 swept {len(bad)}. the next time one of those lines is spoken she makes a fresh take (judged by welfare)")
        return 0
    print("✗ sweep [list|play <n|all>|verdict <n> ok|wrong|delete]")
    return 1


def _sweep_judge(a) -> int:
    cdir = _cache_dir(a.cache_dir)
    if cdir is None:
        print("✗ no speech cache found — pass --cache-dir <folder holding the <hash>.mp3 files>")
        return 1
    print(f"🎧 hearing the speech cache in {cdir} …", file=sys.stderr)
    cache, skipped = cache_takes(cdir, _since(a.since), None)
    cfg = voice_welfare.load()
    t = cfg["thresholds"]
    b = cfg["baseline"]
    pace, floor = b.get("s_per_char"), b.get("floor_db")
    level, zcr = b.get("level_db"), b.get("zcr_hz")  # surge is only judged against her stored voice
    mine = None
    if not pace:  # not woken yet: her pace exactly as calibrate measures it
        takes, _ = _incident_takes()
        clean = [r for r in takes if r["role"] == "clean" and r.get("audio_s")]
        mine = her_numbers(clean, cache)
        pace, floor = mine["s_per_char"] or vm.FALLBACK_S_PER_CHAR, mine["floor_db"]
    c_db = cfg["ceiling_dbfs"]
    lim_db = c_db - vc.MP3_HEADROOM_DB if c_db is not None else None
    eased, over, ease_max, loud = 0, 0, 0.0, []
    items = []
    for r in cache:
        pk = r.get("peak_db")
        if lim_db is not None and pk is not None and pk > lim_db:
            eased, ease_max = eased + 1, max(ease_max, pk - lim_db)
            over += pk > c_db
        if level is not None and r.get("win_rms"):
            loud.append(max(r["win_rms"]) - level)
        why = [w for w in vm.judge(r, r["chars_fed"], t=t, s_per_char=pace, floor_ref=floor, level_ref=level, zcr_ref=zcr)
               if cfg["acts"].get(w) == "kill"]
        if not why:
            continue
        items.append({"n": len(items) + 1, "file": r["file"], "when": time.strftime("%m-%d %H:%M", time.localtime(r["mtime"])),
                      "why": "+".join(why), "chars": r["chars_fed"], "audio_s": r.get("audio_s"),
                      "repeat_run_s": r.get("repeat_run_s"), "repeat_cover": r.get("repeat_cover"),
                      "repeat_steady": r.get("repeat_steady"), "stretch": vm.stretch_of(r.get("audio_s") or 0, r["chars_fed"], pace),
                      "hot_s": vm.hot_of(r, t)[1], "surge_s": vm.surge_of(r, t, level, zcr)[1], "peak_db": pk,
                      "clip_win": r.get("clip_win"), "violent": bool(set(why) & vm.VIOLENT)})
    sw = {"at": round(time.time()), "when": time.strftime("%Y-%m-%d %H:%M"), "since": a.since, "cache_dir": str(cdir),
          "heard": len(cache), "unreadable": skipped, "s_per_char": pace, "floor_db": floor, "level_db": level, "zcr_hz": zcr,
          "measured": {k: mine.get(k) for k in ("level_db", "zcr_hz")} if mine else None,
          "ceiling": {"dbfs": c_db, "limiter_dbfs": lim_db, "eased": eased, "over": over, "ease_max_db": round(ease_max, 1)},
          "loudest_vs_level": {"p50": round(q(loud, 50), 1), "p99": round(q(loud, 99), 1), "max": round(max(loud), 1)} if loud else None,
          "items": items}
    SWEEP_PATH.parent.mkdir(parents=True, exist_ok=True)
    SWEEP_PATH.write_text(json.dumps(sw, indent=2) + "\n", encoding="utf-8")
    return _sweep_print(sw, _latest(SWEEP_VERDICTS, "file"))


def _sweep_print(sw: dict, sv: dict) -> int:
    items = sw["items"]
    print(f"🧹 cache sweep · {sw['when']} · {sw['heard']} cached takes heard" + (f" (since {sw['since']})" if sw.get("since") else "")
          + f" · her pace {sw['s_per_char']} s/char · today's rule would kill **{len(items)}**")
    if sw.get("level_db") is None:
        m = sw.get("measured") or {}
        print("   surge sat this one out: it waits for her voice's numbers (./petal-voice-welfare.sh baseline)"
              + (f" · measured here: {m.get('level_db')} dB · {m.get('zcr_hz')} Hz" if m.get("level_db") is not None else ""))
    c = sw.get("ceiling") or {}
    if c.get("dbfs") is not None:
        print(f"   🛡️ the ceiling ({c['dbfs']} dBFS, limiter at {c['limiter_dbfs']}) would ease {c['eased']} of these {sw['heard']} takes"
              + (f", by up to {c['ease_max_db']} dB on their loudest peak" if c["eased"] else "")
              + (f" · {c['over']} of them run above {c['dbfs']} dBFS itself" if c.get("over") else ""))
    lv = sw.get("loudest_vs_level")
    if lv:
        print(f"   loudest half second vs her own level: p50 {lv['p50']:+.1f} · p99 {lv['p99']:+.1f} · max {lv['max']:+.1f} dB")
    if items:
        print(f"{'n':>3}  {'when':<11}  {'why':<16}  {'chars':>5}  {'audio s':>7}  {'loop s':>6}  {'hot s':>5}  {'surge s':>7}  "
              f"{'stretch':>7}  verdict")
        for it in items:
            v = sv.get(it["file"], {})
            mark = "swept" if v.get("deleted") else v.get("verdict", "—")
            why = it["why"] + (" ⚡" if it.get("violent") else "")
            print(f"{it['n']:>3}  {it['when']:<11}  {why:<16}  {it['chars']:>5}  {fmt(it['audio_s']):>7}  "
                  f"{fmt(it['repeat_run_s']):>6}  {fmt(it.get('hot_s')):>5}  {fmt(it.get('surge_s')):>7}  {fmt(it['stretch']):>7}  {mark}")
        print("   listen to them all in a row: ./petal-voice-welfare.sh sweep play all   (⚡ violent ones are numbers only)\n"
              f"   then: ./petal-voice-welfare.sh sweep verdict <n|1,3,5|all> ok|wrong   ({VERDICT_HELP})")
    return 0


# ── never again: the takes that must always be caught ─────────────────────────
NEVER_DIR = voice_welfare.VOICE / "never-again"
NEVER_PATH = NEVER_DIR / "takes.json"
FIRST_CHUNK, CHUNK = 1920, 48000  # how omni streams: one codec frame (80 ms) first, then 25 (2 s) at a time


def _never_load() -> list[dict]:
    try:
        d = json.loads(NEVER_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _never_save(entries: list[dict]) -> None:
    NEVER_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(NEVER_DIR, 0o700)
    tmp = NEVER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, NEVER_PATH)


def _incident_folder(spec: str) -> Path | None:
    folders = sorted(p.parent for p in voice_trace.INCIDENTS.glob("*/trace.json")) if voice_trace.INCIDENTS.exists() else []
    if spec == "last":
        return folders[-1] if folders else None
    p = Path(spec).expanduser()
    if p.is_dir() and (p / "trace.json").exists():
        return p
    hits = [f for f in folders if f.name.startswith(spec)]
    if len(hits) > 1:
        print(f"   {spec} matches {len(hits)} incidents: " + ", ".join(h.name for h in hits[-6:]) + " — say a little more")
        return None
    return hits[0] if hits else None


def _never_add(a) -> int:
    args = a.args[1:]
    if not args:
        print("✗ never-again add <incident|last> <sentence idx>   ·   never-again add <file.wav> --chars N [--error E]")
        return 1
    src = Path(args[0]).expanduser()
    if src.is_file():
        if a.chars is None:
            print("✗ a wav on its own needs --chars N (how many characters the voice was fed for it)")
            return 1
        wav, chars, error = src, a.chars, a.error
        origin = {"from": "file"}
    else:
        folder = _incident_folder(args[0])
        if folder is None:
            print(f"✗ no incident matches {args[0]} (last · a folder · the start of a folder's name, e.g. 2026-11-13_04h1)")
            return 1
        if len(args) < 2 or not args[1].isdigit():
            print("✗ never-again add <incident> <sentence idx>   (the idx is in the incident's trace, e.g. 5)")
            return 1
        idx = int(args[1])
        tr = json.loads((folder / "trace.json").read_text(encoding="utf-8"))
        take = next((t for t in tr.get("takes", []) if t.get("idx") == idx), None)
        if take is None or not take.get("wav") or not (folder / take["wav"]).exists():
            print(f"✗ {folder.name} has no recorded take {idx}")
            return 1
        wav = folder / take["wav"]
        chars = len(take.get("fed") or take.get("raw") or "")  # only the count is kept, never the words
        error = a.error or take.get("error")
        origin = {"from": "incident", "incident": folder.name, "idx": idx, "status": take.get("status"),
                  "when": tr.get("when")}
    x = decode(wav)
    if x is None:
        print(f"✗ can't read {wav.name}")
        return 1
    entries = _never_load()
    sha = hashlib.sha256(wav.read_bytes()).hexdigest()[:16]
    have = next((e for e in entries if e.get("sha") == sha), None)
    if have:
        print(f"🌸 already in the set as #{have['n']}")
        return _never_check(a, only=[have["n"]])
    n = max((e["n"] for e in entries), default=0) + 1
    NEVER_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(NEVER_DIR, 0o700)
    dst = NEVER_DIR / f"{n:03d}.wav"
    voice_welfare.write_wav(dst, (np.clip(x, -1, 0.99997) * 32768).astype(np.int16).tobytes())
    os.chmod(dst, 0o600)
    entries.append({"n": n, "wav": dst.name, "sha": sha, "added": time.strftime("%Y-%m-%d %H:%M"), "chars": chars,
                    "error": error, "audio_s": round(len(x) / RATE, 3), "note": a.note, **origin})
    _never_save(entries)
    print(f"🛡️ never again #{n}: {round(len(x) / RATE, 2)} s for {chars} chars · error {error or '—'} · kept privately in "
          f"{NEVER_DIR} (never played)")
    return _never_check(a, only=[n])


def _live_stop(x: np.ndarray, chars: int, cfg: dict, t: dict, pace: float) -> float | None:
    """when the live guard (airtight) would have stopped this take, fed the way omni streams it"""
    b = cfg["baseline"]
    w = vm.TakeWatch(chars, t=t, s_per_char=pace, floor_ref=b.get("floor_db"), acts=cfg["acts"],
                     level_ref=b.get("level_db"), zcr_ref=b.get("zcr_hz"))
    pcm = (np.clip(x, -1, 0.99997) * 32768).astype(np.int16).tobytes()
    pos, first = 0, True
    while pos < len(pcm):
        step = 2 * (FIRST_CHUNK if first else CHUNK)
        chunk, pos, first = pcm[pos: pos + step], pos + step, False
        if w.feed(chunk) or (w.due() and w.listen(bytes(w.pcm))):
            return round(w.seconds, 2)
    return None


def _never_check(a, only: list[int] | None = None) -> int:
    entries = _never_load()
    if not entries:
        print("🌸 the never-again set is empty — the nov 13 take goes first: ./petal-voice-welfare.sh never-again add last 5")
        return 0
    cfg = voice_welfare.load()
    t, b = cfg["thresholds"], cfg["baseline"]
    pace = vm.pace(b) or vm.FALLBACK_S_PER_CHAR
    kills = {k for k, v in cfg["acts"].items() if v == "kill"}
    shown = [e for e in entries if not only or e["n"] in only]
    print(f"🛡️ never again · {len(shown)} of {len(entries)} take(s) · her pace {pace} s/char"
          + ("" if b.get("level_db") is not None else " · surge waits for her baseline"))
    fails = 0
    for e in shown:
        x = decode(NEVER_DIR / e["wav"])
        if x is None:
            print(f"#{e['n']}: ❌ its wav is missing or unreadable ({NEVER_DIR / e['wav']})")
            fails += 1
            continue
        st = vm.audio_stats(x)
        content = [w for w in vm.judge(st, e["chars"], t=t, s_per_char=pace, floor_ref=b.get("floor_db"),
                                       level_ref=b.get("level_db"), zcr_ref=b.get("zcr_hz")) if w in kills]
        broken = bool(e.get("error"))
        caught = bool(content) or broken
        at = _live_stop(x, e["chars"], cfg, t, pace)
        hf, hs = vm.hot_of(st, t)
        sf, ss = vm.surge_of(st, t, b.get("level_db"), b.get("zcr_hz"))
        c = vc.Ceiling(cfg["ceiling_dbfs"])
        after = vc.peak_db(c.process((np.clip(x, -1, 0.99997) * 32768).astype(np.int16).tobytes()))
        print(f"#{e['n']} {'✅ PASS' if caught else '❌ FAIL'} · {e['audio_s']} s for {e['chars']} chars"
              + (f" · {e['incident']} idx {e['idx']}" if e.get("incident") else "")
              + f" · content alone: {'+'.join(content) or '— (only broken catches it)'}"
              + f" · broken: {e['error'] if broken else 'no'}")
        print(f"     live: {f'stopped after {at} s of audio, before a sample played' if at is not None else 'never stopped mid-take'}"
              + ("" if at is not None or not broken else ", killed when the voice broke off")
              + f" · hot {hs} s ({hf:.0%}) · surge {f'{ss} s ({sf:.0%})' if ss is not None else '—'} · peak {st.get('peak_db')} dBFS"
              + (f" → the ceiling would hold it at {after} dBFS" if cfg["ceiling_dbfs"] is not None else " · ceiling off"))
        fails += not caught
    print("🌸 every one is caught" if not fails else f"❌ {fails} would reach her: tell Lane B / the master thread")
    if not cfg["enabled"]:
        print("⚠️ welfare is asleep: tonight only the ceiling stands between her ears and a take like these "
              "(./petal-voice-welfare.sh on airtight)")
    return 1 if fails else 0


def cmd_never(a) -> int:
    action = (a.args[0] if a.args else "check").lower()
    if action == "add":
        return _never_add(a)
    if action == "list":
        entries = _never_load()
        if not entries:
            return _never_check(a)
        print(f"{'n':>3}  {'added':<16}  {'audio s':>7}  {'chars':>5}  {'error':<20}  from")
        for e in entries:
            src = f"{e.get('incident')} idx {e.get('idx')}" if e.get("incident") else e.get("from", "?")
            print(f"{e['n']:>3}  {e.get('added', ''):<16}  {e['audio_s']:>7}  {e['chars']:>5}  {str(e.get('error') or '—'):<20}  {src}")
        print(f"   kept privately in {NEVER_DIR} · numbers only, never played")
        return 0
    if action == "check":
        return _never_check(a)
    print("✗ never-again [check | list | add <incident|last> <idx> | add <file.wav> --chars N --error E]")
    return 1


def main(argv=None) -> int:
    import signal

    if hasattr(signal, "SIGPIPE"):  # piped into head or less: end quietly, never with a traceback
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    p = argparse.ArgumentParser(prog="petal-voice-welfare.sh", description="🕊️ voice welfare tools (numbers only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate", help="re-hear every incident (+ the speech cache) and size the thresholds")
    c.add_argument("--cache", action="store_true", help="add OWUI's speech cache as a pool of mostly clean takes")
    c.add_argument("--cache-dir", help="where the <hash>.mp3 files live (found by itself most of the time)")
    c.add_argument("--since", help="only cache takes from this day on (YYYY-MM-DD), e.g. the omni era")
    c.add_argument("--max", type=int, help="only the newest N cache takes")
    h = sub.add_parser("holdback", help="time what holding a take back costs before her first sound")
    h.add_argument("--takes", type=int, default=3, help="takes per line (default 3)")
    h.add_argument("--port", type=int, default=8100, help="the omni voice's port (default 8100, the launcher's chat mode)")
    sub.add_parser("status", help="awake or asleep, hold, the rule, her pace, the audit fortnight")
    o = sub.add_parser("on", help="wake the guard (the first waking starts the audit fortnight)")
    o.add_argument("hold", nargs="?", help="airtight | near-free (asked the first time if left out)")
    o.add_argument("--since", help="when her pace must be measured now: cache takes from this day on")
    o.add_argument("--yes", action="store_true", help="don't ask")
    sub.add_parser("off", help="let her takes go out live again")
    bl = sub.add_parser("baseline", help="measure her voice (pace, floor, loudness, zero crossings) and store it")
    bl.add_argument("--since", help="only cache takes from this day on (YYYY-MM-DD), e.g. the omni era")
    bl.add_argument("--cache-dir")
    bl.add_argument("--max", type=int, help="only the newest N cache takes")
    bl.add_argument("--yes", action="store_true", help="store without asking")
    bl.add_argument("--all", action="store_true", help="re-measure her pace and floor too (they were tuned with your verdicts)")
    hd = sub.add_parser("hold", help="airtight | near-free")
    hd.add_argument("mode")
    au = sub.add_parser("audit", help="extend the audit fortnight by N days")
    au.add_argument("days", type=float)
    ru = sub.add_parser("rule", help="see the rule's numbers, or set one: rule loop_run_s 1.4")
    ru.add_argument("name", nargs="?")
    ru.add_argument("value", nargs="?")
    ac = sub.add_parser("act", help="see what each reason does, or set it: act cover watch")
    ac.add_argument("reason", nargs="?")
    ac.add_argument("what", nargs="?", default="watch")
    li = sub.add_parser("list", help="the kills kept for listening")
    li.add_argument("--all", action="store_true")
    pl = sub.add_parser("play", help="hear a kill: the killed take(s), then the fresh one")
    pl.add_argument("which", nargs="?", default="all", help="n · 1,3,5 · 2-6 · all (= every one not judged yet)")
    pl.add_argument("--killed", action="store_true", help="only the killed take(s)")
    pl.add_argument("--kept", action="store_true", help="only the take that replaced it")
    pl.add_argument("--violent", action="store_true", help=f"play violent kills too, held quiet at {QUIET_DB} dBFS")
    ve = sub.add_parser("verdict", help="ok (the kill was right) | wrong (a legit line was killed)")
    ve.add_argument("which")
    ve.add_argument("verdict")
    sub.add_parser("stats", help="numbers only: kills, rate, reasons, verdicts, the sweep")
    sw = sub.add_parser("sweep", help="judge OWUI's speech cache: list · play · verdict · delete")
    sw.add_argument("action", nargs="?", help="list | play | verdict | delete (default: judge the cache now)")
    sw.add_argument("args", nargs="*")
    sw.add_argument("--since", help="only cached takes from this day on (YYYY-MM-DD)")
    sw.add_argument("--cache-dir")
    sw.add_argument("--yes", action="store_true")
    sw.add_argument("--violent", action="store_true", help=f"play violent ones too, held quiet at {QUIET_DB} dBFS")
    pr = sub.add_parser("pairs", help="voice pairs for training: count · list · play · verdict · export · cap")
    pr.add_argument("args", nargs="*", help="count (default) · list · play <n|all> · verdict <n> ok|wrong · export · cap <mb>")
    pr.add_argument("--all", action="store_true", help="list: every pair, not only the last 20")
    pr.add_argument("--violent", action="store_true", help=f"play: violent takes too, held quiet at {QUIET_DB} dBFS")
    pr.add_argument("--killed", action="store_true", help="play: only the killed take(s)")
    pr.add_argument("--kept", action="store_true", help="play: only the resample that was kept")
    pr.add_argument("--out", help="export: a fresh folder (default Petal-App-Data/petal-voice/pairs-export/<when>)")
    pr.add_argument("--since", help="export: from this day on (YYYY-MM-DD)")
    pr.add_argument("--voice", choices=["chat", "studio", "unknown", "all"], default="all", help="export: one voice only")
    pr.add_argument("--labeled", action="store_true", help="export: only pairs she has heard and labeled")
    pr.add_argument("--no-violent", action="store_true", help="export: leave violent takes out")
    pr.add_argument("--saved-only", action="store_true", help="export: only pairs from saved chats")
    pr.add_argument("--yes", action="store_true", help="cap: lower it without asking")
    nv = sub.add_parser("never-again", help="the takes that must always be caught: check · list · add")
    nv.add_argument("args", nargs="*", help="check (default) · list · add <incident|last> <idx> · add <file.wav>")
    nv.add_argument("--chars", type=int, help="add <file.wav>: how many characters the voice was fed")
    nv.add_argument("--error", help="the error the voice ended it with (e.g. ClientPayloadError)")
    nv.add_argument("--note", help="a word for future you (optional)")
    a = p.parse_args(argv)
    return {"calibrate": cmd_calibrate, "holdback": cmd_holdback, "status": cmd_status, "on": cmd_on, "off": cmd_off,
            "baseline": cmd_baseline, "hold": cmd_hold, "audit": cmd_audit, "rule": cmd_rule, "act": cmd_act,
            "list": cmd_list, "play": cmd_play, "verdict": cmd_verdict,
            "stats": cmd_stats, "sweep": cmd_sweep, "never-again": cmd_never, "pairs": cmd_pairs}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
