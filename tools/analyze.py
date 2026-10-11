"""Find what happens in a raw screen recording, from the pixels alone.

usage: analyze.py <video> <work dir> [--start S --dur D]

One streaming pass at 30 fps, grayscale, 960 px wide (fast; nothing written to disk but results):
  click    the macOS "Show Mouse Clicks" circle (or any click ring): a round, compact change that
           appears and fades at one spot while the rest of the screen holds still
  nav      most of the screen changes at once (new page, modal, big re-render)
  scroll   the screen shifts vertically
  type     small changes repeating along one text line
  change   (fallback when no click indicator is found) a local UI change: zoom target, no ripple

Each event gets a target box (source pixels): for a click, the UI that changed right after it.
Writes work/cues.json (events in the {t, k, x, y, box} schema the renderer uses) and
work/analysis.npz (activity per frame, change heat maps, screen hashes) for tidy.py/retakes.py.
"""
import argparse, json, re, subprocess, sys
from pathlib import Path
import numpy as np
from scipy import ndimage as ndi
from common import duration, ffmpeg, fmt

AW = 960
FPS = 30
ANG = np.linspace(0, 2 * np.pi, 36, endpoint=False)


def video_size(src):
    info = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(src)], capture_output=True, text=True).stderr
    m = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", info)
    return int(m.group(1)), int(m.group(2))


