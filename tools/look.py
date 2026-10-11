"""Brand settings and the shared visual pieces: fonts, gradient background, window frame, labels."""
import copy, json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from common import HOME, ROOT

OW, OH = 1920, 1080
FPS = 30
MAX_W, MAX_H, TOP = 1664, 936, 36     # window area; the band below it holds captions
RADIUS = 20

DEFAULT_BRAND = {
    "name": "SIMMS",
    "logo": None,                       # path to a PNG (transparent background works best)
    "colors": {"bg": ["#1e2234", "#5c213e"], "accent": "#c8104a", "text": "#ffffff",
               "muted": "#c9cbd6", "caption_bg": "#11131c", "caption_text": "#ffffff"},
    "intro": {"enabled": True, "dur": 3.0, "title": None, "subtitle": None},
    "outro": {"enabled": True, "dur": 3.0, "title": "Thanks for watching", "lines": [], "url": ""},
    "captions": {"burn": True, "size": 34, "max_chars": 72, "font_name": "Helvetica Neue"},
    "sfx": {},
    "spotlight_dim": 0.45,
}


def merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_brand(cfg):
    """Defaults < team brand.json (in the plugin) < personal ~/VideoStudio/brand.json < project."""
    b = DEFAULT_BRAND
    for p in (ROOT / "brand.json", HOME / "brand.json"):
        if p.exists():
            b = merge(b, json.loads(p.read_text()))
    b = merge(b, cfg.get("brand", {}))
    if b.get("logo") and not Path(b["logo"]).expanduser().is_absolute():
        b["logo"] = str(ROOT / b["logo"])          # logos in the repo are given relative to it
    return b


def hexrgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def font(size, weight="Regular"):
    for f in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(f).exists():
            ft = ImageFont.truetype(f, size)
            try:
                ft.set_variation_by_name(weight)
            except Exception:
                pass
            return ft
    return ImageFont.load_default()


def window_rect(cw, ch):
    """Window (x, y, w, h) for content of size cw x ch: as large as fits MAX_W x MAX_H, same aspect."""
    a = cw / ch
    w, h = (MAX_W, round(MAX_W / a)) if a >= MAX_W / MAX_H else (round(MAX_H * a), MAX_H)
    w -= w % 2; h -= h % 2
    return (OW - w) // 2, TOP + (MAX_H - h) // 2, w, h


def gradient(colors):
    g = np.linspace(0, 1, OW)[None, :] * 0.55 + np.linspace(0, 1, OH)[:, None] * 0.45
    c0, c1 = np.array(hexrgb(colors[0])), np.array(hexrgb(colors[1]))
    bg = Image.fromarray((c0 * (1 - g[..., None]) + c1 * g[..., None]).astype(np.uint8), "RGB")
    glow = Image.new("L", (OW, OH), 0)
    ImageDraw.Draw(glow).ellipse((-300, -500, 1100, 600), fill=60)
    return Image.composite(Image.new("RGB", (OW, OH), (255, 255, 255)), bg, glow.filter(ImageFilter.GaussianBlur(160)))


def base_layers(colors, rect):
    """Background with the window's soft shadow, plus the window's rounded mask."""
    x, y, w, h = rect
    bg = gradient(colors)
    sh = Image.new("L", (OW, OH), 0)
    ImageDraw.Draw(sh).rounded_rectangle((x, y + 16, x + w, y + h + 16), RADIUS, fill=140)
    bg = Image.composite(Image.new("RGB", (OW, OH), (8, 10, 18)), bg, sh.filter(ImageFilter.GaussianBlur(26)))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), RADIUS, fill=255)
    return bg, mask


def step_label(text, accent):
    """Lower-third step title: a dark rounded card with an accent bar."""
    f, fs = font(30, "Semibold"), font(19, "Medium")
    kicker, _, title = text.partition(" · ") if " · " in text else ("", "", text)
    w = int(max(f.getlength(title), fs.getlength(kicker.upper()) if kicker else 0)) + 70
    h = 92 if kicker else 66
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), 16, fill=(18, 21, 32, 236))
    d.rounded_rectangle((16, 16, 22, h - 17), 3, fill=(*hexrgb(accent), 255))
    if kicker:
        d.text((40, 14), kicker.upper(), font=fs, fill=(*hexrgb(DEFAULT_BRAND["colors"]["muted"]), 255))
        d.text((40, 40), title, font=f, fill=(255, 255, 255, 255))
    else:
        d.text((40, 15), title, font=f, fill=(255, 255, 255, 255))
    return img


def with_alpha(img, k):
    out = img.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * k)))
    return out
