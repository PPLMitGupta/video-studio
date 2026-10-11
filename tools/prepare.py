"""Step 1: transcribe a demo video and draft everything needed for review.

usage: prepare.py <video> [--name NAME] [--classic]

Default (polish-recording): also works out whether the recording has a voice ("voiced") or not
("silent"), finds clicks / typing / page changes (analyze.py), proposes a crop to the app (tidy.py)
and retake cuts (retakes.py), and turns on the polished render in project.json.
--classic keeps the old voice-replacement-only project.

Creates projects/NAME/ with:
  project.json          source path, voice, proposed speed-ups (edit freely)
  work/transcript.json  full Whisper output (word timestamps)
  work/transcript_raw.tsv   start<TAB>text, one line per spoken segment
  script.tsv            starts as a copy of transcript_raw.tsv; rewrite the text column
  work/frames/gap_*.jpg screenshot grids of each silent stretch
"""
import argparse, json, re, shutil
from pathlib import Path
from common import PROJECTS, WHISPER_MODEL, duration, fmt, run_ffmpeg

MIN_SPEEDUP_GAP = 4.5   # silent stretches shorter than this are left alone
MARGIN = 0.25           # keep this much normal-speed time next to speech


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "video"


HALLUCINATIONS = ("be right back", "thank you for watching", "thanks for watching", "subscribe", "see you next time")


