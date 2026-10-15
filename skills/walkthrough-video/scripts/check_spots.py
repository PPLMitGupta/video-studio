"""Check every highlight ring in a take: did the content under it move while it was showing?

A ring drawn while the page is still scrolling (or just before a layout shift) ends up around empty
space or the wrong element. This compares what is inside each ring's box just after it appears with
1.3 s later; a big change means the page moved under the ring.

usage: check_spots.py <project>     (run after the take, before polish.py)
Prints each suspect ring with its time; fix the scene (wait for the page, or spot after the scroll) and
retake, or reword the line.
"""
import json, sys
import numpy as np
from PIL import Image
from _common import project, TOOLS  # noqa: F401  (puts the plugin's tools on the path)
import context

proj = project(sys.argv[1]); work = proj / "work"
c = json.loads((work / "cues.json").read_text())
lines = (work / "frames.txt").read_text().splitlines()
SW, SH = Image.open(lines[0].split("'")[1]).size
sc = SW / context.AW
AH = round(SH / sc / 2) * 2
src = work / "recording.mp4"
moves = [e["t"] for e in c["events"] if e["k"] in ("scroll", "pre", "nav")]
spots = [e for e in c["events"] if e["k"] == "spot" and e.get("box")]
bad = 0
for e in spots:
    a = context._gray(src, e["t"] + 0.15, context.AW, AH)
    b = context._gray(src, e["t"] + 1.45, context.AW, AH)
    if a is None or b is None:
        continue
    bx = e["box"]
    x0, y0 = max(0, int(bx["x"] / sc) + 3), max(0, int(bx["y"] / sc) + 3)
    x1, y1 = min(context.AW - 1, int((bx["x"] + bx["width"]) / sc) - 3), min(AH - 1, int((bx["y"] + bx["height"]) / sc) - 3)
    if x1 <= x0 or y1 <= y0:
        print(f"  {e['t']:6.1f}s  ring box is off screen"); bad += 1
        continue
    d = float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())
    if d > 8:
        near = min([abs(e["t"] - m) for m in moves] or [99])
        print(f"  {e['t']:6.1f}s  content under the ring changed (diff {d:.0f}); nearest scroll or page change {near:.1f}s away")
        bad += 1
print(f"{len(spots)} highlights, {bad} suspect")
