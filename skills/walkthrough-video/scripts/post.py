"""After build.py: mix soft click sounds into the final video and write captions (.srt) beside it.

usage: post.py <project>
Both use the FINAL timeline (after build.py's speed-ups), so they line up with the voice.
"""
import json, re, subprocess, sys
import numpy as np
import soundfile as sf
from _common import ffmpeg, load_config, project

proj = project(sys.argv[1]); work = proj / "work"
cfg = load_config(proj)
speedups = [tuple(x) for x in cfg["speedups"]]
new_t = lambda t: t - sum(min(max(t - lo, 0), hi - lo) * (1 - 1 / s) for lo, hi, s in speedups)
final = proj / cfg["output"]
probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(final)], capture_output=True, text=True).stderr
h, m, s = probe.split("Duration: ")[1].split(",")[0].split(":")
dur = int(h) * 3600 + int(m) * 60 + float(s)

# ---- clicks: a short, soft, high-passed tick about 27 dB under full scale ----
SR = 48000
if cfg.get("clicks", True):
    rng = np.random.default_rng(7)
    n = int(0.035 * SR); k = np.arange(n)
    tick = np.diff(rng.standard_normal(n) * np.exp(-k / (0.004 * SR)), prepend=0) * 0.5
    tick += 0.6 * np.sin(2 * np.pi * 2300 * k / SR) * np.exp(-k / (0.003 * SR))
    tick *= 10 ** (-27 / 20) / np.abs(tick).max()
    track = np.zeros(int((dur + 1) * SR))
    clicks = [new_t(e["t"]) for e in json.loads((work / "cues.json").read_text())["events"] if e["k"] == "click"]
    for t in clicks:
        i = int(t * SR)
        if 0 <= i < len(track) - n:
            track[i:i + n] += tick
    sf.write(work / "clicks.wav", np.stack([track, track], 1).astype(np.float32), SR)
    tmp = final.with_name(final.stem + ".tmp.mp4")
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(final), "-i", str(work / "clicks.wav"),
                    "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0:duration=first[a]", "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(final)
    print(f"clicks: {len(clicks)}")

# ---- captions: each line split at punctuation into chunks of <= 84 characters, two lines of ~44 ----
def chunks(text, limit=84):
    out, cur = [], ""
    for p in re.split(r"(?<=[.,:;!?])\s+", text):
        if cur and len(cur) + 1 + len(p) > limit:
            out.append(cur); cur = p
        else:
            cur = f"{cur} {p}".strip()
    return out + ([cur] if cur else [])


def wrap(s, width=44):
    if len(s) <= width:
        return s
    cut = s.rfind(" ", 0, len(s) // 2 + 8)
    return s[:cut] + "\n" + s[cut + 1:]


def ts(t):
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"


srt, k = [], 1
for p in json.loads((work / "placements.json").read_text()):
    cs = chunks(p["text"]); total = sum(map(len, cs)); t = p["placed"]
    for c in cs:
        d = p["dur"] * len(c) / total
        srt.append(f"{k}\n{ts(t)} --> {ts(t + d - 0.05)}\n{wrap(c)}\n"); k += 1; t += d
final.with_suffix(".srt").write_text("\n".join(srt))
print("captions:", final.with_suffix(".srt"), k - 1, "cues")
