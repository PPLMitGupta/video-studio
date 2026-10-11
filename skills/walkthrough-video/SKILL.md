---
name: walkthrough-video
description: Make a professional narrated walkthrough video of a web app module from scratch, with no existing recording. Writes the narration, voices it with Kokoro, records the app with Playwright paced to the voice, then adds Screen Studio / Recordly style auto-zoom, a framed window, chapter labels, cross-fades, click sounds and SRT captions. Use whenever the user asks for a demo video, product walkthrough, training video, explainer or screen recording of an app, epic, module or feature ("make a video of District Settings", "record a walkthrough of the provider portal", "demo video for the client", "video with zoom effects like Recordly"), even without the word "skill". For a screen recording that already exists (re-voicing or polishing it), use polish-recording instead.
---

# Walkthrough video

Turns a module of a running web app into a polished, narrated video. The narration is written and
voiced first, and the recording is paced to it, so every line fits and nothing has to be cut. It
builds on this plugin's tools (`${CLAUDE_PLUGIN_ROOT}/tools`: Kokoro voice, `build.py`, `verify.py`,
ffmpeg). Its own scripts live in `${CLAUDE_SKILL_DIR}/scripts`.

```bash
S="${CLAUDE_SKILL_DIR}/scripts"; T="${CLAUDE_PLUGIN_ROOT}/tools"
PY=${VIDEO_STUDIO_HOME:-$HOME/VideoStudio}/.venv/bin/python
```

Run the Python scripts as `"$PY" "$S/<script>.py" <project>`. `<project>` is a folder name under
`~/VideoStudio/projects/` or a full path.

## 0. Setup check

- `"$PY" -c "import mlx_whisper, kokoro_onnx, PIL, scipy"` must pass. If it fails, run
  `"${CLAUDE_PLUGIN_ROOT}/setup.sh"` (Apple Silicon Mac; about 5–10 minutes the first time).
- The app must be running, with Playwright and its headless shell installed in some repo (for
  SIMMS: `~/SIMMS/SIMMS`, started with `pnpm dev:up`). Use synthetic data only.
- Each take changes the app's data. Starting clean usually means resetting a local test
  database, which is a destructive step, so ask the user before every reset and say what it
  wipes. Never do this on staging.

## 1. Learn the module and choose the story

Read the module's Jira epic and stories, and click through the real screens. A quick Playwright
pass that saves each page's accessibility snapshot (`page.locator('main').ariaSnapshot()`) works
well. That gives the real field names, buttons and refusal messages, and shows which flows work.

Pick one story with a beginning and an end. "An empty district becomes a live one" beats a tour of
pages. Then try the flow once for real before scripting it. That first pass finds broken steps,
bugs worth keeping off camera, and values the app accepts, such as a valid NPI. Note the bugs, and
plan the video around them instead of narrating past them.

## 2. Write the narration (`work/lines.json`)

Use an ordered map of `cue id -> one spoken line`, normally 35-50 lines for 6-9 minutes. Give
each line one step on screen.

- **Say only what will be on screen.** Viewers believe what they see. A line about a warning
  that didn't render in that take reads as an error, so keep claims tied to stable text, or be
  ready to reword the line after the take.
- **Use a product-demo tone.** Write "Let's start with...", "Here we can see...", and plain words.
  Don't add marketing claims the screen doesn't support.
- **Keep lines short.** Each line paces its step, so a long action can't hide behind a short line.

Create `project.json`:

```json
{ "source": "<abs path>/work/recording_polished.mp4", "output": "output/<name>.mp4",
  "voice": "am_michael", "speedups": [],
  "chapters": { "roles": "Overview", "prof1": "Part 1  ·  IT team setup" } }
```

Then voice every line with `"$PY" "$S/tts_prep.py" <project>`. This writes `work/durations.json` and
fills build.py's voice cache.

## 3. Write the scenes (`work/scenes.mjs`)

Read `references/example-scenes.mjs` first. It shows every pattern below. The recorder library is
`scripts/recorder.mjs`:

```js
const { createRecorder } = await import('${CLAUDE_SKILL_DIR}/scripts/recorder.mjs');   // absolute path
const r = await createRecorder({ project, baseURL, playwrightFrom: '<repo with playwright>', brand: 'SIMMS', accent: '#c8104a' });
const page = await r.role({ label: 'IT team · District Administrator', signIn, start: '/path' });
await r.camera(await r.card('Title', 'Subtitle'));   // the first camera() starts the clock
await r.cue('intro');
await r.camera(page);
await r.cue('id', async () => { /* actions while the line plays */ }, async () => { /* silent page change first */ });
await r.finish();
```

The hands are `point`, `spot` (highlight ring), `click`, `type` (`{clear}`), `tabOut`, `pick`
(dropdown button name plus option), `scrollTo` (layout px), `navClick`, `goto`, and `settle`.
Every one logs what it did, and the zoom is directed from that log.

Rules that each came from a failed take:

- **Do page changes in the `pre` step**, not inside the line, or the voice talks about a page that
  hasn't opened yet. The recorder speeds up the gap 2× automatically.
- **Wait for saves.** `pick` and `tabOut` wait for the network to go idle. Firing the next change
  while the last one is still saving makes apps refuse it ("could not be saved"), and the take
  then ends in the wrong state.
- **Make must-happen steps wait for their confirmation** (sign-off, activation, submit), and
  retry once. Add a final check of the story's end state and `note()` it if it's missing.
- **Switch roles by loading the other page first**, then call `camera()`. The cut cross-fades.
- **Keep known bugs off camera**, and don't stop on a screen that shows one.

Run it from the app repo so Playwright resolves: `cd <repo> && node <project>/work/scenes.mjs`. A
take lasts about 10 minutes and changes data, so run it in the background. It prints problems
and lines that were never cued.

## 4. Check the take before polishing

1. Run `"$PY" "$S/check_grid.py" <project>` and read every `work/check/grid*.jpg`. Each frame (three
   quarters through its line) must show what the line says. Look for pages still loading,
   missing highlights, error banners and wrong values.
2. Fix what you find. For a pacing problem, move work into `pre`. For a missing element, reword
   the line or fix the locator. If the data changed, the next take needs a reset (ask first). For
   a reworded line, edit `lines.json`, rerun `tts_prep.py`, rebuild `script.tsv` from
   `work/cues.json`, and check that no speed-up now starts inside the longer line.

## 5. Polish, then review with the user

Preview 40 seconds first with `"$PY" "$S/polish.py" <project> --start <s> --dur 40 --out work/preview.mp4`.
Pull frames from it and check the zoom:

- the target and its whole form stay in view
- no zoom while a page loads
- no restless drifting

The tuning options are in `polish.py`'s docstring (`zmax`, `content_center`, `hold`, colours).
Then render the whole thing with `"$PY" "$S/polish.py" <project>`, about 0.6× real time.

Then do polish-recording's review round, in one message, and wait for "go":

- the voice
- the full script
- the speed-ups, summarised as page loads vs. long actions, with the final length
- the bugs that are visible on screen
- any lines you reworded, and why

## 6. Build, finish, verify

```bash
"$PY" "$T/build.py" <project>
"$PY" "$S/post.py" <project>        # click sounds + <output>.srt captions
"$PY" "$T/verify.py" <project>
```

`verify.py` must show every line matched and a silent ending. Then read
`work/frames/sync_check.jpg`. A blended frame at a role switch is the cross-fade, which is
expected. Copy the `.mp4` and its `.srt` (same base name, so players load the captions) to the
Desktop and reveal them in Finder.

Report the length, the voice, the effects, the verify result, any reworded lines, the bugs visible
on screen, and the state the app's data was left in.

## Why the capture works this way

- **CDP screencast frames come at the viewport's CSS size**, whatever the `deviceScaleFactor`.
  So the recorder uses a 2880×1620 viewport with `body { zoom: 2 }`. The app still lays out at
  1440×810, and zoomed text stays sharp.
- **The pointer, ring and role badge are page elements** mounted on `<html>` after `load`,
  outside React's `<body>` and outside the zoom. Mounting them earlier breaks hydration, and the
  app never renders.
- **The zoom is directed from the action log, not guessed from pixels.** It frames each target
  with margin, leans toward the content column so a form isn't cut off, holds still when the next
  target is already in frame, stays wide for navigation clicks and page loads, and eases through
  a critically damped spring.
- **`project.json` `source` must be an absolute path.** `build.py` resolves it from its own
  working folder.
