"""Contact sheets: one frame per narration line, to check that the screen matches the words.

usage: check_grid.py <project> [--at 0.75] [--video work/recording.mp4]
Writes work/check/grid<N>.jpg (12 frames each, in cue order) and prints which cue is which.
--at is how far into each line to sample (0.75 = three quarters through, after the action).
"""
import argparse, glob, json, subprocess
from _common import ffmpeg, project

ap = argparse.ArgumentParser(); ap.add_argument("project"); ap.add_argument("--at", type=float, default=0.75)
ap.add_argument("--video", default="work/recording.mp4"); a = ap.parse_args()
proj = project(a.project); work = proj / "work"; chk = work / "check"; chk.mkdir(exist_ok=True)
for f in chk.glob("*.jpg"):
    f.unlink()
c = json.loads((work / "cues.json").read_text()); d = json.loads((work / "durations.json").read_text())
for i, q in enumerate(c["cues"]):
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{q['t'] + d[q['id']] * a.at:.2f}",
                    "-i", str(proj / a.video), "-frames:v", "1", "-vf", "scale=640:-1", str(chk / f"{i:02d}_{q['id']}.jpg")], check=True)
files = sorted(glob.glob(str(chk / "[0-9]*.jpg")))
for g in range(0, len(files), 12):
    part = files[g:g + 12]; args = []
    for f in part:
        args += ["-i", f]
    lay = "|".join(f"{(k % 3) * 640}_{(k // 3) * 360}" for k in range(len(part)))
    flt = f"xstack=inputs={len(part)}:layout={lay}:fill=black" if len(part) > 1 else "null"
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args, "-filter_complex", flt, "-frames:v", "1",
                    str(chk / f"grid{g // 12}.jpg")], check=True)
    print(f"grid{g // 12}.jpg:", ", ".join(f.split("/")[-1][3:-4] for f in part))
