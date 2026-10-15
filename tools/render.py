"""Render the finished video in one pass (one lossy encode).

decoder ffmpeg   crop to the app, drop cut ranges, apply speed-ups -> frames on the content timeline
python (PIL)     intro card, camera (auto-zoom), framed window, click ripples (the macOS click circle is
                 removed underneath), spotlight, step titles, cross-fades at cuts, holds, outro card
encoder ffmpeg   burns the .ass captions, normalises the voice + sound-effects mix, x264 CRF 18

The camera director (targets/camera_path) comes from walkthrough-video's polish.py: it runs on the
OUTPUT timeline, so zooms move at viewing speed even inside 3x stretches.
"""
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from common import ffmpeg
from look import FPS, OH, OW, base_layers, hexrgb, step_label, window_rect, with_alpha

MAX_DECODE_W = 2560   # enough for a crisp 1.5x zoom in a 1664 px window


# ---------------------------------------------------------------- camera director
def targets(ev, end, SW, SH, opt):
    """Piecewise camera targets (t, zoom, cx, cy) in content pixels, from events on the output timeline.

    Zoom only where it helps, and never at the cost of context:
      - frame each event's "ctx" box (the change plus what belongs with it on its row, from
        context.py) rather than the bare change, so a dropdown keeps its label in view
      - changes less than 1.5 s apart are one moment: frame them together, move once
      - skip zooms below zmin (a small zoom is just motion); stay wide after page changes
      - opt["zoom"]: "auto" (default), "gentle" (at most 1.25x) or "off"
    """
    mode = opt.get("zoom", "auto")
    wide = (0.0, 1.0, SW / 2, SH / 2)
    if mode == "off":
        return [wide]
    ZMAX = min(opt["zmax"], 1.25) if mode == "gentle" else opt["zmax"]
    ZMIN, PREF, HOLD = opt.get("zmin", 1.2), opt["content_center"], opt["hold"]
    keys = [wide + (0.0,)]                 # (t, z, cx, cy, active until)

    def focus(box):
        x, y, w, h = box["x"], box["y"], box["width"], box["height"]
        need_w = max(w + 0.14 * SW, SW / ZMAX)
        need_h = max(h + 0.16 * SH, SH / ZMAX)
        z = max(1.0, min(ZMAX, SW / need_w, SH / need_h))
        vw = SW / z
        lo, hi = (x + w) - vw / 2 + 0.05 * vw, x + vw / 2 - 0.05 * vw
        cx = min(max(PREF * SW, lo), hi) if lo <= hi else x + w / 2
        return z, cx, y + h / 2

    def inside(box, cur):
        if cur is None:
            return False
        z, cx, cy = cur
        vw, vh = SW / z, SH / z
        return (box["x"] >= cx - vw * .46 and box["y"] >= cy - vh * .44 and
                box["x"] + box["width"] <= cx + vw * .46 and box["y"] + box["height"] <= cy + vh * .44)

    def union(boxes):
        x0 = min(b["x"] for b in boxes); y0 = min(b["y"] for b in boxes)
        x1 = max(b["x"] + b["width"] for b in boxes); y1 = max(b["y"] + b["height"] for b in boxes)
        return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}

    # 1. group events into moments: boxed events less than 1.5 s apart, with no page change between.
    #    Works for both pipelines: polish-recording (click/change/type from pixels) and
    #    walkthrough-video (move/click/spot/type from the recorder's log, cuts to title cards, "pre").
    settle = opt.get("settle", 1.2)          # seconds to stay wide after a page change
    moments, last_nav, on_card = [], -9, False
    for e in ev:
        t = e["t"]
        if e["k"] in ("nav", "scroll", "cut", "pre"):
            keys.append((t, 1.0, SW / 2, SH / 2, t))
            moments.append(None)
            if e["k"] == "cut":
                on_card = bool(e.get("card"))
            if e["k"] != "scroll":
                last_nav = t
            continue
        b = e.get("ctx") or e.get("box")
        if on_card or not b or (e["k"] in ("click", "change", "move") and t - last_nav < settle):
            continue  # a title card, nothing to frame, or the page is still loading: stay wide
        m = moments[-1] if moments else None
        if m is not None and t - m["t1"] < 1.5:
            m["t1"] = t; m["boxes"].append(b)
        else:
            moments.append({"t0": t, "t1": t, "boxes": [b]})

    # 2. one framing per moment
    cur, last_focus_t = None, -9
    for m in moments:
        if m is None:
            cur = None
            continue
        u = union(m["boxes"])
        if inside(u, cur):
            keys.append((m["t0"], *cur, m["t1"])); last_focus_t = m["t1"]
            continue  # already framed: hold still rather than drift
        z, cx, cy = focus(u)
        if z < ZMIN:
            if cur is not None:            # the next thing needs the full view: ease back out
                keys.append((m["t0"], 1.0, SW / 2, SH / 2, m["t1"])); cur = None
            continue
        lead = 0.3 if m["t0"] - last_focus_t > 1.5 else 0.0
        keys.append((max(0.0, m["t0"] - lead), z, cx, cy, m["t1"]))
        cur, last_focus_t = (z, cx, cy), m["t1"]

    # 3. zoom back out HOLD seconds after the last activity in a framing
    keys.sort(key=lambda k: k[0])
    out = []
    for i, k in enumerate(keys):
        if out and out[-1][1:] == k[1:4]:
            continue
        out.append(k[:4])
        nxt = keys[i + 1][0] if i + 1 < len(keys) else end
        if k[1] > 1.0 and nxt - k[4] > HOLD + 0.8:
            out.append((k[4] + HOLD, 1.0, SW / 2, SH / 2))
    return out


