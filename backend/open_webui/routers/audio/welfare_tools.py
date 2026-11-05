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
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import voice_measure as vm  # noqa: E402
import voice_trace  # noqa: E402
import voice_welfare  # noqa: E402

RATE = vm.RATE
LEAD_IN_S = 0.18  # petal stream's lead_in_ms: she can never start sooner than this anyway


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
    return {"s_per_char": round(float(np.median(spc)), 4) if spc else None,
            "floor_db": round(float(np.median(floors)), 1) if floors else None,
            "n_pace": len(spc), "n_floor": len(floors), "_spc": spc, "_floors": floors}


def save_calibration(mine: dict, since: str | None, incidents: int, clean: int, cache: int) -> None:
    try:
        CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_PATH.write_text(json.dumps({
            "at": round(time.time()), "when": time.strftime("%Y-%m-%d %H:%M"), "cache_since": since,
            "s_per_char": mine["s_per_char"], "floor_db": mine["floor_db"], "n_pace": mine["n_pace"],
            "n_floor": mine["n_floor"], "incidents": incidents, "clean_takes": clean, "cache_takes": cache,
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
    save_calibration(mine, a.since if a.cache else None, len(incidents), len(clean), len(cache))

    def stretch(r):
        return vm.stretch_of(r["audio_s"], r["chars_fed"], pace) if r.get("audio_s") and r["chars_fed"] >= t["stretch_min_chars"] else None

    def why(r, tt=None):
        return vm.judge(r, r["chars_fed"], t=tt or t, s_per_char=pace, floor_ref=floor) if r.get("audio_s") else []

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
    L.append(f"- rule today: loop ≥ {t['loop_run_s']} s · cover ≥ {t['loop_cover']} (≥ {t['loop_cover_min_s']} s) · "
             f"stretch > {t['stretch_x']}× (min {t['stretch_min_s']} s, ≥ {t['stretch_min_chars']} chars) · hiss ≥ {t['hiss_db']} dB")
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

    def caught(inc, tt):
        return any(set(why(r, tt)) & {"loop", "stretch"} for r in inc["rows"])

    L.append("## would the guard have caught them? (loop or stretch, with her pace)")
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
        L.append("")

    def sweep(title, key, values, mk):
        L.append(f"### {title}")
        L.append("")
        L.append("| " + key + " | incidents caught | clean takes killed | cache takes killed |")
        L.append("|---|---|---|---|")
        for v in values:
            tt = mk(v)
            hit = sum(1 for inc in incidents if any(set(why(r, tt)) & {"loop", "stretch"} for r in inc["rows"]))
            ck = sum(1 for r in clean if set(why(r, tt)) & {"loop", "stretch"})
            kk = sum(1 for r in cache if set(why(r, tt)) & {"loop", "stretch"})
            mark = " ←" if v == t[key] else ""
            L.append(f"| {v}{mark} | {hit}/{len(incidents)} | {ck}/{len(clean)} | {kk}/{len(cache)} |")
        L.append("")

    L.append("## threshold sweeps (one knob moves, the others stay as today; ← is today)")
    L.append("")
    sweep("loop run", "loop_run_s", [0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0], lambda v: {**t, "loop_run_s": v})
    sweep("loop cover", "loop_cover", [0.4, 0.5, 0.6, 0.7, 0.8, 0.9], lambda v: {**t, "loop_cover": v})
    sweep("stretch", "stretch_x", [1.6, 1.8, 2.0, 2.2, 2.5, 3.0, 3.5], lambda v: {**t, "stretch_x": v})
    sweep("stretch floor (short lines)", "stretch_min_s", [2.0, 2.5, 3.0, 4.0, 5.0], lambda v: {**t, "stretch_min_s": v})
    sweep("held-sound spare (off = None)", "loop_steady_max", [None, 0.9, 0.8, 0.7, 0.6], lambda v: {**t, "loop_steady_max": v})

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


def play_file(path: Path) -> bool:
    cmd = _player()
    if cmd is None:
        print("✗ no audio player found here (ffplay, pw-play, paplay or aplay)")
        return False
    target, tmp = path, None
    if path.suffix.lower() != ".wav" and cmd[0] != "ffplay":  # the simple players want a wav
        x = decode(path)
        if x is None:
            print(f"✗ can't read {path.name}")
            return False
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
    print(f"   acts: " + " · ".join(f"{k} {v}" for k, v in cfg["acts"].items()))
    print(f"   rule: loop ≥ {t['loop_run_s']} s · cover ≥ {t['loop_cover']} (≥ {t['loop_cover_min_s']} s) · stretch > "
          f"{t['stretch_x']}× her pace (never under {t['stretch_min_s']} s) · hiss ≥ {t['hiss_db']} dB")
    print(f"   her pace {b.get('s_per_char') or '—'} s/char · her floor {b.get('floor_db') if b.get('floor_db') is not None else '—'} dB"
          + (f" · near-free window {voice_welfare.window_s(cfg)} s" if cfg["hold"] == "near-free" else ""))
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
        return {"s_per_char": d["s_per_char"], "floor_db": d.get("floor_db")}
    print("   measuring her pace from your incidents + the speech cache …")
    takes, _ = _incident_takes()
    clean = [r for r in takes if r["role"] == "clean" and r.get("audio_s")]
    cdir = _cache_dir(None)
    cache = cache_takes(cdir, _since(since), None)[0] if cdir else []
    mine = her_numbers(clean, cache)
    return {"s_per_char": mine["s_per_char"] or vm.FALLBACK_S_PER_CHAR, "floor_db": mine["floor_db"]}


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
        why = ", ".join("+".join(k.get("why") or ["?"]) for k in kills)
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
                              f" · {kill.get('audio_s')} s long (limit {kill.get('limit_s')})")
                        play_file(wav)
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
        line = f"- {label}: {n_k} takes killed in {len(ks)} sentences · recovered {sum(1 for r in ks if r.get('recovered'))} · " \
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
    temp = sum(1 for r in killed if r.get("temp"))
    if temp:
        L.append(f"- in temp chats: {temp} sentences (kept without chat/message links)")
    items = audit_items()
    if items:
        v = _latest(voice_welfare.VERDICTS_PATH, "audit")
        heard_v = [v[it["folder"].name]["verdict"] for it in items if it["folder"].name in v]
        L.append(f"- audit: {len(items)} kills kept for listening · heard {len(heard_v)} → "
                 f"{heard_v.count('ok')} confirmed bad · {heard_v.count('wrong')} false kills · {len(items) - len(heard_v)} not heard yet")
    sw = _sweep_state()
    if sw:
        sv = _latest(SWEEP_VERDICTS, "file")
        got = [sv[i["file"]] for i in sw["items"] if i["file"] in sv]
        L.append(f"- cache sweep ({sw.get('when', '?')}): {len(sw['items'])} cached takes judged bad of {sw.get('heard', '?')} · heard "
                 f"{len(got)} → {sum(1 for g in got if g['verdict'] == 'ok')} confirmed · "
                 f"{sum(1 for g in got if g['verdict'] == 'wrong')} false kills · {sum(1 for g in got if g.get('deleted'))} swept away")
    print("\n".join(L) + "\n")
    return 0


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
                play_file(mp3)
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
            for ext in (".mp3", ".json", ".mime"):
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
    pace, floor = cfg["baseline"].get("s_per_char"), cfg["baseline"].get("floor_db")
    if not pace:  # not woken yet: her pace exactly as calibrate measures it
        takes, _ = _incident_takes()
        clean = [r for r in takes if r["role"] == "clean" and r.get("audio_s")]
        mine = her_numbers(clean, cache)
        pace, floor = mine["s_per_char"] or vm.FALLBACK_S_PER_CHAR, mine["floor_db"]
    items = []
    for r in cache:
        why = [w for w in vm.judge(r, r["chars_fed"], t=t, s_per_char=pace, floor_ref=floor) if cfg["acts"].get(w) == "kill"]
        if not why:
            continue
        items.append({"n": len(items) + 1, "file": r["file"], "when": time.strftime("%m-%d %H:%M", time.localtime(r["mtime"])),
                      "why": "+".join(why), "chars": r["chars_fed"], "audio_s": r.get("audio_s"),
                      "repeat_run_s": r.get("repeat_run_s"), "repeat_cover": r.get("repeat_cover"),
                      "repeat_steady": r.get("repeat_steady"), "stretch": vm.stretch_of(r.get("audio_s") or 0, r["chars_fed"], pace)})
    sw = {"at": round(time.time()), "when": time.strftime("%Y-%m-%d %H:%M"), "since": a.since, "cache_dir": str(cdir),
          "heard": len(cache), "unreadable": skipped, "s_per_char": pace, "floor_db": floor, "items": items}
    SWEEP_PATH.parent.mkdir(parents=True, exist_ok=True)
    SWEEP_PATH.write_text(json.dumps(sw, indent=2) + "\n", encoding="utf-8")
    return _sweep_print(sw, _latest(SWEEP_VERDICTS, "file"))


def _sweep_print(sw: dict, sv: dict) -> int:
    items = sw["items"]
    print(f"🧹 cache sweep · {sw['when']} · {sw['heard']} cached takes heard" + (f" (since {sw['since']})" if sw.get("since") else "")
          + f" · her pace {sw['s_per_char']} s/char · today's rule would kill **{len(items)}**")
    if items:
        print(f"{'n':>3}  {'when':<11}  {'why':<14}  {'chars':>5}  {'audio s':>7}  {'loop s':>6}  {'cover':>5}  {'stretch':>7}  verdict")
        for it in items:
            v = sv.get(it["file"], {})
            mark = "swept" if v.get("deleted") else v.get("verdict", "—")
            print(f"{it['n']:>3}  {it['when']:<11}  {it['why']:<14}  {it['chars']:>5}  {fmt(it['audio_s']):>7}  "
                  f"{fmt(it['repeat_run_s']):>6}  {fmt(it['repeat_cover'], 2):>5}  {fmt(it['stretch']):>7}  {mark}")
        print("   listen to them all in a row: ./petal-voice-welfare.sh sweep play all\n"
              f"   then: ./petal-voice-welfare.sh sweep verdict <n|1,3,5|all> ok|wrong   ({VERDICT_HELP})")
    return 0


def main(argv=None) -> int:
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
    hd = sub.add_parser("hold", help="airtight | near-free")
    hd.add_argument("mode")
    au = sub.add_parser("audit", help="extend the audit fortnight by N days")
    au.add_argument("days", type=float)
    li = sub.add_parser("list", help="the kills kept for listening")
    li.add_argument("--all", action="store_true")
    pl = sub.add_parser("play", help="hear a kill: the killed take(s), then the fresh one")
    pl.add_argument("which", nargs="?", default="all", help="n · 1,3,5 · 2-6 · all (= every one not judged yet)")
    pl.add_argument("--killed", action="store_true", help="only the killed take(s)")
    pl.add_argument("--kept", action="store_true", help="only the take that replaced it")
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
    a = p.parse_args(argv)
    return {"calibrate": cmd_calibrate, "holdback": cmd_holdback, "status": cmd_status, "on": cmd_on, "off": cmd_off,
            "hold": cmd_hold, "audit": cmd_audit, "list": cmd_list, "play": cmd_play, "verdict": cmd_verdict,
            "stats": cmd_stats, "sweep": cmd_sweep}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
