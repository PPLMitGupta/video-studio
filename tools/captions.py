"""Captions from the voice placements: a sidecar .srt and a styled .ass that build.py burns in.

Each line is split at punctuation into short chunks; a chunk's time is its share of the line's
voice duration by character count. Burned captions sit in the band under the framed window.
"""
import re


def chunks(text, limit=84):
    out, cur = [], ""
    for p in re.split(r"(?<=[.,:;!?])\s+", text):
        if cur and len(cur) + 1 + len(p) > limit:
            out.append(cur); cur = p
        else:
            cur = f"{cur} {p}".strip()
    out += [cur] if cur else []
    # a single clause longer than the limit: split at the space nearest the middle
    res = []
    for c in out:
        while len(c) > limit:
            cut = c.rfind(" ", 0, len(c) // 2 + 10)
            cut = cut if cut > 0 else c.find(" ", len(c) // 2)
            if cut <= 0:
                break
            res.append(c[:cut]); c = c[cut + 1:]
        res.append(c)
    return res


def wrap(s, width=44):
    if len(s) <= width:
        return s
    cut = s.rfind(" ", 0, len(s) // 2 + 8)
    return s[:cut] + "\n" + s[cut + 1:]


def cues(placements, limit):
    out = []
    for p in placements:
        cs = chunks(p["text"], limit)
        total = sum(map(len, cs)) or 1
        t = p["placed"]
        for c in cs:
            d = p["dur"] * len(c) / total
            out.append((t, t + d - 0.05, c))
            t += d
    return out


def srt_ts(t):
    h, r = divmod(max(t, 0), 3600); m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"


def ass_ts(t):
    h, r = divmod(max(t, 0), 3600); m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_color(hexrgb, alpha=0):
    h = hexrgb.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def write(placements, srt_path, ass_path, brand, band_top, band_h, width=1920, height=1080):
    c = brand.get("captions", {})
    limit = c.get("max_chars", 72)
    items = cues(placements, limit)
    srt_path.write_text("\n".join(f"{i}\n{srt_ts(a)} --> {srt_ts(b)}\n{wrap(t)}\n"
                                  for i, (a, b, t) in enumerate(items, 1)))
    size = c.get("size", 34)
    font = c.get("font_name", "Helvetica Neue")
    text_col = ass_color(brand["colors"].get("caption_text", "#ffffff"))
    box_col = ass_color(brand["colors"].get("caption_bg", "#11131c"), alpha=0x40)
    margin_v = max(4, height - (band_top + band_h) + (band_h - size - 16) // 2)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{text_col},{text_col},{box_col},{box_col},0,0,0,0,100,100,0.3,0,3,10,0,2,160,160,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 0,{ass_ts(a)},{ass_ts(b)},Cap,,0,0,0,,{{\\fad(120,120)}}{t.replace(chr(10), ' ')}"
             for a, b, t in items]
    ass_path.write_text(head + "\n".join(lines) + "\n")
    return len(items)