def camera_path(keys, n, SW, SH):
    """Sample targets per frame, then smooth with a critically damped spring (no jerks, no overshoot)."""
    tz = np.ones(n); tx = np.full(n, SW / 2); ty = np.full(n, SH / 2)
    j = 0
    for i in range(n):
        t = i / FPS
        while j + 1 < len(keys) and keys[j + 1][0] <= t:
            j += 1
        _, tz[i], tx[i], ty[i] = keys[j]

    def spring(target, w):
        x, v, out, dt = target[0], 0.0, np.empty_like(target), 1 / FPS
        for i, g in enumerate(target):
            v += (w * w * (g - x) - 2 * w * v) * dt; x += v * dt; out[i] = x
        return out

    z = np.exp(spring(np.log(tz), 4.2))
    x, y = spring(tx, 4.6), spring(ty, 4.6)
    vw, vh = SW / z, SH / z
    return z, np.clip(x, vw / 2, SW - vw / 2), np.clip(y, vh / 2, SH - vh / 2)


# ---------------------------------------------------------------- click circle removal
def unblend_disc(frame, clean, x, y, r, q_cal=None):
    """Undo the macOS click circle (black, translucent) at (x, y), radius r, in place.
    The circle scales the pixels under it by a constant q (the same for the whole recording), so
    dividing q back out restores them, whatever is underneath. q is measured against the frame just
    before the click when that is still comparable, otherwise the recording's calibrated q is used.
    Returns the q used, or None if no circle was found on this frame."""
    H, W = frame.shape[:2]
    R = int(r * 1.25) + 3
    x0, x1, y0, y1 = max(0, int(x) - R), min(W, int(x) + R), max(0, int(y) - R), min(H, int(y) + R)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(xx - x, yy - y)
    cur = frame[y0:y1, x0:x1].astype(np.float32)
    in_ring = (d > r - 5) & (d < r - 2)
    out_ring = (d > r + 2) & (d < r + 5)
    q = None
    if clean is not None:
        ref = clean[y0:y1, x0:x1].astype(np.float32)
        ring = (d > r * 0.55) & (d < r * 0.9) & (ref.mean(2) > 40)      # skip the cursor in the middle
        if ring.sum() >= 20:
            qs = (cur[ring] + 4) / (ref[ring] + 4)
            if 0.25 < np.median(qs) < 0.92 and np.std(qs) < 0.12:
                q = float(np.median(qs))
    if q is None and in_ring.any() and out_ring.any():
        # no usable reference (the page changed under the click): on a plain background the circle's
        # own edge shows how dark it is. Use the recording's calibrated value when there is one.
        # medians and the middle half of the values, so the cursor crossing the edge doesn't count
        vi, vo = cur[in_ring].mean(1), cur[out_ring].mean(1)
        spread = lambda v: np.percentile(v, 75) - np.percentile(v, 25)
        # (the cursor or another ring inside the circle only makes some pixels darker, so read the
        # circle's darkness from the brighter quarter of the inner edge)
        flat = spread(vo) < 10
        edge = (np.percentile(vi, 75) + 4) / (np.median(vo) + 4)
        if q_cal is not None and abs(edge - q_cal) < 0.12:
            q = q_cal
        elif q_cal is None and flat and 0.3 < edge < 0.85:
            q = float(edge)
    if q is None:
        return None
    a = np.clip(r + 0.8 - d, 0, 1)[..., None]                           # anti-aliased disc mask
    fixed = cur / (1 - a * (1 - q))
    frame[y0:y1, x0:x1] = np.clip(fixed, 0, 255).astype(np.uint8)
    return q


def ripple(img, x, y, k, accent):
    """Expanding accent ring + soft fill; k runs 0 -> 1 over the ripple's life."""
    e = 1 - (1 - k) ** 3
    r = 12 + 40 * e
    a = (1 - k) ** 1.3
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    col = hexrgb(accent)
    d.ellipse((x - r * 0.62, y - r * 0.62, x + r * 0.62, y + r * 0.62), fill=(*col, int(70 * a)))
    d.ellipse((x - r, y - r, x + r, y + r), outline=(*col, int(235 * a)), width=4)
    img.paste(layer, (0, 0), layer)


