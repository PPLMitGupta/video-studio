# video-studio

A Claude Code plugin that turns screen recordings into polished product videos. Everything
runs locally on your Mac and is free: Whisper (transcription), Kokoro (AI voice), ffmpeg and
Python (video). Nothing is uploaded anywhere.

Two skills:

- **polish-recording**: give Claude a screen recording, with or without your voice, and get:
  - an AI voiceover: your words cleaned up, or narration written for a silent recording
  - slow stretches sped up and retakes cut (you approve every cut)
  - a crop to the app, with no browser tabs or address bar
  - auto-zoom on clicks and typing, inside a framed window
  - click ripples and spotlights on key moments
  - step titles, intro and end cards
  - burned-in captions plus an .srt file
  - subtle click, typing and transition sounds
- **walkthrough-video**: Claude writes the narration, records your app itself with Playwright, and
  produces the same polished result from scratch.

## Requirements

- A Mac with Apple Silicon (M1 or later).
- Python 3.10+ (`python3 --version`; install from python.org or `brew install python` if needed).
- Claude Code (desktop app or CLI).
- Read access to this repo on GitHub, with git able to reach it: run `gh auth login` and then
  `gh auth setup-git` once.
- About 4 GB of free disk space.

## Install (once)

In Claude Code, run these two commands:

```
/plugin marketplace add PPLMitGupta/video-studio
/plugin install video-studio@video-studio
```

Or from a terminal:

```bash
claude plugin marketplace add PPLMitGupta/video-studio
claude plugin install video-studio@video-studio --scope user
```

The first time you use it, Claude runs `setup.sh`. That takes about 5–10 minutes and creates your
workspace, `~/VideoStudio`, which holds the Python env, ffmpeg, the voice model and your projects.
You can also run setup yourself: `~/.claude/plugins/cache/video-studio/video-studio/*/setup.sh`.

## Use

Ask Claude in plain words, with the file:

> Polish this recording: ~/Desktop/Screen Recording ….mov

Claude analyses the video and drafts the script and edits. It sends you one review (script, cuts,
speed-ups, crop, spotlights and a short preview), then renders after you say "go". Finished videos
land in `~/VideoStudio/projects/<name>/output/`. You can also call a skill directly:
`/video-studio:polish-recording`.

### Recording tips (they make a big difference)

- Use **Cmd+Shift+5**, then **Options → Show Mouse Clicks ON**. Click ripples, click sounds and
  zoom then land exactly where you clicked.
- Turn on Focus / Do Not Disturb, and close personal windows, notes and authenticator apps.
- Use test data only.
- Pause about 1 second after each click.

## Update

Claude Code doesn't auto-update team plugins unless you turn it on (`/plugin` → Marketplaces →
video-studio → Enable auto-update). To update by hand:

```
/plugin marketplace update video-studio
```

Then choose Update in `/plugin` → Installed, and run `/reload-plugins`. Your workspace and
projects are never touched by updates.

## Team settings (in this repo)

- `brand.json`: logo, colours, intro and end-card text, caption style, sound levels. Put logo
  files in `assets/` and reference them as `"logo": "assets/logo.png"`.
- `pronunciations.json`: how the AI voice says product terms, e.g. `"SIMMS": "Sims"`. Captions
  keep the real spelling.

Change these with a pull request, so everyone's videos stay consistent. For a personal override,
put a `brand.json` or `pronunciations.json` in `~/VideoStudio`.

## Layout

```
.claude-plugin/       plugin + marketplace manifests
skills/               polish-recording, walkthrough-video (instructions Claude follows)
tools/                prepare / analyze / tidy / retakes / build / render / verify (Python)
setup.sh              one-time setup of ~/VideoStudio
brand.json, pronunciations.json, voice_samples/
```

`tools/` in brief:

- `prepare.py` transcribes, decides voiced or silent, runs `analyze.py` (clicks, typing, page
  changes), `tidy.py` (crop) and `retakes.py` (cut proposals), and writes review sheets.
- `build.py` places the voice on one timeline (`timeline.py`: cuts, speed-ups, automatic
  freeze-frames), writes captions (`captions.py`) and sound effects (`sfx.py`), and renders in
  one pass (`render.py`, `cards.py`, `look.py`).
- `verify.py` re-transcribes the result and checks every line, the length, the loudness and the
  captions. It also writes a frame sheet of every effect.

## Troubleshooting

- **"needs a Mac with Apple Silicon"**: the transcription library (MLX) only runs on M-series Macs.
- **A file path from Finder is "not found"**: macOS puts a special narrow space before AM/PM in
  screen-recording names. Drag the file into the chat instead of typing the path.
- **Setup fails halfway**: re-run it; it only fills in what's missing.
- **The voice says a term wrong**: add it to `pronunciations.json`.