def real_segments(segs, wav):
    """Drop Whisper hallucinations: zero-length, repetitive, stock phrases, or over near-silence."""
    import numpy as np, soundfile as sf
    audio, sr = sf.read(wav, dtype="float32")
    def level(s):
        chunk = audio[int(s["start"] * sr):int(s["end"] * sr)]
        return 20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-9) if len(chunk) else -120
    levels = [level(s) for s in segs]
    speech_level = float(np.median([l for l in levels if l > -60] or [-30]))
    out = []
    for s, lvl in zip(segs, levels):
        if lvl < speech_level - 20 or any(h in s["text"].lower() for h in HALLUCINATIONS):
            continue
        text = s["text"].strip()
        if not text or s["end"] - s["start"] < 0.3:
            continue
        if s.get("no_speech_prob", 0) > 0.6 or s.get("compression_ratio", 0) > 2.4:
            continue
        if sum(c.isascii() for c in text) < 0.8 * len(text):
            continue
        out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--name")
    ap.add_argument("--classic", action="store_true")
    a = ap.parse_args()
    src = Path(a.video).expanduser().resolve()
    proj = PROJECTS / (a.name or slug(src.stem))
    work = proj / "work"
    (work / "frames").mkdir(parents=True, exist_ok=True)
    (proj / "output").mkdir(exist_ok=True)
    total = duration(src)

    wav = work / "orig_16k.wav"
    import subprocess
    from common import ffmpeg
    has_audio = "Audio:" in subprocess.run([ffmpeg(), "-hide_banner", "-i", str(src)], capture_output=True, text=True).stderr
    segs = []
    if has_audio:
        run_ffmpeg("-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav))
        import mlx_whisper
        r = mlx_whisper.transcribe(str(wav), path_or_hf_repo=WHISPER_MODEL, word_timestamps=True, language="en")
        (work / "transcript.json").write_text(json.dumps(r, indent=1))
        segs = real_segments(r["segments"], str(wav))

    speech = sum(s["end"] - s["start"] for s in segs)
    mode = "voiced" if speech >= 3 or a.classic else "silent"
    if mode == "silent":
        segs = []
    (work / "segments.json").write_text(json.dumps([{k: s[k] for k in ("start", "end", "text")} for s in segs], indent=1))
    lines = [f"{s['start']:.2f}\t{s['text'].strip()}" for s in segs]
    (work / "transcript_raw.tsv").write_text("\n".join(lines) + "\n")
    if not (proj / "script.tsv").exists():
        if mode == "voiced":
            shutil.copy(work / "transcript_raw.tsv", proj / "script.tsv")
        else:
            (proj / "script.tsv").write_text(
                "# silent recording: write the narration. One line per row:\n"
                "# <start seconds in the original><TAB><narration>[<TAB><step title>]\n")

    # low-confidence words = likely mishearings to confirm with the user
    # (skip segment-initial and short words: Whisper is routinely unsure of "So", "And", "We")
    unsure = [(w["start"], w["word"].strip(), s["text"].strip())
              for s in segs for w in s.get("words", [])[1:]
              if w.get("probability", 1) < 0.5 and len(re.sub(r"\W", "", w["word"])) >= 4]

    # silent stretches -> proposed speed-ups
    gaps, prev = [], 0.0
    for s in segs:
        gaps.append((prev, s["start"]))
        prev = s["end"]
    gaps.append((prev, total))
    speedups, sheets = [], []
    for i, (g0, g1) in enumerate(gaps):
        length = g1 - g0
        if length < MIN_SPEEDUP_GAP:
            continue
        if i == len(gaps) - 1:
            continue  # trailing silence after the last line: leave the ending alone
        lo, hi = (g0 + MARGIN if i else g0), g1 - MARGIN
        speedups.append([round(lo, 2), round(hi, 2), 3 if length >= 10 else 2])
        sheets.append(f"frames/gap_{int(g0):04d}.jpg")
        n = 12
        step = max(length / n, 0.5)
        run_ffmpeg("-ss", f"{g0:.2f}", "-t", f"{length:.2f}", "-i", str(src), "-vf",
                   f"fps=1/{step:.3f},scale=640:-1,drawtext=fontfile=/System/Library/Fonts/Helvetica.ttc:text='%{{pts\\:hms\\:{g0:.2f}}}':x=10:y=10:"
                   f"fontsize=28:fontcolor=yellow:box=1:boxcolor=black,tile=4x3",
                   "-frames:v", "1", str(work / "frames" / f"gap_{int(g0):04d}.jpg"))

    cfg_path = proj / "project.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    cfg.setdefault("source", str(src))
    polish = not a.classic
    extra = {}
    if polish:
        extra = polish_analysis(src, work, segs, total, mode)
        if mode == "silent":
            speedups = extra.pop("idle_speedups")
        else:
            extra.pop("idle_speedups")
        cfg.setdefault("output", f"output/{proj.name}.mp4")
        cfg.setdefault("polish", {})
        cfg.setdefault("title", src.stem.replace("_", " ").replace("-", " ").strip().title())
        cfg.setdefault("subtitle", None)
        cfg.setdefault("crop", extra["crop"])
        cfg.setdefault("cuts", [])
        cfg.setdefault("spotlights", [])
        cfg["mode"] = mode
    cfg.setdefault("output", f"output/{proj.name}_voiceover.mp4")
    cfg["speedups"] = speedups
    cfg_path.write_text(json.dumps(cfg, indent=1))

    saved = sum((b - a) * (1 - 1 / s) for a, b, s in speedups)
    print(f"project: {proj}")
    print(f"length {fmt(total)} -> about {fmt(total - saved)} with proposed speed-ups; {len(segs)} spoken lines")
    print("\nproposed speed-ups:")
    for (lo, hi, s), sheet in zip(speedups, sheets):
        print(f"  {fmt(lo)}-{fmt(hi)}  {s}x  ({hi - lo:.1f}s)  work/{sheet}")
    print(f"  trailing silence: {fmt(gaps[-1][0])}-{fmt(total)} (left as is)")
    print("\nlow-confidence words:")
    for t, w, ctx in unsure:
        print(f"  {fmt(t)}  '{w}'  in: {ctx}")
    print("\ntranscript:" if segs else "\nno narration in the recording (silent mode): write script.tsv from the events")
    for s in segs:
        print(f"  [{fmt(s['start'])}] {s['text'].strip()}")
    if polish:
        print(f"\nmode: {mode}   crop: {cfg['crop']}   (check work/frames/tidy_rect.jpg)")
        print(f"events ({extra['event_mode']}): {extra['counts']}   sheets: {', '.join(extra['sheets'])}")
        print("retake proposals (not applied; copy approved ones into project.json \"cuts\"):")
        for p in extra["retakes"] or [{"from": 0, "to": 0, "conf": "-", "why": "none found"}]:
            print(f"  {fmt(p['from'])}-{fmt(p['to'])}  [{p['conf']}]  {p['why']}")
        print("events (original time, kind, target box):")
        for e in extra["events"]:
            if e["k"] in ("click", "type", "nav", "scroll", "change"):
                b = e.get("box")
                print(f"  {fmt(e['t'])}  {e['k']:<6}" + (f"  at {e['x']},{e['y']}" if "x" in e else "") +
                      (f"  box {b['x']},{b['y']} {b['width']}x{b['height']}" if b else ""))


def polish_analysis(src, work, segs, total, mode):
    """Run analyze -> tidy -> retakes; return what prepare needs to print and store."""
    import numpy as np
    from collections import Counter
    import analyze, tidy, retakes
    a = analyze.analyze(src)
    ev, ev_mode = analyze.events_from(a)
    (work / "cues.json").write_text(json.dumps({"source": str(src), "size": [a["SW"], a["SH"]], "mode": ev_mode,
                                                "events": ev}, indent=1))
    np.savez_compressed(work / "analysis.npz", frac=a["frac"], heat_nav=a["heat_nav"], heat_all=a["heat_all"],
                        start=a["start"], sc=a["sc"], hash_t=np.array([t for t, _ in a["hashes"]]),
                        hash_v=np.array([h for _, h in a["hashes"]]))
    items = []
    for e in ev:
        if e["k"] in ("click", "type", "change"):
            b = e.get("box")
            marks = ([("box", b["x"], b["y"], b["width"], b["height"])] if b else []) + \
                    ([("dot", e["x"], e["y"], 0, 0)] if "x" in e else [])
            items.append((e["t"] + 0.12, f"{fmt(e['t'])} {e['k']}", marks))
    sheets = [str(p.relative_to(work.parent)) for p in analyze.contact_sheet(src, items, work / "frames" / "events.jpg")]
    crop = tidy.content_rect(a["heat_nav"], a["heat_all"], a["sc"], a["SW"], a["SH"])
    tidy.preview(src, crop, work / "frames" / "tidy_rect.jpg", min(total * 0.4, total - 1))
    props = retakes.from_transcript(segs) + retakes.from_screen(
        [t for t, _ in a["hashes"]], [h for _, h in a["hashes"]], a["frac"], a["start"], [(s["start"], s["end"]) for s in segs])
    props.sort(key=lambda p: p["from"])
    (work / "retakes.json").write_text(json.dumps(props, indent=1))
    # silent recordings: still stretches (nothing on screen changes for 4 s+) are speed-up candidates
    frac = a["frac"]
    still = np.convolve(frac > 0.002, np.ones(15), "same") == 0
    idle, i = [], 0
    while i < len(still):
        if still[i]:
            j = i
            while j < len(still) and still[j]:
                j += 1
            if (j - i) / 30 >= 4 and j < len(still) - 30:
                idle.append([round(i / 30 + 0.5, 2), round(j / 30 - 0.5, 2), 2])
            i = j
        i += 1
    return {"crop": crop, "events": ev, "event_mode": ev_mode, "counts": dict(Counter(e["k"] for e in ev)),
            "sheets": sheets + [str((work / "frames" / "tidy_rect.jpg").relative_to(work.parent))],
            "retakes": props, "idle_speedups": idle}


if __name__ == "__main__":
    main()
