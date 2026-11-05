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
        r.update({"chars_fed": len(text), "role": "cache", "inc": None, "idx": i})
        rows.append(r)
        if (i + 1) % 50 == 0:
            print(f"  … {i + 1}/{len(files)} cached takes heard", file=sys.stderr)
    return rows, skipped


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
    pool = clean + cache
    spc_all = [r["audio_s"] / r["chars_fed"] for r in pool if r.get("audio_s") and r["chars_fed"] >= 12]
    pace = float(np.median(spc_all)) if spc_all else (cfg["baseline"].get("s_per_char") or vm.FALLBACK_S_PER_CHAR)
    floors = [r["floor_db"] for r in pool if "floor_db" in r]
    floor = float(np.median(floors)) if floors else None

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
    a = p.parse_args(argv)
    return {"calibrate": cmd_calibrate, "holdback": cmd_holdback}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
