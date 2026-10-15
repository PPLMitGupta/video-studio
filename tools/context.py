"""Context-aware zoom targets: frame what belongs with a change, not just the change.

A change box (a dropdown that opened, a field that got a value) is rarely the whole story. On a
mapping or form screen the label that explains it sits on the same row, often far to the left
("Speech-Language Therapy · 15 rows" next to its dropdown). Zooming on the dropdown alone cuts
that off.

For each event with a target box, look at the real frame just after the change and grow the box
along its row: keep adding content to the left and right until a long empty gap or a panel border
(a long vertical line: sidebar edge, card edge). The result is stored as the event's "ctx" box,
which the camera frames instead of the raw box. Tall boxes grow too, so an open list stays wide.

usage (normally called by build.py): add(src, events) -> events with "ctx" (source px)
"""
import subprocess
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from common import ffmpeg

AW = 960            # analysis width
VERSION = 3


def _gray(src, t, w, h):
    raw = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(src), "-frames:v", "1",
                          "-vf", f"scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w).astype(np.int16) if len(raw) >= w * h else None


def barriers(g):
    """Columns holding a long vertical line (panel or card border, sidebar edge, scrollbar)."""
    gx = np.abs(np.diff(g, axis=1)) > 6
    gx = np.pad(gx, ((0, 0), (0, 1)))
    best = np.zeros(g.shape[1], int)
    run = np.zeros(g.shape[1], int)
    for row in gx:                       # longest vertical run per column
        run = np.where(row, run + 1, 0)
        best = np.maximum(best, run)
    return best > 0.35 * g.shape[0]


def ctx_box(g, box, wall):
    """Grow box (analysis px: x, y, w, h) along its row to the content that belongs with it."""
    H, W = g.shape
    x, y, w, h = box
    pad = max(6, 0.25 * h)
    y0, y1 = int(max(0, y - pad)), int(min(H, y + h + pad))
    band = g[y0:y1]
    ink = (np.abs(np.diff(band, axis=1)) > 22).any(axis=0)
    ink = np.pad(ink, (0, 1))
    # Everything inside the same card or panel on this row belongs together: mapping and form
    # screens often have a short label ("OT", "Speech") far from its control. A panel border stops
    # the growth; without borders only a very wide empty stretch (30% of the screen) does.
    gap_max = int(0.30 * W)

    def grow(start, step):
        i, last, gap = start, start, 0
        while 0 <= i + step < W:
            i += step
            if wall[i]:
                return last              # stop before a panel border
            if ink[i]:
                last, gap = i, 0
            else:
                gap += 1
                if gap > gap_max:
                    break
        return last

    left = grow(int(max(0, min(W - 1, x))), -1)
    right = grow(int(max(0, min(W - 1, x + w))), 1)
    nx0, nx1 = min(left, x), max(right, x + w)
    # Never frame part of a card: widen to the whole panel the target sits in (between the nearest
    # panel borders). A small panel (dialog, side panel) still gets a zoom; the main page card spans
    # most of the screen, so the camera stays wide there instead of cutting off its labels.
    xa, xb = int(max(0, min(W - 1, x))), int(max(0, min(W - 1, x + w)))
    lw = [i for i in range(0, xa) if wall[i]]
    rw = [i for i in range(xb + 1, W) if wall[i]]
    if lw and rw:
        nx0, nx1 = min(nx0, lw[-1] + 1), max(nx1, rw[0] - 1)
    return nx0, y0, nx1 - nx0, y1 - y0


def add(src, events, size, at=0.4):
    """Add "ctx" to every event with a box (source px). Frames are read in parallel."""
    SW, SH = size
    sc = SW / AW
    AH = round(SH / sc / 2) * 2
    todo = [e for e in events if e.get("box")]
    with ThreadPoolExecutor(6) as pool:
        frames = list(pool.map(lambda e: _gray(src, e["t"] + at, AW, AH), todo))
    walls = {}
    for e, g in zip(todo, frames):
        if g is None:
            continue
        key = id(g)
        walls[key] = barriers(g)
        b = e["box"]
        cx, cy, cw, ch = ctx_box(g, (b["x"] / sc, b["y"] / sc, b["width"] / sc, b["height"] / sc), walls[key])
        e["ctx"] = {"x": round(cx * sc), "y": round(cy * sc), "width": round(cw * sc), "height": round(ch * sc)}
    return events
