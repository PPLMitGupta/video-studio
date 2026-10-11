"""Tidy the frame: find the app's page area and crop away browser tabs, address bar, menu bar, dock.

When the page changes (navigation, modal, re-render) nearly the whole page area changes at once,
while the browser chrome around it only changes a little (the URL text, a tab title). So the page
area is the rectangle where most of the change happens during those big moments.

usage: tidy.py <video> <work dir>   (needs work/analysis.npz from analyze.py)
Writes the proposed crop [x, y, w, h] (source px) to stdout and work/frames/tidy_rect.jpg.
"""
import argparse, subprocess, sys
from pathlib import Path
import numpy as np
from scipy import ndimage as ndi
from common import ffmpeg


def runs(mask):
    """(start, stop) of runs of True."""
    d = np.diff(np.r_[0, mask.astype(int), 0])
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def content_rect(heat_nav, heat_all, sc, SW, SH):
    h = heat_nav if heat_nav.max() > 0 and heat_nav.sum() > 50 * heat_nav.shape[1] else heat_all
    if h.max() <= 0:
        return [0, 0, SW, SH]
    h = ndi.uniform_filter(h / h.max(), 5)
    AH, AW = h.shape
    rows = h.mean(1); cols = h.mean(0)
    # Be conservative: a static part of the app (a sidebar, empty space under a short page) must
    # never be cropped. Top: cut only the band above where page-wide change starts (tabs, address
    # bar, menu bar). Bottom and sides: cut only bands where nothing ever changes (wallpaper, Dock).
    rp, cp = np.percentile(rows, 90), np.percentile(cols, 90)
    y0 = int(np.argmax(rows > 0.25 * rp))
    y0 = y0 if y0 < AH * 0.25 else 0
    dead_r, dead_c = rows < 0.01 * rp, cols < 0.01 * cp
    y1 = AH - (runs(dead_r)[-1][1] - runs(dead_r)[-1][0] if dead_r[-1] else 0)
    x0 = runs(dead_c)[0][1] if dead_c[0] else 0
    x1 = AW - (runs(dead_c)[-1][1] - runs(dead_c)[-1][0] if dead_c[-1] else 0)
    if AH - y1 > AH * 0.15: y1 = AH
    if x0 > AW * 0.2: x0 = 0
    if AW - x1 > AW * 0.2: x1 = AW
    # nothing to gain from trimming a sliver: keep edges within 1.5% of the frame
    if y0 < AH * 0.015: y0 = 0
    if x0 < AW * 0.015: x0 = 0
    if y1 > AH * 0.985: y1 = AH
    if x1 > AW * 0.985: x1 = AW
    x, y, w, hh = [int(round(v * sc)) for v in (x0, y0, x1 - x0, y1 - y0)]
    x, y = x // 2 * 2, y // 2 * 2
    w, hh = min(SW - x, w) // 2 * 2, min(SH - y, hh) // 2 * 2
    if w * hh < 0.3 * SW * SH:          # implausibly small: don't crop
        return [0, 0, SW, SH]
    return [x, y, w, hh]


def preview(src, crop, out, t):
    from PIL import Image, ImageDraw
    from analyze import video_size
    SW, SH = video_size(src)
    w = 960; h = round(w * SH / SW); k = w / SW
    raw = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                          "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    im = Image.frombytes("RGB", (w, h), raw)
    dim = Image.eval(im, lambda v: v // 3)
    x, y, cw, ch = crop
    box = (int(x * k), int(y * k), int((x + cw) * k), int((y + ch) * k))
    dim.paste(im.crop(box), box[:2])
    ImageDraw.Draw(dim).rectangle(box, outline=(255, 210, 0), width=3)
    dim.save(out, quality=88)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("work")
    o = ap.parse_args()
    work = Path(o.work)
    a = np.load(work / "analysis.npz")
    from analyze import video_size
    SW, SH = video_size(o.video)
    crop = content_rect(a["heat_nav"], a["heat_all"], float(a["sc"]), SW, SH)
    frac = a["frac"]
    t = float(a["start"]) + (int(np.argmin(np.abs(frac - np.median(frac)) + (np.arange(len(frac)) < len(frac) * 0.3))) / 30)
    preview(o.video, crop, work / "frames" / "tidy_rect.jpg", t)
    print(crop)


if __name__ == "__main__":
    main()
