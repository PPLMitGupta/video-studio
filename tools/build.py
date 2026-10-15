"""Step 2: render the final video from project.json + script.tsv.

usage: build.py <project> [--voice-only] [--preview START DUR]

Classic projects (no "polish" in project.json): speed up the silent stretches and replace the
narration with Kokoro TTS, exactly as before.

Polished projects ("polish": {...} or true) add, in one render pass (see render.py):
intro/outro cards, crop to the app, cuts with cross-fades, auto-zoom, framed window, click
ripples, spotlights, step titles, burned-in captions (+ .srt) and subtle sound effects.
If a voice line runs past the next one, the video freezes briefly ("holds") so they stay in sync.
"""
import argparse, json, subprocess, sys
import numpy as np
import soundfile as sf
from common import duration, ffmpeg, fmt, load_config, project_dir
from timeline import Timeline
from voice import SR, load_pronunciations, load_script, place_lines
import context

POLISH = {"zoom": "auto", "zmax": 1.5, "zmin": 1.2, "content_center": 0.5, "hold": 3.0, "auto_hold": True, "ripples": True}


def check_rows(rows, tl):
    bad = [(t, txt) for t, txt, _ in rows for lo, hi, _ in tl.speedups if lo < t < hi]
    bad += [(t, txt) for t, txt, _ in rows if tl.in_cut(t)]
    if bad:
        sys.exit("script lines start inside a speed-up or cut range; shrink the range:\n" +
                 "\n".join(f"  {fmt(t)} {txt}" for t, txt in bad))


def classic(a, proj, cfg, work, src, src_end, rows):
    tl = Timeline(src_end, (), cfg.get("speedups", []))
    check_rows(rows, tl)
    track, placements, cursor = place_lines(rows, tl, cfg, work / "tts", load_pronunciations(cfg) if cfg.get("pronunciations") else {})
    out_len = max(tl.out_dur, cursor + 0.5)
    track = track[: int(out_len * SR)]
    write_voice(work, track, placements, rows, tl, src_end, out_len, cursor)
    if a.voice_only:
        return
    out = proj / cfg["output"]
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        ffmpeg(), "-hide_banner", "-loglevel", "error", "-stats", "-y",
        "-i", src, "-i", str(work / "voice_track.wav"),
        "-filter_complex",
        f"[0:v]{tl.ffmpeg_filter()}[v];"
        f"[1:a]loudnorm=I={cfg['loudness']}:TP=-1.5:LRA=11,aresample=48000,apad[a]",
        "-map", "[v]", "-map", "[a]", "-t", f"{out_len:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(out)], check=True)
    print("wrote", out)


def write_voice(work, track, placements, rows, tl, src_end, out_len, cursor):
    sf.write(work / "voice_track.wav", track, SR)
    (work / "placements.json").write_text(json.dumps(placements, indent=1))
    (work / "script_review.txt").write_text("".join(
        f"{fmt(t)}  {txt}" + (f"   [step: {step}]" if step else "") + "\n" for t, txt, step in rows))
    for p in placements:
        if p["placed"] - p["target"] > 0.05:
            print(f"shifted +{p['placed'] - p['target']:.2f}s at {fmt(p['placed'])}: {p['text']}")
    print(f"length {fmt(src_end)} -> {fmt(out_len)}; {len(rows)} lines; voice ends {fmt(cursor)}")


