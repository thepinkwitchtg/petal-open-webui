"""
🛡️🎀 voice ceiling — nothing that plays can ever go past it
─────────────────────────────────────────────────────────────
the last thing every sample passes before her ears, whatever welfare decided and whether it is
awake or asleep: petal stream (in the station, right before the mp3 encoder) and the speaker clips
(right before they're returned and cached). born nov 13 2026, after a runaway take reached her raw.

  · nothing she hears ever above the ceiling (welfare.json "ceiling_dbfs", -3 by default; null turns
    it off). everything she hears is mp3, and the encoder adds its own overshoot on top of a limited
    peak (up to ~1.4 dB on the nov 13 take at 96 kbps), so the limiter itself works MP3_HEADROOM_DB
    under the ceiling and the decoded sound stays beneath it
  · instant attack (the very block holding a hot peak is already turned down), smooth release
    (~80 ms back to untouched), so nothing ever clips, not even inside the mp3 decoder on her phone
  · transparent below its own level (ceiling − headroom, -4.5 dBFS by default): a chunk that never
    reaches it goes out byte-identical. her loudest normal peaks can brush it (the nov 13 take's own
    clean opening peaked at -3.7 dBFS) and are eased down a dB or so for a few milliseconds, far
    under what an ear can tell. welfare.jsonl only hears of it when something above the ceiling
    itself arrived (ran_hot)

what it is not: a peak ceiling keeps clipping and full-scale blasts out, but a harsh take held at
-3 dBFS is still loud. keeping such a take from her ears at all is welfare's job (the kills).
"""

from __future__ import annotations

import math

import numpy as np

RATE = 24000
BLOCK = 48  # 2 ms: the gain is held per block, never above what the block's own peak allows
MP3_HEADROOM_DB = 1.5  # room for the mp3 encoder's overshoot, so the decoded peak stays under the ceiling
TOUCH = 10 ** (-0.1 / 20)  # a sample counts as touched once it's eased down by 0.1 dB or more
SNAP = 0.999  # a release this close to untouched (-0.009 dB) is untouched again: byte for byte from here on


def amp(dbfs: float) -> float:
    return 32767.0 * (10.0 ** (dbfs / 20.0))


class Ceiling:
    """one stream's ceiling (its gain carries from chunk to chunk). process(bytes) → bytes"""

    def __init__(self, dbfs: float | None = -3.0, release_ms: float = 80.0, headroom_db: float = MP3_HEADROOM_DB):
        self.on = dbfs is not None
        self.dbfs = dbfs
        self.lim = amp(dbfs - headroom_db) if self.on else 32767.0
        self.rel = 1.0 - math.exp(-BLOCK / (max(1.0, release_ms) / 1000.0 * RATE))
        self.g = 1.0
        self.seen = 0  # samples that passed
        self.touched = 0  # samples it turned down
        self.peak_in = 0.0  # the hottest sample it was handed (int16 scale)

    def process(self, pcm: bytes) -> bytes:
        if not self.on or len(pcm) < 2:
            return pcm
        a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
        self.seen += len(a)
        pk = float(np.abs(a.astype(np.int32)).max())
        self.peak_in = max(self.peak_in, pk)
        if self.g >= 1.0 and pk <= self.lim:
            return pcm  # untouched, byte for byte
        x = a.astype(np.float32)
        n = len(x)
        nb = -(-n // BLOCK)
        padded = np.zeros(nb * BLOCK, dtype=np.float32)
        padded[:n] = np.abs(x)
        need = np.minimum(1.0, self.lim / np.maximum(padded.reshape(nb, BLOCK).max(axis=1), 1.0))
        g = np.empty(nb, dtype=np.float32)
        cur = self.g
        for i in range(nb):  # 500 blocks a second: cheap, and only ever while she runs hot
            cur = min(float(need[i]), cur + (1.0 - cur) * self.rel)
            g[i] = cur
        self.g = 1.0 if cur > SNAP else cur
        gs = np.repeat(g, BLOCK)[:n]
        self.touched += int(np.count_nonzero(gs < TOUCH))
        y = np.clip(np.rint(x * gs), -self.lim, self.lim)
        return y.astype(np.int16).tobytes()

    @property
    def touched_s(self) -> float:
        return self.touched / RATE

    @property
    def ran_hot(self) -> bool:
        """something above the ceiling itself was handed to it (not just a peak inside the headroom)"""
        return self.on and self.peak_in > amp(self.dbfs)

    @property
    def peak_in_db(self) -> float | None:
        return round(20 * math.log10(self.peak_in / 32767.0), 1) if self.peak_in > 0 else None


def peak_db(pcm: bytes) -> float | None:
    a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
    if not len(a):
        return None
    return round(20 * math.log10(max(1, int(np.abs(a.astype(np.int32)).max())) / 32767.0), 1)


def encode_mp3(pcm: bytes, kbps: int = 128) -> bytes | None:
    """a clip the ceiling had to touch goes back out as mp3 (lameenc, the station's own encoder)"""
    try:
        import lameenc

        e = lameenc.Encoder()
        e.set_bit_rate(kbps)
        e.set_in_sample_rate(RATE)
        e.set_channels(1)
        e.set_quality(2)
        return bytes(e.encode(pcm)) + bytes(e.flush())
    except Exception:  # noqa: BLE001
        return None
