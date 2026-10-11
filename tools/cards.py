"""Intro and outro title cards, drawn with the brand look (gradient, logo, title, subtitle)."""
from pathlib import Path
from PIL import Image, ImageDraw
from look import OH, OW, font, gradient, hexrgb, with_alpha


def _ease(x):
    x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3


def _logo(brand, height):
    p = brand.get("logo")
    if p and Path(p).expanduser().exists():
        im = Image.open(Path(p).expanduser()).convert("RGBA")
        return im.resize((round(im.width * height / im.height), height), Image.LANCZOS)
    # no logo file: the brand name as a wordmark with an accent dot
    f = font(int(height * 0.62), "Bold")
    w = int(f.getlength(brand["name"])) + int(height * 0.6)
    im = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = height * 0.16
    d.ellipse((0, height / 2 - r, 2 * r, height / 2 + r), fill=(*hexrgb(brand["colors"]["accent"]), 255))
    d.text((int(height * 0.5), height // 2), brand["name"], font=f, fill=(255, 255, 255, 255), anchor="lm")
    return im


class Card:
    """A title card. frame(t) returns the RGB image at t seconds into the card."""

    def __init__(self, brand, title, subtitle=None, lines=(), url="", dur=3.0):
        self.dur = dur
        self.bg = gradient(brand["colors"]["bg"])
        self.layers = []                       # (image, y, delay)
        y = OH // 2 - 120 - 22 * len(lines)
        logo = _logo(brand, 64)
        self.layers.append((logo, y, 0.0)); y += logo.height + 44
        for text, size, weight, color, delay in (
                [(title, 68, "Bold", "#ffffff", 0.15)] if title else []) + (
                [(subtitle, 34, "Regular", brand["colors"]["muted"], 0.3)] if subtitle else []) + [
                (l, 30, "Regular", brand["colors"]["muted"], 0.4 + 0.08 * i) for i, l in enumerate(lines)] + (
                [(url, 30, "Semibold", brand["colors"]["accent"], 0.6)] if url else []):
            f = font(size, weight)
            im = Image.new("RGBA", (int(f.getlength(text)) + 8, int(size * 1.35)), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((4, 0), text, font=f, fill=(*hexrgb(color), 255))
            self.layers.append((im, y, delay)); y += im.height + (18 if size < 60 else 26)

    def frame(self, t):
        out = self.bg.copy()
        fade_out = min(1.0, (self.dur - t) / 0.35) if t > self.dur - 0.35 else 1.0
        for im, y, delay in self.layers:
            k = _ease((t - delay) / 0.6) * fade_out
            if k <= 0:
                continue
            layer = with_alpha(im, k)
            out.paste(layer, ((OW - im.width) // 2, y + int((1 - k) * 18)), layer)
        return out


def intro_card(brand, title, subtitle):
    i = brand["intro"]
    return Card(brand, i.get("title") or title, i.get("subtitle") or subtitle, dur=i["dur"])


def outro_card(brand):
    o = brand["outro"]
    return Card(brand, o.get("title"), None, o.get("lines", []), o.get("url", ""), dur=o["dur"])