def spotlight(win, box, k, dim):
    """Darken everything in the window except a feathered rounded box (window pixels)."""
    w, h = win.size
    m = Image.new("L", (w, h), 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(m).rounded_rectangle((x0 - 18, y0 - 14, x1 + 18, y1 + 14), 16, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(10))
    dark = Image.eval(win, lambda v: int(v * (1 - dim * k)))
    return Image.composite(win, dark, m)


# ---------------------------------------------------------------- render
class Render:
    def __init__(self, src, crop, tl, events, brand, opt, steps=(), spots=(), intro=None, outro=None):
        self.src, self.tl, self.brand, self.opt = src, tl, brand, opt
        cx, cy, cw, ch = crop
        s = min(1.0, MAX_DECODE_W / cw)
        self.dw, self.dh = int(cw * s) // 2 * 2, int(ch * s) // 2 * 2
        self.crop, self.s = crop, s
        self.rect = window_rect(self.dw, self.dh)
        self.bg, self.mask = base_layers(brand["colors"]["bg"], self.rect)
        self.intro, self.outro = intro, outro
        self.accent = brand["colors"]["accent"]

        def to_content(e):
            out = dict(e)
            out["t"] = tl.map(e["t"])
            if "x" in e:
                out["x"], out["y"] = (e["x"] - cx) * s, (e["y"] - cy) * s
            if "r" in e:
                out["r"] = e["r"] * s
            for k in ("box", "ctx"):
                if e.get(k):
                    b = e[k]
                    out[k] = {"x": (b["x"] - cx) * s, "y": (b["y"] - cy) * s, "width": b["width"] * s, "height": b["height"] * s}
            return out

        live = [e for e in events if not tl.in_cut(e["t"]) and e["t"] < tl.src_dur]
        self.ev = [to_content(e) for e in live]
        self.ev += [{"t": T, "k": "cut"} for T in tl.cut_points()]
        self.spots = [(tl.map(sp["t"]), sp.get("dur", 2.5), to_content({"t": sp["t"], "box": sp["box"]})["box"]) for sp in spots]
        self.ev += [{"t": T, "k": "spot", "box": b} for T, _, b in self.spots]
        self.ev.sort(key=lambda e: e["t"])
        self.clicks = [e for e in self.ev if e["k"] == "click"]
        # the macOS circle lives from mouse-down to mouse-up (content time = output time minus intro/holds)
        self.discs = [(to_content(x), tl.content(x["t"]), tl.content(x.get("up", x["t"] + 0.35)))
                      for x in live if x["k"] == "click"]
        self.steps = [(T, step_label(txt, self.accent)) for T, txt in steps]
        self.n = int(round(tl.out_dur * FPS))
        self.cam = camera_path(targets(self.ev, tl.out_dur, self.dw, self.dh, opt), self.n, self.dw, self.dh)

    def decoder(self):
        cx, cy, cw, ch = self.crop
        vf = f"crop={cw}:{ch}:{cx}:{cy},{self.tl.ffmpeg_filter()},scale={self.dw}:{self.dh}:flags=lanczos,format=rgb24"
        return subprocess.Popen([ffmpeg(), "-v", "error", "-i", str(self.src), "-vf", vf, "-f", "rawvideo", "-"],
                                stdout=subprocess.PIPE, bufsize=self.dw * self.dh * 3 * 4)

    def compose(self, i, src_img):
        z, cx, cy = self.cam[0][i], self.cam[1][i], self.cam[2][i]
        T = i / FPS
        WX, WY, WW, WH = self.rect
        vw, vh = self.dw / z, self.dh / z
        box = (cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2)
        win = src_img.resize((WW, WH), Image.LANCZOS if z > 1.01 else Image.BILINEAR, box=box)
        to_win = lambda x, y: ((x - box[0]) * WW / vw, (y - box[1]) * WH / vh)
        for T0, dur, b in self.spots:
            if T0 - 0.3 <= T <= T0 + dur + 0.3:
                k = max(0.0, min(1.0, (T - T0 + 0.3) / 0.3, (T0 + dur + 0.3 - T) / 0.3))
                (x0, y0), (x1, y1) = to_win(b["x"], b["y"]), to_win(b["x"] + b["width"], b["y"] + b["height"])
                win = spotlight(win, (x0, y0, x1, y1), k, self.brand.get("spotlight_dim", 0.55))
        out = self.bg.copy()
        out.paste(win, (WX, WY), self.mask)
        for e in self.clicks:
            if e["t"] <= T < e["t"] + 0.55:
                x, y = to_win(e["x"], e["y"])
                if 0 <= x < WW and 0 <= y < WH:
                    ripple(out, WX + x, WY + y, (T - e["t"]) / 0.55, self.accent)
        for T0, lab in self.steps:
            if T0 - 0.2 <= T <= T0 + 3.8:
                k = max(0.0, min(1.0, (T - T0 + 0.2) / 0.35, (T0 + 3.8 - T) / 0.4))
                layer = with_alpha(lab, k)
                out.paste(layer, (WX + 28 - int((1 - k) * 16), WY + WH - lab.height - 28), layer)
        return out

    def run(self, out_path, audio_path, ass_path=None, cwd=None, preview=None):
        """preview=(start, dur) in output seconds renders only that range (no audio sync promise)."""
        p0, p1 = (0, self.n) if not preview else (int(preview[0] * FPS), min(self.n, int(sum(preview) * FPS)))
        # captions are timed on the full output: in a preview, shift them along with the cut
        vf = "[0:v]" + (f"setpts=PTS+{p0 / FPS:.3f}/TB,ass={ass_path.name}:fontsdir=/System/Library/Fonts,setpts=PTS-STARTPTS,"
                        if ass_path else "") + "format=yuv420p[v]"
        enc_cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                   "-ss", f"{p0 / FPS:.3f}", "-i", str(audio_path)]
        enc_cmd += ["-filter_complex", vf + f";[1:a]loudnorm=I={self.opt['loudness']}:TP=-1.5:LRA=11,aresample=48000,apad[a]",
                    "-map", "[v]", "-map", "[a]", "-t", f"{(p1 - p0) / FPS:.3f}",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(out_path)]
        enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, cwd=cwd)
        dec = self.decoder()
        fsize = self.dw * self.dh * 3
        clean_at = {max(0, int(d0 * FPS) - 2): k for k, (_, d0, _) in enumerate(self.discs)}
        cleans = {}                       # disc index -> frame just before its click circle appeared
        qs_seen = []                      # circle darkness measured so far (calibrates later clicks)
        cur_idx, cur = -1, None
        tl = self.tl
        cuts = set(round(T * FPS) for T in tl.cut_points())
        content_start = round(tl.intro * FPS)
        outro_start = round((tl.out_dur - tl.outro) * FPS) if tl.outro else self.n + 1
        prev, xf_from, xf_i = None, None, -99
        for i in range(self.n):
            T = i / FPS
            c, kind = tl.at_out(T)
            if kind in ("content", "hold"):
                want = min(int(round(c * FPS)), int(tl.content_dur * FPS) - 1)
                while cur_idx < want:
                    b = dec.stdout.read(fsize)
                    if len(b) < fsize:
                        want = cur_idx
                        break
                    cur_idx += 1
                    cur = np.frombuffer(b, np.uint8).reshape(self.dh, self.dw, 3).copy()
                    if cur_idx in clean_at:
                        cleans[clean_at[cur_idx]] = cur
            if i < p0:
                continue
            if kind == "intro" and self.intro:
                img = self.intro.frame(T)
            elif kind == "outro" and self.outro:
                img = self.outro.frame(T - tl.out_dur + tl.outro)
            else:
                frame = cur.copy()
                cc = cur_idx / FPS
                for k, (e, d0, d1) in enumerate(self.discs):
                    if d0 - 0.04 <= cc <= d1 + 0.1:
                        q = unblend_disc(frame, cleans.get(k), e["x"], e["y"], e.get("r", 40 * self.s) / 2,
                                         float(np.median(qs_seen)) if len(qs_seen) >= 3 else None)
                        if q is not None and cleans.get(k) is not None:
                            qs_seen.append(q)
                img = self.compose(i, Image.fromarray(frame))
            # transitions: card <-> content and at every cut, a short cross-fade
            if i in (content_start, outro_start) or i in cuts:
                if prev is not None:
                    xf_from, xf_i = prev, i
            span = 0.5 if xf_i in (content_start, outro_start) else 0.4
            if xf_from is not None and (i - xf_i) / FPS < span:
                img = Image.blend(xf_from, img, (i - xf_i) / FPS / span)
            elif xf_from is not None:
                xf_from = None
            fade = min(1.0, T / 0.4, (tl.out_dur - T) / 0.6)
            if fade < 1.0:
                img = Image.blend(Image.new("RGB", (OW, OH)), img, max(0.0, fade))
            prev = img
            enc.stdin.write(img.tobytes())
            if i >= p1 - 1:
                break
            if i % (FPS * 60) == 0 and i:
                print(f"  rendered {i / FPS / 60:.0f} min", flush=True)
        enc.stdin.close(); enc.wait(); dec.kill()
        if enc.returncode:
            raise SystemExit("encoder failed")
