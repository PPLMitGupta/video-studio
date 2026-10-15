"""Screen-Studio-style polish for a recorded walkthrough.

Reads the screencast frames (work/frames.txt) and the action log (work/cues.json) written by
recorder.mjs, and renders work/recording_polished.mp4 on the SAME timeline as the raw recording,
so build.py's speed-ups and narration placement still apply unchanged.

  auto zoom     eases in on clicks, typing and highlights; stays wide while pages load
  framing       the app in a rounded window with a soft shadow on a gradient
  transitions   fade in/out, cross-fade when the camera switches page (role or title card)
  chapters      a pill label as each part starts (project.json "chapters": {cue id: label})

usage: polish.py <project> [--start S --dur D --out FILE]   (start/dur: a preview range in raw seconds)

Tuning lives in project.json "polish" (all optional):
  zoom "auto"         "auto", "gentle" (at most 1.25x) or "off"
  zmax 1.5            strongest zoom; above ~1.6 viewers lose their place
  zmin 1.2            smaller zooms are skipped (they only add motion)
  content_center .61  where the main content column sits, as a fraction of the width; the camera
                      leans toward it so a form isn't cut off when the target is near its left edge
  hold 3.0            seconds to stay zoomed after the last action before easing back out
  bg ["#1e2234", "#5c213e"], pill_dot "#e8476e"
"""
import argparse, json, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from _common import ffmpeg, load_config, project

FPS = 30
OW, OH = 1920, 1080
WIN_X, WIN_Y, WIN_W, WIN_H = 80, 45, 1760, 990
RADIUS = 22


def hexrgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def load(work):
    c = json.loads((work / "cues.json").read_text())
    lines = (work / "frames.txt").read_text().splitlines()
    frames, t = [], 0.0
    for i in range(0, len(lines) - 1, 2):
        frames.append((t, lines[i].split("'")[1]))
        t += float(lines[i + 1].split()[1])
    return c, frames, t


# ---------------------------------------------------------------- camera director
# Shared with polish-recording (tools/render.py): frames each target together with the content on
# its row (tools/context.py), groups quick actions into one move, and skips pointless small zooms.
from render import camera_path, targets  # noqa: E402
import context  # noqa: E402


# ---------------------------------------------------------------- static layers
def base_layers(bg_colors):
    g = np.linspace(0, 1, OW)[None, :] * 0.55 + np.linspace(0, 1, OH)[:, None] * 0.45
    c0, c1 = np.array(hexrgb(bg_colors[0])), np.array(hexrgb(bg_colors[1]))
    bg = Image.fromarray((c0 * (1 - g[..., None]) + c1 * g[..., None]).astype(np.uint8), "RGB")
    glow = Image.new("L", (OW, OH), 0)
    ImageDraw.Draw(glow).ellipse((-300, -500, 1100, 600), fill=60)
    bg = Image.composite(Image.new("RGB", (OW, OH), (255, 255, 255)), bg, glow.filter(ImageFilter.GaussianBlur(160)))
    sh = Image.new("L", (OW, OH), 0)
    ImageDraw.Draw(sh).rounded_rectangle((WIN_X, WIN_Y + 18, WIN_X + WIN_W, WIN_Y + WIN_H + 18), RADIUS, fill=140)
    bg = Image.composite(Image.new("RGB", (OW, OH), (8, 10, 18)), bg, sh.filter(ImageFilter.GaussianBlur(28)))
    mask = Image.new("L", (WIN_W, WIN_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, WIN_W - 1, WIN_H - 1), RADIUS, fill=255)
    return bg, mask


def font(size):
    for f in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def pill(text, dot):
    f = font(30)
    w = int(f.getlength(text)) + 64
    img = Image.new("RGBA", (w, 62), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, 61), 31, fill=(22, 26, 38, 232))
    d.ellipse((24, 25, 36, 37), fill=(*hexrgb(dot), 255))
    d.text((48, 13), text, font=f, fill=(255, 255, 255, 255))
    return img


