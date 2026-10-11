---
name: polish-recording
description: Turn a raw screen recording (.mov/.mp4) of a product demo or walkthrough, with the presenter's voice or silent, into a professional video. It gets an AI voiceover (the presenter's narration cleaned up, or written from scratch for a silent recording), silent stretches sped up, mistakes and retakes cut, a crop to the app, auto-zoom on clicks and typing, a framed window, click ripples, spotlights, step titles, intro and end cards, burned-in captions plus .srt, and subtle click, typing and transition sounds. Use whenever the user gives a screen recording and wants it polished, narrated, re-voiced, tightened, made professional or "like Screen Studio", including several videos at once and "do the same as last time". Also covers plain voice replacement (formerly demo-voiceover). To record an app from scratch with no video, use walkthrough-video.
---

# Polish a screen recording

Code: this plugin, `${CLAUDE_PLUGIN_ROOT}` (tools in `${CLAUDE_PLUGIN_ROOT}/tools`).
Workspace: `~/VideoStudio` (or `$VIDEO_STUDIO_HOME`). It holds the Python env, ffmpeg, the voice model and one
folder per video in `projects/<name>/`. Run every tool with the workspace Python:

```bash
PY=${VIDEO_STUDIO_HOME:-$HOME/VideoStudio}/.venv/bin/python
T="${CLAUDE_PLUGIN_ROOT}/tools"
"$PY" "$T/prepare.py" ...
```

## 0. Setup check (first use on a machine)

If `"$PY" -c "import mlx_whisper, kokoro_onnx, scipy, PIL"` fails, run `"${CLAUDE_PLUGIN_ROOT}/setup.sh"`.
It needs a Mac with Apple Silicon and Python 3.10+, takes about 5–10 minutes, downloads about 3.5 GB once,
and is safe to re-run. Run it in the background and tell the user what it is doing. Never use a
system/Homebrew ffmpeg; the tools use `~/VideoStudio/bin/ffmpeg` automatically.

## 1. Prepare (per video)

```bash
"$PY" "$T/prepare.py" "<video path>" [--name short-name]
```

macOS screen recordings have a narrow no-break space before "AM/PM" in their file names. If a
pasted path is "not found", list the folder and use the real name.

This takes about 1 minute per 2 minutes of video. It:
- transcribes the audio and decides the **mode**: `voiced` (someone narrates) or `silent`.
- finds what happens on screen (`analyze.py`): clicks (from the macOS click circle), typing, page
  changes and scrolls, each with a target box. `cues.json` mode `clicks` means the click circle was
  found. `changes` means it wasn't: zoom still works, but there are no ripples or click sounds.
- proposes a crop to the app (`tidy.py`) and retake cuts (`retakes.py`). Nothing is applied yet.
- turns on the polished render in `project.json` (`"polish": {}`).

Read everything it lists:
- `work/frames/events_*.jpg`: every click (red dot) and target (yellow box).
- `work/frames/tidy_rect.jpg`: the proposed crop. The bright area is what viewers will see.
- `work/frames/gap_*.jpg` (voiced): what happens during each silent stretch.

Also look for things a client shouldn't see: other windows, personal notes, real names or emails,
notifications. Offer to cut them.

## 2. Write the script (`script.tsv`)

One row per line: `<start s in the ORIGINAL video>\t<narration>[\t<step title>]`.
- **Voiced:** rewrite the text column and keep the start times.
  - Keep the speaker's meaning and order.
  - Drop filler ("so", "basically", restarts) and fix the grammar.
  - Use a confident, friendly product-demo tone ("Let's…", "Next, we…", "Here we can see…").
  - Don't invent features or claims. Resolve low-confidence words with the screenshots, and flag guesses.
  - Keep each line about as long as the original.