def polished(a, proj, cfg, work, src, src_end, rows):
    from look import load_brand
    brand = load_brand(cfg)
    opt = dict(POLISH); opt.update(cfg["polish"] if isinstance(cfg["polish"], dict) else {})
    opt["loudness"] = cfg["loudness"]
    pron = load_pronunciations(cfg)
    intro = brand["intro"]["dur"] if brand["intro"]["enabled"] else 0.0
    outro = brand["outro"]["dur"] if brand["outro"]["enabled"] else 0.0
    cuts = [tuple(c[:2]) for c in cfg.get("cuts", [])]
    holds = [tuple(h) for h in cfg.get("holds", [])]

    # place the voice; where a line is pushed late, freeze the video before it (auto holds).
    # One hold at a time, earliest line first: a hold also delays every later line, so the shifts
    # further on must be re-measured after it (adding them all at once over-holds badly).
    for _ in range(len(rows) + 3):
        tl = Timeline(src_end, cuts, cfg.get("speedups", []), holds, intro, outro)
        check_rows(rows, tl)
        track, placements, cursor = place_lines(rows, tl, cfg, work / "tts", pron)
        if not opt["auto_hold"]:
            break
        late = next((p for p in placements if p["placed"] - p["target"] > 0.35), None)
        if late:
            holds = merge_holds(holds + [(late["orig"] - 0.05, round(late["placed"] - late["target"] + 0.15, 2))])
            continue
        end_gap = cursor + 0.8 - (tl.out_dur - outro)
        if end_gap > 0.05:
            holds = merge_holds(holds + [(src_end, round(end_gap, 2))])   # last screen stays up until the voice ends
            continue
        break
    if holds != [tuple(h) for h in cfg.get("holds", [])]:
        print("auto holds (freeze, seconds):", ", ".join(f"{fmt(t)} +{d:.1f}s" for t, d in holds))
    out_len = tl.out_dur
    (work / "timeline.json").write_text(json.dumps({
        "src_dur": src_end, "cuts": tl.cuts, "speedups": tl.speedups, "holds": tl.holds,
        "intro": tl.intro, "outro": tl.outro, "out_dur": tl.out_dur}, indent=1))
    track = np.pad(track, (0, max(0, int(out_len * SR) - len(track))))[: int(out_len * SR)]
    write_voice(work, track, placements, rows, tl, src_end, out_len, cursor)
    if a.voice_only:
        return

    # events from analyze.py, sound effects, captions
    cues = json.loads((work / "cues.json").read_text()) if (work / "cues.json").exists() else {"events": [], "size": None}
    events = cues["events"]
    if events and opt["zoom"] != "off" and cues.get("ctx_version") != context.VERSION:
        print("reading the screen around each change (context-aware zoom)...")
        context.add(src, events, cues.get("size") or video_size(src))
        cues["ctx_version"] = context.VERSION
        (work / "cues.json").write_text(json.dumps(cues, indent=1))
    import sfx, captions
    from look import window_rect
    clicks = [tl.map(e["t"]) for e in events if e["k"] == "click" and not tl.in_cut(e["t"])] if opt["ripples"] else []
    whoosh = ([intro] if intro else []) + tl.cut_points() + ([out_len - outro] if outro else [])
    typing, open_t = [], None
    for e in events:
        if e["k"] == "type":
            open_t = e["t"]
        elif e["k"] == "typeEnd" and open_t is not None:
            if tl.speed_at(open_t) == 1.0 and not tl.in_cut(open_t):
                typing.append((tl.map(open_t), tl.map(e["t"])))
            open_t = None
    fx = sfx.build(out_len, clicks, whoosh, typing, brand.get("sfx"))
    from scipy.signal import resample_poly
    voice48 = resample_poly(track, 2, 1).astype(np.float32)
    n = max(len(voice48), len(fx))
    mix = np.pad(voice48, (0, n - len(voice48))) + np.pad(fx, (0, n - len(fx)))
    sf.write(work / "mix.wav", np.stack([mix, mix], 1), sfx.SR)

    size = cues.get("size") or video_size(src)
    crop = cfg.get("crop") or [0, 0, *size]
    from render import Render, MAX_DECODE_W
    s = min(1.0, MAX_DECODE_W / crop[2])
    rect = window_rect(int(crop[2] * s) // 2 * 2, int(crop[3] * s) // 2 * 2)
    out = proj / cfg["output"]
    out.parent.mkdir(parents=True, exist_ok=True)
    ass = None
    if brand["captions"].get("burn", True):
        ass = work / "captions.ass"
        band_top = rect[1] + rect[3]
        captions.write(placements, out.with_suffix(".srt"), ass, brand, band_top, 1080 - band_top)
    else:
        captions.write(placements, out.with_suffix(".srt"), work / "captions.ass", brand, 980, 100)

    from cards import intro_card, outro_card
    title = cfg.get("title") or proj.name.replace("-", " ").title()
    steps, n_step = [], 0
    for p in placements:
        if p.get("step"):
            n_step += 1
            txt = p["step"] if " · " in p["step"] else f"Step {n_step} · {p['step']}"
            steps.append((p["placed"], txt))
    r = Render(src, crop, tl, events, brand, opt, steps, cfg.get("spotlights", []),
               intro_card(brand, title, cfg.get("subtitle")) if intro else None,
               outro_card(brand) if outro else None)
    # the zoomed-in moments, so verify.py can show them for a context check
    z = r.cam[0]; zooms, i = [], 0
    while i < len(z):
        if z[i] > 1.15:
            j = i
            while j < len(z) and z[j] > 1.15:
                j += 1
            k = i + int(np.argmax(z[i:j]))
            zooms.append({"t": round(k / 30, 2), "z": round(float(z[k]), 2), "dur": round((j - i) / 30, 1)})
            i = j
        i += 1
    (work / "zooms.json").write_text(json.dumps(zooms, indent=1))
    print(f"zoom: {len(zooms)} zoomed moments, {sum(m['dur'] for m in zooms):.0f}s of {out_len:.0f}s zoomed in")
    target = out if not a.preview else out.with_name(out.stem + f"_preview_{int(a.preview[0])}.mp4")
    print(f"rendering {fmt(out_len)} ({r.n} frames) -> {target.name}")
    r.run(target, work / "mix.wav", ass, cwd=work, preview=a.preview)
    print("wrote", target, "and", out.with_suffix(".srt").name)


def merge_holds(holds):
    out = {}
    for t, d in holds:
        k = round(t, 2)
        out[k] = round(out.get(k, 0) + d, 2)      # a later measurement is what is still missing: add it
    return sorted(out.items())


def video_size(src):
    from analyze import video_size as vs
    return list(vs(src))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--voice-only", action="store_true", help="build voice_track.wav, skip the video render")
    ap.add_argument("--preview", nargs=2, type=float, metavar=("START", "DUR"), help="render only this output range")
    a = ap.parse_args()
    proj = project_dir(a.project)
    cfg = load_config(proj)
    work = proj / "work"
    src = cfg["source"]
    src_end = duration(src)
    rows = load_script(proj)
    (polished if is_polish_recording(cfg) else classic)(a, proj, cfg, work, src, src_end, rows)


def is_polish_recording(cfg):
    """Only projects made by polish-recording's prepare.py get the polished render. walkthrough-video
    projects also have a "polish" block (tuning for its own polish.py) but their source is already
    framed and zoomed: polishing it again zooms twice, with click positions that no longer match."""
    if cfg.get("pipeline"):
        return cfg["pipeline"] == "polish-recording"
    return cfg.get("polish", False) is not False and cfg.get("mode") in ("voiced", "silent") and "chapters" not in cfg


if __name__ == "__main__":
    main()