# ---------------------------------------------------------------- render
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    proj = project(a.project); work = proj / "work"
    cfg = load_config(proj)
    opt = {"zoom": "auto", "zmax": 1.5, "zmin": 1.2, "settle": 1.9, "content_center": 0.61, "hold": 3.0,
           "bg": ["#1e2234", "#5c213e"], "pill_dot": "#e8476e"}
    opt.update(cfg.get("polish", {}))
    c, frames, end = load(work)
    SW, SH = Image.open(frames[0][1]).size
    n = int(end * FPS)
    if opt["zoom"] != "off" and c.get("ctx_version") != context.VERSION:
        print("reading the screen around each action (context-aware zoom)...")
        context.add(work / "recording.mp4", c["events"], (SW, SH))
        c["ctx_version"] = context.VERSION
        (work / "cues.json").write_text(json.dumps(c, indent=1))
    z, cx, cy = camera_path(targets(c["events"], end, SW, SH, opt), n, SW, SH)
    bg, mask = base_layers(opt["bg"])
    cuts = [e["t"] for e in c["events"] if e["k"] == "cut" and not e.get("first")]
    chapters = [(q["t"], pill(cfg["chapters"][q["id"]], opt["pill_dot"])) for q in c["cues"] if q["id"] in cfg.get("chapters", {})]
    out_path = a.out or str(work / "recording_polished.mp4")

    i0 = int(a.start * FPS); i1 = n if a.dur is None else min(n, i0 + int(a.dur * FPS))
    enc = subprocess.Popen([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                            "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path], stdin=subprocess.PIPE)
    fi, cache, prev, xf_from, xf_t = 0, {}, None, None, -1
    for i in range(i0, i1):
        t = i / FPS
        while fi + 1 < len(frames) and frames[fi + 1][0] <= t:
            fi += 1
        src = cache.get(frames[fi][1])
        if src is None:
            src = Image.open(frames[fi][1]).convert("RGB"); cache = {frames[fi][1]: src}
        vw, vh = SW / z[i], SH / z[i]
        box = (cx[i] - vw / 2, cy[i] - vh / 2, cx[i] + vw / 2, cy[i] + vh / 2)
        win = src.resize((WIN_W, WIN_H), Image.LANCZOS if z[i] > 1.01 else Image.BILINEAR, box=box)
        out = bg.copy(); out.paste(win, (WIN_X, WIN_Y), mask)
        for ct, p in chapters:
            # lower-left corner of the window (over the app's sidebar footer), not the middle of
            # the page where it covered the rows being talked about
            if ct - 0.2 <= t <= ct + 3.2:
                k = max(0.0, min(1.0, (t - ct + 0.2) / 0.35, (ct + 3.2 - t) / 0.4))
                layer = p.copy(); layer.putalpha(layer.getchannel("A").point(lambda v: int(v * k)))
                out.paste(layer, (WIN_X + 24 - int((1 - k) * 14), WIN_Y + WIN_H - p.height - 24), layer)
        if prev is not None and any(0 <= t - ct < 1 / FPS for ct in cuts):
            xf_from, xf_t = prev, t
        if xf_from is not None and t - xf_t < 0.45:
            out = Image.blend(xf_from, out, (t - xf_t) / 0.45)
        else:
            xf_from = None
        fade = min(1.0, t / 0.6, (end - t) / 0.9)
        if fade < 1.0:
            out = Image.blend(Image.new("RGB", (OW, OH)), out, max(0.0, fade))
        prev = out
        enc.stdin.write(out.tobytes())
        if (i - i0) % 1800 == 0:
            print(f"  {t / 60:.1f} min", flush=True)
    enc.stdin.close(); enc.wait()
    print("wrote", out_path, f"({(i1 - i0) / FPS:.1f}s)")


if __name__ == "__main__":
    main()