- **Silent:** write the narration from the events sheets.
  - Write one line per meaningful action, starting about 0.3 s before it (a click's time is in
    `prepare`'s event list).
  - Say what the viewer sees and why it matters. Don't narrate every click.
  - Leave about 1 s of gap between lines. If a line runs long, the build freezes the video
    briefly ("auto holds") so the line still fits.
- **Step titles** (3rd column): mark 3–7 main steps per video in 2–5 words ("Assign a provider").
  They are numbered automatically ("Step 2 · Assign a provider"). Write "Overview · Title" to
  set your own label.
- **Pronunciation:** product terms the voice might misread go in the plugin's `pronunciations.json` (team-wide, via the repo),
  `~/VideoStudio/pronunciations.json` (personal) or `project.json` `"pronunciations"`. Captions keep the written spelling. The voice already
  reads IEP, CPT and NPI correctly. A new term needs a human ear: Whisper can't judge pronunciation.

## 3. Edit `project.json`

- **`title` / `subtitle`:** the intro card. Make the title the module or workflow name.
- **`speedups`** `[[from, to, speed]]` (original seconds):
  - Use 3x for typing, page loads and copy-paste. Use 2x for slow scrolling.
  - Use normal speed where the viewer must watch.
  - A range must never cover the start of a script line; the build refuses.
  - Silent mode proposes still stretches. Remove any that the narration needs.
- **`cuts`** `[[from, to]]`: retakes the user approves (from `retakes.json`) and anything to hide. A cut
  cross-fades. Prefer speed-ups for short waits, because hard cuts make fields appear filled.
- **`crop`** `[x, y, w, h]` (source px): fix it if `tidy_rect.jpg` is wrong. Cut away browser chrome,
  but never part of the app.
- **`spotlights`** `[{"t": s, "dur": 2.5, "box": {...}}]`: 1–3 per video at most, on the key moment
  (the button that matters, an important warning). Copy the box from that click's event.
- **`brand`:** overrides the brand for this video, e.g. `{"outro": {"enabled": false}}`.
  - Brand order: defaults < the plugin's `brand.json` (team) < `~/VideoStudio/brand.json` (personal) < project.
    If no logo is set yet, ask the user for a PNG and the end-card lines/URL. Team-wide changes go in
    the repo's `brand.json` (and `assets/`) through a pull request; otherwise save them in `~/VideoStudio/brand.json`.
- **`polish`:** tuning. `zmax` (1.5, the strongest zoom), `hold` (3 s before zooming out),
  `auto_hold` (true), `ripples` (true).

## 4. One review round with the user (required)

Send it in one message:
- The voice: default **am_michael** (the team default). Offer `voice_samples/` only if asked.
- The script. Run `"$PY" "$T/build.py" <name> --voice-only`, which writes `work/script_review.txt` with the step
  titles. Attach it, and list guessed words separately (before -> after).
- A table of time range | what's on screen | action (2x/3x/cut), with the estimated new length.
- The crop preview (`tidy_rect.jpg`), the spotlight picks, and any new pronunciation terms.
- Optional: a 20 s preview of the look (`"$PY" "$T/build.py" <name> --preview <start> 20`).

Wait for "go" or corrections. For several videos, run step 1 for all of them first, then do one
combined review.

## 5. Build and verify

```bash
"$PY" "$T/build.py" <name>     # about 2x real time for 1080p, slower for 1440p or 4K
"$PY" "$T/verify.py" <name>
```

- **`build.py`:**
  - Prints the auto holds and any lines it shifted. A hold of more than about 2 s means the line is
    too long for its moment, so shorten it.
  - TTS is cached, so rebuilds only re-voice changed lines.
- **`verify.py`:**
  - Every line must match, and the length must be OK.
  - Loudness must be within 1 LUFS of the target.
  - No captions may fall outside the voice.
- **Read `work/frames/effects_check.jpg`:** the intro card, each step title, each cut, ripples on the
  actual click points, the spotlight, holds and the outro.
- **Read `work/frames/sync_check.jpg`:** each frame matches its line.
- **Send** `output/<name>.mp4` (and its `.srt`) with SendUserFile.
- **Report:** old -> new length, mode, cuts and speed-ups, holds, anything guessed, and anything
  worth a look.

## Recording checklist (share with the user when useful)

- **Cmd+Shift+5 → Options → Show Mouse Clicks ON.** This gives exact click points for ripples, sounds and zoom.
- Focus / Do Not Disturb on (no notifications). Close personal windows and notes.
- Test data only. A browser window at a normal zoom, about 1 s of pause after each click.
- Record the window or the full screen; the crop removes browser chrome and the menu bar.

## Classic mode

`"$PY" "$T/prepare.py" <video> --classic` makes a voice-replacement-only project (no zoom, frame, cards or
captions). Projects without `"polish"` in `project.json` render exactly as before.

## Defaults

- Voice: `am_michael`, `en-us`, speed 1.0, −16 LUFS, 48 kHz AAC, x264 CRF 18, 30 fps, 1920×1080.
- Window: 1664×936 on a brand gradient. Captions sit in the band below the window.
- Intro and outro cards: 3 s each.
- Sound effects: click −27, whoosh −31, typing −37 dBFS. Typing sounds only play at 1x speed.
