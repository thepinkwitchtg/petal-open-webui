"""
🔎🎀 voice measure — the one ear that listens to Petal's voice for wrongness
─────────────────────────────────────────────────────────────────────────────
numbers only, numpy only, never the disk. everything that judges her voice reads it from here,
so the incident report and the live guard can never disagree about what a loop is:

  voice_trace.py     auto-suspect on a planted incident                       (offline)
  voice_welfare.py   the guard that swaps a bad take for a fresh one          (live)
  welfare_tools.py   calibration · the cache sweep · the audit fortnight      (petal-voice-welfare.sh)

what she's listened for
  loop     repeat_run_s   the longest stretch where her voice keeps matching itself at one fixed
                          delay (0.16 … 3.2 s): the luvluvluv, a wet loop, a stuck syllable
           repeat_steady  how much of that best run is a *held* sound (still matching itself 80 ms
                          later: a moan, a hum, a hiss) instead of a pattern coming round again.
                          measured for calibration; it only judges once loop_steady_max is set
  cover    repeat_cover   how much of her voice is a copy of itself somewhere in the take. its own
                          reason since nov 5 2026: at 0.6 it would have killed 9 of 663 cached takes
                          and every one was her normal voice, so welfare only watches it (≥ 0.8)
  stretch  the take runs far past what its text deserves at her own pace (s_per_char)
  hiss     her noise floor sits far above her usual floor (floor_db)
  clip     clip_win       the worst half second's share of samples at full scale (true clipping)
           hot            quarter seconds whose peak touches hot_db (-1 dBFS): a take running hot,
                          as a share of the take (hot_frac) and in seconds anywhere in it (hot_s), so
                          a runaway in the tail of a long line can't hide behind its clean start.
                          the violent runaway of nov 13 2026 ran hot from its 3rd second on
  surge    win_rms/zcr    loud AND harsh together, held: half seconds both ≥ surge_db louder than her
                          own voice (level_db) and ≥ surge_zcr_x her zero-crossing rate (zcr_hz), as a
                          share (surge_frac) and in seconds (surge_s). measured against her calibrated
                          voice, never the take's own first second: a line that opens on a soft "mmh~"
                          would trip that on legit speech
  broken   not heard, told: the voice ended the take with an error (omni's own runaway ceiling ends
           in one), so it is incomplete by definition. the callers add it, the ear can't hear it

judge() is the rule, the same everywhere. what a reason *does* live (kill · watch · off) is the
welfare policy, kept in welfare.json beside the thresholds. a held moan, a giggle, a cursed witchy
surprise that happens once: none of these is a loop, and none of them is ever touched.
"""

from __future__ import annotations

import numpy as np

RATE = 24000
WIN, HOP = 1024, 480  # 43 ms window, 20 ms hop
FRAME_S = HOP / RATE
LAG_MIN, LAG_MAX = 8, 160  # 0.16 s … 3.2 s
SIM = 0.9  # two frames this alike are the same sound
STEADY_LAG = 4  # 80 ms: a sound that still matches itself this soon is held, not repeated

DEFAULT_THRESHOLDS = {
    "loop_run_s": 1.2,  # a self-match this long at one delay is not ordinary speech
    "loop_cover": 0.8,  # cover: most of a take's voice is a copy of itself somewhere (0.6 → 9/663 false)…
    "loop_cover_min_s": 2.0,  # …in a take at least this long
    "loop_steady_max": None,  # set (e.g. 0.8) to spare runs that are mostly one held sound
    "stretch_x": 2.2,  # a take this many times longer than her pace says its text needs…
    "stretch_min_s": 3.0,  # …and never judged stretched below this (short lines breathe)
    "stretch_min_chars": 4,
    "hiss_db": 9.0,  # a noise floor this far above her usual one
    # clip · tuned on the nov 13 2026 take, then checked against her clean takes (the sweep)
    "clip_win": 0.01,  # 1% of a half second at full scale is true clipping
    "hot_db": -1.0,  # a quarter second peaking this high runs hot
    "hot_frac": 0.3,  # a third of the take's quarter seconds hot…
    "hot_min_s": 2.0,  # …in a take at least this long
    "hot_total_s": 1.5,  # …or this many hot seconds anywhere, however long the take
    # surge · the nov 13 take: 43% of its half seconds ≥ +4 dB louder and ≥ 1.8× harsher than her opening
    "surge_db": 4.0,
    "surge_zcr_x": 1.8,
    "surge_frac": 0.3,  # a third of the take loud-and-harsh at once…
    "surge_min_s": 3.0,  # …in a take at least this long
    "surge_total_s": 2.0,  # …or this many loud-and-harsh seconds anywhere
}
# her pace, her floor, her loudness and her zero-crossing rate, from calibration. None = not
# calibrated yet: the incident report then measures pace and floor against each reply's own median,
# and surge waits (it is only ever measured against her own voice)
DEFAULT_BASELINE = {"s_per_char": None, "floor_db": None, "level_db": None, "zcr_hz": None}
FALLBACK_S_PER_CHAR = 0.067  # ≈ 15 characters a second, petal-voice's own token_budget guess
VIOLENT = {"clip", "surge"}  # takes killed for these are never auto-played back (numbers are enough)
W_S, W_HOP_S = 0.5, 0.25  # the loudness / harshness windows (half a second, a quarter second apart)
BLK = int(RATE * W_HOP_S)  # the peak blocks: quarter seconds, side by side