def gray_frames(src, w, h, start=0.0, dur=None, fps=FPS):
    cmd = [ffmpeg(), "-v", "error", "-ss", f"{start:.3f}"] + (["-t", f"{dur:.3f}"] if dur else []) + [
        "-i", str(src), "-vf", f"fps={fps},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=w * h * 8)
    i = 0
    while True:
        b = p.stdout.read(w * h)
        if len(b) < w * h:
            break
        yield start + i / fps, np.frombuffer(b, np.uint8).reshape(h, w)
        i += 1
    p.wait()


DISK = np.add.outer(np.arange(-2, 3) ** 2, np.arange(-2, 3) ** 2) <= 5


def discs(f, p, dmin, dmax):
    """macOS draws a translucent black disc while the button is down: every pixel under it gets
    darker by the same ratio (and brighter by the inverse ratio when it goes). Find round blobs
    with a consistent brightness ratio. Returns [(kind 'down'|'up', cx, cy, diameter)]."""
    q = (f.astype(np.float32) + 4) / (p.astype(np.float32) + 4)
    out = []
    for kind, m in (("down", (q > 0.3) & (q < 0.82)), ("up", (q > 1.22) & (q < 3.4))):
        if not m.any():
            continue
        m = ndi.binary_closing(ndi.binary_opening(m, DISK), DISK)   # drop thin lines (borders, text)
        lab, n = ndi.label(m)
        for i, sl in enumerate(ndi.find_objects(lab), 1):
            h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if not (dmin <= w <= dmax and dmin <= h <= dmax and 0.75 < w / h < 1.33):
                continue
            blob = lab[sl] == i
            fill = blob.sum() / (np.pi * w * h / 4)
            qs = q[sl][blob]
            if fill < 0.6 or qs.std() / qs.mean() > 0.22:
                continue
            out.append((kind, (sl[1].start + sl[1].stop) / 2, (sl[0].start + sl[0].stop) / 2, (w + h) / 2))
    return out


def dhash(f):
    small = f[::f.shape[0] // 9 or 1, ::f.shape[1] // 17 or 1][:9, :17].astype(np.int16)
    return np.packbits(small[:, 1:] > small[:, :-1]).tobytes().hex()


def vshift(a, b, maxs=60):
    """Vertical shift of b relative to a from row-mean profiles; (shift, residual ratio)."""
    cols = slice(a.shape[1] // 5, 4 * a.shape[1] // 5)
    pa, pb = a[:, cols].mean(1), b[:, cols].mean(1)
    base = np.abs(pa - pb).mean() + 1e-6
    best = (0, 1.0)
    for s in range(-maxs, maxs + 1):
        if s == 0:
            continue
        e = np.abs(pa[max(0, s):len(pa) + min(0, s)] - pb[max(0, -s):len(pb) + min(0, -s)]).mean() / base
        if e < best[1]:
            best = (s, e)
    return best


def analyze(src, start=0.0, dur=None):
    SW, SH = video_size(src)
    AH = round(AW * SH / SW / 2) * 2
    sc = SW / AW
    dmin, dmax = max(8, int(14 / sc * 1.5)), int(120 / sc * 1.5) + 20   # click ring size range (analysis px)
    prev, frac, cands, local, hashes = [], [], [], [], []
    heat_nav = np.zeros((AH, AW), np.float32)
    heat_all = np.zeros((AH, AW), np.float32)
    navs, scrolls = [], []
    for t, f in gray_frames(src, AW, AH, start, dur):
        f = f.astype(np.int16)
        if len(prev) >= 2:
            d1 = np.abs(f - prev[-1]); d2 = np.abs(f - prev[-2])
            m1 = d1 > 12
            fr = float(m1.mean())
            heat_all += m1
            if fr > 0.25:
                heat_nav += m1
                s, e = vshift(prev[-1], f)
                if e < 0.35:
                    scrolls.append((t, s * sc))
                else:
                    navs.append(t)
            elif fr > 0.0003:
                lab, n = ndi.label(ndi.binary_dilation(m1, iterations=3))
                for sl in ndi.find_objects(lab):
                    h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
                    if h * w >= 30:
                        local.append((t, sl[1].start, sl[0].start, w, h, fr))
            m2 = d2 > 14
            if fr < 0.06 and m2.any():
                # only look where something changed (fast): crops around each changed region.
                # A click happens on a calm screen; a busy frame (camera motion, page load) is skipped.
                lab, n = ndi.label(ndi.binary_dilation(m2, iterations=3))
                found = []
                for sl in (ndi.find_objects(lab) if n <= 12 else []):
                    h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
                    if h < dmin or w < dmin:
                        continue
                    y0, x0 = max(0, sl[0].start - 4), max(0, sl[1].start - 4)
                    cs = (slice(y0, sl[0].stop + 4), slice(x0, sl[1].stop + 4))
                    found += [(k, x + x0, y + y0, r) for k, x, y, r in discs(f[cs], prev[-2][cs], dmin, dmax)]
                if len(found) <= 2:            # many round blobs at once = icons sliding, not a click
                    cands += [(t, x, y, r, fr, kind) for kind, x, y, r in found]
            frac.append(fr)
        else:
            frac.append(0.0)
        if len(frac) % 15 == 1:
            hashes.append((t, dhash(f)))
        prev = (prev + [f])[-2:]
    end = start + len(frac) / FPS
    return dict(SW=SW, SH=SH, AW=AW, AH=AH, sc=sc, frac=np.array(frac), cands=cands, local=local,
                navs=navs, scrolls=scrolls, hashes=hashes, heat_nav=heat_nav, heat_all=heat_all,
                start=start, end=end)


def debounce(ts, gap):
    out = []
    for t in ts:
        if not out or t - out[-1] > gap:
            out.append(t)
    return out


def clicks_from(cands, frac, start):
    """A click = a disc that appears ('down') and later disappears ('up') at the same spot
    within 3 s. A 'down' with no matching 'up' still counts if it is a clean, isolated disc."""
    downs = [c for c in cands if c[5] == "down"]
    ups = [c for c in cands if c[5] == "up"]
    out = []
    for t, x, y, r, fr, _ in downs:
        if out and t - out[-1]["t0"] < 0.35 and abs(x - out[-1]["x"]) < r and abs(y - out[-1]["y"]) < r:
            continue                                   # same disc seen on consecutive frames
        up = next((u[0] for u in ups if 0.05 < u[0] - t < 3.0 and abs(u[1] - x) < r * 0.6 and abs(u[2] - y) < r * 0.6), None)
        seen = sum(1 for d in downs if 0 <= d[0] - t < 0.3 and abs(d[1] - x) < r * 0.6 and abs(d[2] - y) < r * 0.6)
        if up is not None or seen >= 2:
            out.append({"t0": t, "x": x, "y": y, "r": r, "up": up})
    # a person can't click 3 times in 0.4 s at different spots: a burst is a moving ring or icon
    burst = lambda c: sum(1 for o in out if abs(o["t0"] - c["t0"]) < 0.4) >= 3
    return [c for c in out if not burst(c)]


def union(boxes):
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
    return x0, y0, x1 - x0, y1 - y0


def typing_from(local, AW, AH):
    """Runs of small, short changes inside one text line: [(t0, t1, box)] in analysis px."""
    # Typed text grows rightwards along one baseline in small steps. A moving cursor jumps around
    # and drifts vertically; a blinking caret toggles in place without growing.
    # only calm frames: when much of the screen is moving (a scroll, an animation, a camera move
    # baked into the recording) small changes are not keystrokes
    small = [l for l in local if 3 <= l[4] < AH * 0.05 and l[3] < AW * 0.2 and l[5] < 0.006]
    runs = []
    for t, x, y, w, h, _ in small:
        cy = y + h / 2
        for r in runs:
            if abs(r["cy"] - cy) <= 3 and t - r["t1"] < 1.0 and r["x1"] - 8 <= x + w <= r["x1"] + 40 and x >= r["x0"] - 8:
                if x + w > r["x1"] + 1:
                    r["grow"] += 1
                r["t1"] = t; r["boxes"].append((x, y, w, h)); r["x1"] = max(r["x1"], x + w)
                break
        else:
            runs.append({"t0": t, "t1": t, "cy": cy, "grow": 0, "x0": x, "x1": x + w, "boxes": [(x, y, w, h)]})
    found = sorted((r["t0"], r["t1"], union(r["boxes"])) for r in runs
                   if r["grow"] >= 4 and r["x1"] - r["x0"] >= 20 and r["t1"] - r["t0"] >= 0.6)
    merged = []
    for t0, t1, b in found:                       # one field typed in = one event
        if merged and t0 <= merged[-1][1] + 0.8:
            merged[-1] = (merged[-1][0], max(t1, merged[-1][1]), union([merged[-1][2], b]))
        else:
            merged.append((t0, t1, b))
    return merged


def events_from(a):
    sc, AW, AH = a["sc"], a["AW"], a["AH"]
    frac, start = a["frac"], a["start"]
    S = lambda b: {"x": round(b[0] * sc), "y": round(b[1] * sc), "width": round(b[2] * sc), "height": round(b[3] * sc)}
    navs = debounce(a["navs"], 0.8)
    scrolls = debounce([t for t, _ in a["scrolls"]], 0.8)
    clicks = clicks_from(a["cands"], frac, start)
    typing = typing_from(a["local"], AW, AH)
    ev = [{"t": round(t, 3), "k": "nav"} for t in navs] + [{"t": round(t, 3), "k": "scroll"} for t in scrolls]
    for t0, t1, b in typing:
        ev += [{"t": round(t0, 3), "k": "type", "box": S(b)}, {"t": round(t1, 3), "k": "typeEnd"}]

    def after(t, x, y, lo=0.08, hi=1.2, reach=0.28):
        near = [l[1:] for l in a["local"] if t + lo <= l[0] <= t + hi and
                abs(l[1] + l[3] / 2 - x) < AW * reach and abs(l[2] + l[4] / 2 - y) < AH * reach and
                l[3] < AW * 0.7 and l[4] < AH * 0.7]
        return near

    # a walkthrough with Show Mouse Clicks on has a click every few seconds; a handful of hits in
    # minutes of video means the indicator wasn't recorded, and those hits aren't trustworthy
    mode = "clicks" if len(clicks) >= max(3, (a["end"] - start) / 60) else "changes"
    if mode == "clicks":
        for c in clicks:
            t, x, y = c["t0"], c["x"], c["y"]
            near = after(t, x, y)
            # the click ring itself shows up as a change; ignore boxes that are just the ring
            near = [b for b in near if not (abs(b[0] + b[2] / 2 - x) < c["r"] and abs(b[1] + b[3] / 2 - y) < c["r"] and b[2] < 2.2 * c["r"])]
            e = {"t": round(t, 3), "k": "click", "x": round(x * sc), "y": round(y * sc), "r": round(c["r"] * sc)}
            if c["up"] is not None:
                e["up"] = round(c["up"], 3)
            box = union(near + [(x - 60 / sc, y - 30 / sc, 120 / sc, 60 / sc)]) if near else (x - 160 / sc, y - 90 / sc, 320 / sc, 180 / sc)
            e["box"] = S(box)
            ev.append(e)
    else:
        # no click indicator: local change onsets become zoom targets (no ripple, no click sound)
        typed = [(t0, t1) for t0, t1, _ in typing]
        groups = []
        for t, x, y, w, h, _ in a["local"]:
            if any(t0 - 0.2 <= t <= t1 + 0.5 for t0, t1 in typed) or w * h < 400:
                continue
            if groups and t - groups[-1]["t1"] < 0.6:
                groups[-1]["t1"] = t; groups[-1]["boxes"].append((x, y, w, h))
            else:
                groups.append({"t0": t, "t1": t, "boxes": [(x, y, w, h)]})
        for g in groups:
            b = union(g["boxes"])
            if b[2] * b[3] < 0.5 * AW * AH:
                ev.append({"t": round(g["t0"], 3), "k": "change", "box": S(b)})
    ev.sort(key=lambda e: e["t"])
    return ev, mode


def contact_sheet(src, items, out, cols=4, w=640):
    """items: [(t, label, marks)] with marks [(kind, x, y, w, h)] in source px. One JPEG per 12 items."""
    from PIL import Image, ImageDraw
    from look import font
    from concurrent.futures import ThreadPoolExecutor
    SW, SH = video_size(src)
    h = round(w * SH / SW)
    k = w / SW

    def grab(t):
        return subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(src), "-frames:v", "1",
                               "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              capture_output=True).stdout

    with ThreadPoolExecutor(6) as pool:
        raws = list(pool.map(grab, [it[0] for it in items]))
    sheets = []
    for s in range(0, len(items), 12):
        part = items[s:s + 12]
        rows = (len(part) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * w, rows * h), (20, 20, 20))
        for i, (t, label, marks) in enumerate(part):
            raw = raws[s + i]
            if len(raw) < w * h * 3:
                continue
            im = Image.frombytes("RGB", (w, h), raw)
            d = ImageDraw.Draw(im)
            for kind, x, y, bw, bh in marks:
                if kind == "box":
                    d.rectangle((x * k, y * k, (x + bw) * k, (y + bh) * k), outline=(255, 210, 0), width=3)
                else:
                    d.ellipse((x * k - 9, y * k - 9, x * k + 9, y * k + 9), outline=(255, 40, 90), width=4)
            d.rectangle((0, 0, w, 26), fill=(0, 0, 0))
            d.text((6, 3), label, font=font(18), fill=(255, 230, 120))
            sheet.paste(im, ((i % cols) * w, (i // cols) * h))
        p = Path(str(out).replace(".jpg", f"_{s // 12 + 1}.jpg"))
        sheet.save(p, quality=85)
        sheets.append(p)
    return sheets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("work")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--no-sheets", action="store_true")
    o = ap.parse_args()
    work = Path(o.work); (work / "frames").mkdir(parents=True, exist_ok=True)
    a = analyze(o.video, o.start, o.dur)
    ev, mode = events_from(a)
    (work / "cues.json").write_text(json.dumps({"source": str(o.video), "size": [a["SW"], a["SH"]], "mode": mode,
                                                "events": ev}, indent=1))
    np.savez_compressed(work / "analysis.npz", frac=a["frac"], heat_nav=a["heat_nav"], heat_all=a["heat_all"],
                        start=a["start"], sc=a["sc"], hash_t=np.array([t for t, _ in a["hashes"]]),
                        hash_v=np.array([h for _, h in a["hashes"]]))
    from collections import Counter
    print(f"mode: {mode}  " + ", ".join(f"{k} {n}" for k, n in Counter(e['k'] for e in ev).items()))
    if not o.no_sheets:
        items = []
        for e in ev:
            if e["k"] in ("click", "type", "change"):
                b = e.get("box")
                marks = ([("box", b["x"], b["y"], b["width"], b["height"])] if b else []) + \
                        ([("dot", e["x"], e["y"], 0, 0)] if "x" in e else [])
                items.append((e["t"] + 0.12, f"{fmt(e['t'])} {e['k']}", marks))
        for p in contact_sheet(o.video, items, work / "frames" / "events.jpg"):
            print("  ", p)


if __name__ == "__main__":
    main()
