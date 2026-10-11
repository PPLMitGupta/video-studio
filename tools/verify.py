"""Step 3: check the rendered video.

usage: verify.py <project>

- re-transcribes the output and matches every script line (flags lines that don't come back close)
- confirms the audio after the last line is silent (Whisper invents sentences on silence)
- writes work/frames/sync_check.jpg: the frame at the start of 8 spread-out lines, to eyeball sync
"""
import argparse, json, re, subprocess
from difflib import SequenceMatcher
from common import WHISPER_MODEL, duration, ffmpeg, fmt, load_config, project_dir, run_ffmpeg


ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def spell(n):
    n = int(n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    return str(n)


def norm(s):
    s = s.lower().replace("-", " ").replace("into", "in to")
    s = re.sub(r"\b\d{1,2}\b", lambda m: spell(m.group()), s)
    return re.sub(r"[^a-z0-9 ]", "", s).split()


def polished_checks(cfg, work, out, placements):
    """Length, loudness, captions inside the voice, and a sheet of every effect to look at."""
    from timeline import Timeline
    tj = json.loads((work / "timeline.json").read_text())
    tl = Timeline(tj["src_dur"], tj["cuts"], tj["speedups"], tj["holds"], tj["intro"], tj["outro"])
    total = duration(out)
    print(f"length {total:.2f}s, expected {tl.out_dur:.2f}s -> {'OK' if abs(total - tl.out_dur) < 0.15 else 'MISMATCH'}")
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(out), "-vn", "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r)[-1])
    print(f"loudness {lufs} LUFS (target {cfg.get('loudness', -16)}) -> {'OK' if abs(lufs - cfg.get('loudness', -16)) <= 1 else 'CHECK'}")
    srt = out.with_suffix(".srt")
    if srt.exists():
        def sec(s):
            h, m, rest = s.split(":"); return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))
        cues = [tuple(map(sec, l.split(" --> "))) for l in srt.read_text().splitlines() if " --> " in l]
        spans = [(p["placed"] - 0.05, p["placed"] + p["dur"] + 0.05) for p in placements]
        bad = [c for c in cues if not any(a <= c[0] and c[1] <= b for a, b in spans)]
        print(f"captions: {len(cues)} cues, {len(bad)} outside the voice" + (f" (first at {fmt(bad[0][0])})" if bad else ""))
    cues_path = work / "cues.json"
    ev = json.loads(cues_path.read_text())["events"] if cues_path.exists() else []
    shots = []
    if tl.intro:
        shots.append((tl.intro * 0.6, "intro card"))
        shots.append((tl.intro + 0.25, "intro -> content fade"))
    steps = [p for p in placements if p.get("step")]
    shots += [(p["placed"] + 0.8, f"step: {p['step']}") for p in steps]
    shots += [(T + 0.2, "cut (cross-fade)") for T in tl.cut_points()]
    shots += [(tl.map(e["t"]) + 0.15, "click ripple") for e in ev if e["k"] == "click" and not tl.in_cut(e["t"])][:8]
    shots += [(tl.map(s["t"]) + 1.0, "spotlight") for s in cfg.get("spotlights", [])]
    shots += [(tl.map(th) + d / 2, f"hold {d:.1f}s") for th, d in tl.holds][:4]
    if tl.outro:
        shots.append((tl.out_dur - tl.outro * 0.4, "outro card"))
    frames = work / "frames"
    from PIL import Image, ImageDraw
    w, h = 640, 360
    shots = sorted(shots)[:24]
    sheet = Image.new("RGB", (4 * w, ((len(shots) + 3) // 4) * h), (20, 20, 20))
    for i, (t, label) in enumerate(shots):
        raw = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{max(t, 0):.2f}", "-i", str(out), "-frames:v", "1",
                              "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if len(raw) < w * h * 3:
            continue
        im = Image.frombytes("RGB", (w, h), raw)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, w, 24), fill=(0, 0, 0))
        d.text((6, 4), f"{fmt(t)}  {label}", fill=(255, 230, 120))
        sheet.paste(im, ((i % 4) * w, (i // 4) * h))
    sheet.save(frames / "effects_check.jpg", quality=86)
    print("effects sheet: work/frames/effects_check.jpg")
    for t, label in shots:
        print(f"  {fmt(t)}  {label}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    proj = project_dir(ap.parse_args().project)
    cfg = load_config(proj)
    work = proj / "work"
    out = proj / cfg["output"]
    placements = json.loads((work / "placements.json").read_text())

    info = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(out)], capture_output=True, text=True).stderr
    for l in info.splitlines():
        if "Duration" in l or "Stream" in l:
            print(l.strip())

    wav = work / "final_16k.wav"
    run_ffmpeg("-i", str(out), "-vn", "-ac", "1", "-ar", "16000", str(wav))
    import mlx_whisper
    segs = mlx_whisper.transcribe(str(wav), path_or_hf_repo=WHISPER_MODEL, language="en",
                                  word_timestamps=True)["segments"]

    # match each script line against Whisper words heard within its time window
    words = [(w["start"], n) for s in segs for w in s.get("words", []) for n in norm(w["word"])]

    def missing(want, heard):
        found = sum(b.size for b in SequenceMatcher(None, want, heard).get_matching_blocks())
        return len(want) - found > 1 and found < 0.8 * len(want)  # one dropped word is Whisper noise

    import soundfile as sf
    audio, sr = sf.read(str(wav), dtype="float32")
    problems = 0
    for p in placements:
        want = norm(p["text"])
        heard = [w for t, w in words if p["placed"] - 0.5 <= t <= p["placed"] + p["dur"] + 0.3]
        if missing(want, heard):
            # full-length Whisper sometimes skips whole chunks; re-check this line's clip alone
            clip = audio[int(max(p["placed"] - 0.3, 0) * sr):int((p["placed"] + p["dur"] + 0.3) * sr)]
            heard = norm(mlx_whisper.transcribe(clip, path_or_hf_repo=WHISPER_MODEL, language="en")["text"])
        if missing(want, heard):
            problems += 1
            print(f"CHECK {fmt(p['placed'])}: expected '{p['text']}' | heard '{' '.join(heard)}'")
    print(f"{len(placements) - problems}/{len(placements)} lines matched")

    # ending should be silent after the last line
    end_voice = max(p["placed"] + p["dur"] for p in placements)
    total = duration(out)
    if total - end_voice > 0.5 and cfg.get("polish", False) is False:   # polished: outro sound is expected
        r = subprocess.run([ffmpeg(), "-hide_banner", "-ss", f"{end_voice + 0.2:.2f}", "-i", str(out), "-vn",
                            "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        mx = float(re.search(r"max_volume: (-?[\d.]+)", r).group(1))
        print(f"after last line ({fmt(end_voice)}-{fmt(total)}): max {mx} dB -> {'silent' if mx < -60 else 'NOT SILENT'}")

    if cfg.get("polish", False) is not False:
        polished_checks(cfg, work, out, placements)

    # sync contact sheet
    idx = sorted({round(i * (len(placements) - 1) / 7) for i in range(8)})
    frames = work / "frames"
    frames.mkdir(exist_ok=True)
    for n, i in enumerate(idx):
        run_ffmpeg("-ss", f"{placements[i]['placed'] + 0.2:.2f}", "-i", str(out), "-frames:v", "1",
                   "-vf", "scale=640:-1", str(frames / f"chk_{n}.jpg"))
    run_ffmpeg("-i", str(frames / "chk_%d.jpg"), "-vf", "tile=4x2", "-frames:v", "1", str(frames / "sync_check.jpg"))
    for f in frames.glob("chk_*.jpg"):
        f.unlink()
    wav.unlink()
    print(f"\nsync_check.jpg (left->right, top->bottom):")
    for n, i in enumerate(idx):
        print(f"  {n + 1}. {fmt(placements[i]['placed'])}  {placements[i]['text']}")


if __name__ == "__main__":
    main()