def thresholds(t: dict | None) -> dict:
    """her numbers over the defaults. a broken value keeps the default (it never disarms a rule)"""
    out = dict(DEFAULT_THRESHOLDS)
    for k, v in (t or {}).items():
        if k not in DEFAULT_THRESHOLDS:
            continue
        if v is None and DEFAULT_THRESHOLDS[k] is None:
            out[k] = None
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            out[k] = v
    return out


# ── the ear ───────────────────────────────────────────────────────────────────
_BANDS = None


def _bands():
    global _BANDS
    if _BANDS is None:
        freqs = np.fft.rfftfreq(WIN, 1 / RATE)
        edges = np.geomspace(80, RATE / 2, 33)
        _BANDS = [b for b in ((freqs >= lo) & (freqs < hi) for lo, hi in zip(edges[:-1], edges[1:])) if b.any()]
    return _BANDS


def pcm_to_float(pcm: bytes) -> np.ndarray:
    """24 kHz mono int16 bytes → float32 in [-1, 1)"""
    n = len(pcm) // 2 * 2
    return np.frombuffer(pcm[:n], dtype=np.int16).astype(np.float32) / 32768.0


def _loop(feats: np.ndarray, voiced: np.ndarray) -> dict:
    """the longest run where her voice keeps matching itself at one delay (little quiet gaps don't
    break it), how much of her voice is copied somewhere, and how held the best run is."""
    n = len(feats)
    best_run, best_lag, best_bounds = 0, 0, None
    cover = np.zeros(n, bool)
    for lag in range(LAG_MIN, min(LAG_MAX, n // 2)):
        sim = np.einsum("ij,ij->i", feats[:-lag], feats[lag:])
        hit = (sim > SIM) & voiced[:-lag] & voiced[lag:]
        cover[:-lag] |= hit
        if hit.any():
            ok = hit | ~(voiced[:-lag] | voiced[lag:])
            d = np.diff(np.concatenate(([0], ok.astype(np.int8), [0])))
            starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
            ch = np.concatenate(([0], np.cumsum(hit)))
            runs = ch[ends] - ch[starts]  # matched voiced frames inside each run
            k = int(runs.argmax())
            if int(runs[k]) > best_run:
                best_run, best_lag, best_bounds = int(runs[k]), lag, (int(starts[k]), int(ends[k]), hit)
    steady = 0.0
    if best_bounds is not None:
        a, b, hit = best_bounds
        frames = np.flatnonzero(hit[a:b]) + a
        frames = frames[frames + STEADY_LAG < n]
        if len(frames):
            near = np.einsum("ij,ij->i", feats[frames], feats[frames + STEADY_LAG])
            steady = float(np.mean((near > SIM) & voiced[frames + STEADY_LAG]))
    return {
        "repeat_run_s": round(best_run * FRAME_S, 2),
        "repeat_lag_s": round(best_lag * FRAME_S, 2),
        "repeat_cover": round(float(cover[voiced].mean()) if voiced.any() else 0.0, 3),
        "repeat_steady": round(steady, 3),
    }


def audio_stats(x: np.ndarray) -> dict:
    """numbers only. x: float32 mono at 24 kHz. repeat_*: the loop. floor_db + quiet_flatness: the
    noise under her (hiss is flat and high). the very same numbers voice_trace always wrote."""
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
    out.update(_loop(feats, voiced))

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
    out.update(_windows(x))
    return out


def _windows(x: np.ndarray) -> dict:
    """half-second windows (quarter-second hop): how loud, how harsh, how clipped. quarter-second
    blocks side by side: how hot (each block's peak)"""
    ww, hh = int(RATE * W_S), BLK
    if len(x) < ww:
        return {}
    seg = np.lib.stride_tricks.sliding_window_view(x, ww)[::hh]
    a = np.abs(seg)
    rms = 20 * np.log10(np.sqrt(np.mean(np.square(seg), axis=1, dtype=np.float64)) + 1e-9)
    zcr = np.count_nonzero(np.diff(np.signbit(seg), axis=1), axis=1) / W_S
    on = rms > max(rms.max() - 30, -55)  # windows where she is actually speaking
    nb = len(x) // hh
    blk = 20 * np.log10(np.abs(x[: nb * hh]).reshape(nb, hh).max(axis=1) + 1e-9)
    return {
        "clip_win": round(float((a >= 0.99).mean(axis=1).max()), 4),
        "level_db": round(float(np.median(rms[on])), 1),
        "zcr_hz": int(np.median(zcr[on])),
        "win_rms": [round(float(v), 1) for v in rms],
        "win_zcr": [int(v) for v in zcr],
        "blk_peak": [round(float(v), 1) for v in blk],
    }


# ── the rule ──────────────────────────────────────────────────────────────────
def pace(baseline: dict | None, reply_s_per_char: float | None = None) -> float | None:
    """seconds per character to measure against: her calibrated pace, else the reply's own median"""
    b = baseline or {}
    v = b.get("s_per_char")
    return float(v) if isinstance(v, (int, float)) and v > 0 else reply_s_per_char


def allowed_s(chars: int, s_per_char: float | None, t: dict) -> float | None:
    """how long a take of this text may run before it's a stretch (None: too short to judge)"""
    if not s_per_char or chars < t["stretch_min_chars"]:
        return None
    return max(t["stretch_min_s"], t["stretch_x"] * s_per_char * chars)


def hot_of(stats: dict, t: dict) -> tuple[float | None, float | None]:
    """(share, seconds) of the take's quarter seconds peaking at or above hot_db"""
    b = stats.get("blk_peak")
    if not b:
        return None, None
    h = np.asarray(b, dtype=float) >= t["hot_db"]
    return round(float(h.mean()), 3), round(float(h.sum()) * W_HOP_S, 2)


def surge_mask(stats: dict, t: dict, level_ref: float | None, zcr_ref: float | None) -> np.ndarray | None:
    """which half seconds are both louder and harsher than her own voice (None: not calibrated)"""
    r, z = stats.get("win_rms"), stats.get("win_zcr")
    if not r or not z or level_ref is None or not zcr_ref:
        return None
    r, z = np.asarray(r, dtype=float), np.asarray(z, dtype=float)
    return (r >= level_ref + t["surge_db"]) & (z >= t["surge_zcr_x"] * zcr_ref)


def surge_of(stats: dict, t: dict, level_ref: float | None, zcr_ref: float | None) -> tuple[float | None, float | None]:
    """(share, seconds) of loud-and-harsh half seconds (None, None: not calibrated)"""
    m = surge_mask(stats, t, level_ref, zcr_ref)
    if m is None:
        return None, None
    return round(float(m.mean()), 3), round(float(m.sum()) * W_HOP_S, 2)


def surge_frac(stats: dict, t: dict, level_ref: float | None, zcr_ref: float | None) -> float | None:
    return surge_of(stats, t, level_ref, zcr_ref)[0]


def judge(stats: dict, chars: int, *, t: dict, s_per_char: float | None, floor_ref: float | None,
          level_ref: float | None = None, zcr_ref: float | None = None) -> list[str]:
    """why a take is wrong: [] · ["loop"] · ["stretch"] · ["clip", "surge"] · ["loop", "cover", "hiss"] …"""
    why = []
    dur = stats.get("audio_s") or 0
    run, cover = stats.get("repeat_run_s") or 0, stats.get("repeat_cover") or 0
    looped = run >= t["loop_run_s"]
    if looped and t.get("loop_steady_max") is not None and (stats.get("repeat_steady") or 0) > t["loop_steady_max"]:
        looped = False  # one held sound, not a pattern coming round again
    if looped:
        why.append("loop")
    if cover >= t["loop_cover"] and dur >= t["loop_cover_min_s"]:
        why.append("cover")
    lim = allowed_s(chars, s_per_char, t)
    if lim is not None and dur > lim:
        why.append("stretch")
    if floor_ref is not None and "floor_db" in stats and stats["floor_db"] - floor_ref >= t["hiss_db"]:
        why.append("hiss")
    hf, hs = hot_of(stats, t)
    if (stats.get("clip_win") or 0) >= t["clip_win"] or \
            (hf is not None and ((hf >= t["hot_frac"] and dur >= t["hot_min_s"]) or hs >= t["hot_total_s"])):
        why.append("clip")
    sf, ss = surge_of(stats, t, level_ref, zcr_ref)
    if sf is not None and ((sf >= t["surge_frac"] and dur >= t["surge_min_s"]) or ss >= t["surge_total_s"]):
        why.append("surge")
    return why


def stretch_of(audio_s: float, chars: int, s_per_char: float | None) -> float | None:
    if not s_per_char or chars < 1 or not audio_s:
        return None
    return round(audio_s / (chars * s_per_char), 2)


# ── the live ear: one take, judged while it streams in ───────────────────────
class TakeWatch:
    """stretch is a clock, so it's judged on every chunk, instantly. a loop is a pattern, so it's
    re-listened every `every_s` of new audio on everything she has said so far: the very same
    audio_stats the incident report runs on a saved take, so a kill reads the same offline.

    acts: {"loop": "kill"|"watch"|"off", "stretch": …, "hiss": …}. only "kill" reasons kill."""

    def __init__(self, chars: int, *, t: dict, s_per_char: float, floor_ref: float | None, acts: dict,
                 every_s: float = 0.5, level_ref: float | None = None, zcr_ref: float | None = None):
        self.chars, self.t, self.spc, self.floor_ref, self.acts = chars, t, s_per_char, floor_ref, acts
        self.level_ref, self.zcr_ref = level_ref, zcr_ref
        self.limit_s = allowed_s(chars, s_per_char, t)
        self.every = max(0.2, every_s)
        self._next = min(t["loop_run_s"], 1.0) if acts.get("clip") == "kill" or acts.get("surge") == "kill" \
            else max(t["loop_run_s"], self.every)  # a hot take can be heard from its first second
        self.pcm = bytearray()
        self.stats: dict = {}
        self.why: list[str] = []

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (2 * RATE)

    def feed(self, pcm: bytes) -> str | None:
        """→ "stretch" the moment she runs past what her text deserves (when stretch kills)"""
        self.pcm += pcm
        if self.limit_s is not None and self.acts.get("stretch") == "kill" and self.seconds > self.limit_s:
            self.stats = {"audio_s": round(self.seconds, 3)}
            self.why = ["stretch"]
            return "stretch"
        return None

    def due(self) -> bool:
        return any(self.acts.get(k) == "kill" for k in ("loop", "clip", "surge")) and self.seconds >= self._next

    def cool_upto(self) -> int:
        """near-free's gate, in bytes: nothing from the first hot quarter second (or, once her voice is
        calibrated, the first loud-and-harsh half second) on is ever let out early. such a take is held
        whole until it's judged, as in airtight"""
        a = np.frombuffer(bytes(self.pcm[: len(self.pcm) // 2 * 2]), dtype=np.int16)
        cut = len(a)
        hot = np.flatnonzero(np.abs(a.astype(np.int32)) >= 32768.0 * 10 ** (self.t["hot_db"] / 20))
        if len(hot):
            cut = int(hot[0]) // BLK * BLK
        m = surge_mask(self.stats, self.t, self.level_ref, self.zcr_ref)
        if m is not None and m.any():
            cut = min(cut, int(np.flatnonzero(m)[0]) * BLK)
        return 2 * cut

    def listen(self, pcm: bytes) -> list[str]:
        """heavy (a few ms per second of audio): run it in a thread. → the kill reasons, if any"""
        self._next = len(pcm) / (2 * RATE) + self.every
        self.stats = audio_stats(pcm_to_float(pcm))
        self.why = judge(self.stats, self.chars, t=self.t, s_per_char=self.spc, floor_ref=self.floor_ref,
                         level_ref=self.level_ref, zcr_ref=self.zcr_ref)
        return [w for w in self.why if self.acts.get(w) == "kill"]

    def numbers(self) -> dict:
        """what the guard knew when it decided (numbers only)"""
        out = {k: self.stats[k] for k in ("audio_s", "repeat_run_s", "repeat_lag_s", "repeat_cover",
                                          "repeat_steady", "floor_db", "quiet_flatness", "peak_db", "clip_win",
                                          "level_db", "zcr_hz") if k in self.stats}
        out["hot_frac"], out["hot_s"] = hot_of(self.stats, self.t)
        out["audio_s"] = round(self.seconds, 3)
        out["chars"] = self.chars
        out["stretch"] = stretch_of(self.seconds, self.chars, self.spc)
        out["limit_s"] = round(self.limit_s, 2) if self.limit_s is not None else None
        out["surge_frac"], out["surge_s"] = surge_of(self.stats, self.t, self.level_ref, self.zcr_ref)
        out["why"] = list(self.why)
        return out
