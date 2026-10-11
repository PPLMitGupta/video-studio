"""Subtle sound design, synthesised (no audio files): click ticks, whooshes and typing ticks.

All placed on the output timeline and mixed under the voice before loudness normalisation.
Levels are dBFS peaks per sound; brand.json "sfx" can override them (null turns one off).
"""
import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
LEVELS = {"click": -27, "whoosh": -31, "type": -37}


def _norm(x, db):
    return (x * 10 ** (db / 20) / (np.abs(x).max() or 1)).astype(np.float32)


def click(db, rng):
    n = int(0.035 * SR); k = np.arange(n)
    tick = np.diff(rng.standard_normal(n) * np.exp(-k / (0.004 * SR)), prepend=0) * 0.5
    tick += 0.6 * np.sin(2 * np.pi * 2300 * k / SR) * np.exp(-k / (0.003 * SR))
    return _norm(tick, db)


def whoosh(db, rng, dur=0.55):
    """Noise through a band-pass whose centre sweeps up then down, with a soft swell."""
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    seg = 512
    for i in range(0, n, seg):
        x = i / n
        fc = 400 + 2600 * np.sin(np.pi * x) ** 1.5
        sos = butter(2, [fc * 0.6, min(fc * 1.6, SR / 2 - 100)], btype="band", fs=SR, output="sos")
        out[i:i + seg] = sosfilt(sos, noise[max(0, i - 2048):i + seg])[-len(out[i:i + seg]):]
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 2
    return _norm(out * env, db)


def keytick(db, rng):
    n = int(0.018 * SR); k = np.arange(n)
    x = rng.standard_normal(n) * np.exp(-k / (0.002 * SR))
    sos = butter(2, [1800, 6000], btype="band", fs=SR, output="sos")
    return _norm(sosfilt(sos, x), db + rng.uniform(-3, 0))


def build(out_dur, clicks=(), whooshes=(), typing=(), levels=None, seed=7):
    """clicks/whooshes: output times; typing: [(start, end)] output-time ranges at 1x speed."""
    lv = dict(LEVELS); lv.update({k: v for k, v in (levels or {}).items()})
    rng = np.random.default_rng(seed)
    track = np.zeros(int((out_dur + 1) * SR), dtype=np.float32)

    def put(sound, t):
        i = int(t * SR)
        if 0 <= i < len(track):
            j = min(len(track), i + len(sound))
            track[i:j] += sound[:j - i]

    if lv.get("click") is not None:
        c = click(lv["click"], rng)
        for t in clicks:
            put(c, t)
    if lv.get("whoosh") is not None:
        w = whoosh(lv["whoosh"], rng)
        for t in whooshes:
            put(w, t - 0.25)   # the swell peaks on the transition
    if lv.get("type") is not None:
        for a, b in typing:
            t = a
            while t < b:
                put(keytick(lv["type"], rng), t)
                t += rng.uniform(0.07, 0.16)
    return track
