# Chalk Talk: AI football explainer videos with a talking-head coach

## Context
The working photo → talking-head pipeline lives in `~/Documents/claude-a-thon/talking-head/`. It runs Kokoro TTS and SadTalker on the Apple GPU (MPS), driven by `talk.py`. The user wants a product built on top of it:

- A web form takes a headshot upload, one of 4 common offensive formations, and one of 2 base plays for that formation.
- An LLM (Claude, either direct or through the **Vercel AI Gateway**) writes a script of about 30 seconds explaining which defense beats that play.
- The output is a **vertical 9:16 short-form video**. An animated football chalkboard illustrates the script, and the user's headshot is animated in the corner, speaking it.

**Key design decision:** the LLM writes only the narration and picks which chalkboard cue plays during each line. It never produces coordinates. All player positions, routes and defensive answers are hand-authored data for the 8 plays. Diagrams are therefore always correct and readable, and the LLM can't hallucinate the X's and O's.

## Project layout
New app at `~/Documents/claude-a-thon/chalk-talk/`. It reuses `../talking-head/` (venvs, SadTalker, patches) and doesn't copy it.

```
chalk-talk/
  app.py            FastAPI: form page, job submit, job status, video download
  static/index.html upload + formation/play pickers + voice + progress + video player
  playbook.py       4 formations × 2 plays: offense alignment, routes/paths, the counter defense
  script_gen.py     LLM call (Anthropic SDK → Claude API or Vercel AI Gateway), structured JSON output
  chalkboard.py     frame renderer (Pillow) → ffmpeg, timed to narration
  compose.py        ffmpeg overlay: chalkboard + circular talking head + audio (+ captions)
  pipeline.py       job orchestration and progress stages
  .env.example      LLM_PROVIDER, AI_GATEWAY_API_KEY / ANTHROPIC_API_KEY, LLM_MODEL
  jobs/<id>/        upload, script.json, narration.wav, timings.json, face.mp4, board.mp4, final.mp4
```

Small additions to `talking-head/` so both projects share it:
- **`tts.py`** (runs in `.venv-tts`): takes a JSON list of narration beats. It writes one `narration.wav` plus `timings.json` with per-beat start and end times, and per-word timestamps from Kokoro's token output (used for captions). Each beat is synthesized separately with a short pause between beats, so beat timing is exact.
- **`talk.py --audio file.wav`**: skips TTS and animates the face from existing audio. The current behavior is unchanged when the flag isn't given.

## Pipeline (one job)
1. **Form submit** saves the headshot. A quick face check with SadTalker's crop step rejects photos with no detectable face before any work is spent on them.
2. **Script.** `script_gen.py` sends the play's facts (formation, play concept, the counter defense and *why* it works) from `playbook.py`. It returns JSON with:
   - `title`, which is the on-screen hook.
   - 5–7 `beats` of `{narration, cue}`. `cue` is an enum: `show_formation`, `run_play`, `show_defense`, `highlight_key` (spotlights the defender who wins), `play_vs_defense` (the play runs into the defense and gets stopped), `recap`.
   - About 75–85 words in total, so the clip lands at about 30 seconds.
3. **TTS.** `talking-head/tts.py` produces `narration.wav` and `timings.json`.
4. **In parallel:**
   - **Face:** `talk.py --audio narration.wav --enhance` produces `face.mp4`. This is the slow step: about 9–12 minutes for 30 seconds of audio.
   - **Board:** `chalkboard.py` renders `board.mp4` at 1080×1920 and 30 fps, with each cue's animation stretched to its beat's duration. This takes under a minute.
5. **Compose.** `compose.py` overlays the face as a circle with a chalk-white ring in the bottom-right corner (about 400 px), adds the narration audio and burns in word-chunk captions. The output is `final.mp4` (H.264).

One worker thread processes jobs one at a time, since there's one GPU. The status endpoint reports the stage and its progress, and the page polls it.

## LLM integration (`script_gen.py`)
- **Anthropic Python SDK for both providers.** Vercel AI Gateway implements the Anthropic Messages API (verified in Vercel's docs, which include structured outputs). The only difference between providers is configuration:
  - `LLM_PROVIDER=gateway`: `Anthropic(api_key=AI_GATEWAY_API_KEY, base_url="https://ai-gateway.vercel.sh")`, with the model `anthropic/claude-opus-5.5`. Confirm the exact gateway model slug during implementation; it's configurable through `LLM_MODEL`.
  - `LLM_PROVIDER=anthropic`: `Anthropic()` with `claude-opus-5-5`.
- **Request settings:** structured output through `output_config.format` (JSON schema with the cue enum), `effort: "low"` (short creative writing doesn't need deep thinking), and `max_tokens` of about 4000.
- **Validation and retry:** validate the result (word count, at least one `show_defense` and one `highlight_key` beat, valid cues). Retry once if it fails. Check `stop_reason` for refusals and token limits.
- **System prompt voice:** an energetic chalk-talk coach writing for short-form video. Open with a hook, name the defense, explain the one key reason it wins, and keep sentences short and spoken.

## Playbook (`playbook.py`), to be reviewed by the user
The coordinates are in yards relative to the ball. Each play stores: offense alignment (11 players), assignments (routes as polylines, run paths, blocks), the defense (11 players, alignment and assignment arrows), a `key_defender`, and a one-paragraph `why_it_works` that is fed to the LLM.

| Formation | Play 1 (run) | Counter | Play 2 (pass) | Counter |
|---|---|---|---|---|
| Shotgun Spread (2×2, 11 personnel) | Inside Zone | Tite/Bear front: interior gaps plugged, LBs fast-flow | Mesh | Cover 1 Robber: a low hole defender jumps the crossers |
| Singleback / Ace (12 personnel) | Outside Zone | Hard-edge Cover 2: corners set the edge, slant front | Play-Action Boot | Cover 3 with a backside end that stays home for contain |
| I-Formation (21 personnel) | Power O | 8-man front: spill the kick-out, unblocked fill player | PA Post | Quarters (Cover 4): safeties read #2 and cap the post |
| Pistol | Zone Read | Scrape exchange: DE crashes the back, LB scrapes to the QB | Smash | Cover 3 Sky: the corner bails over the corner route, the nickel drives on the hitch |

## Chalkboard renderer (`chalkboard.py`)
- **Medium:** Pillow drawing raw frames piped to `ffmpeg -f rawvideo`. There are no new heavy dependencies.
- **Look:**
  - Dark green-black slate with a subtle noise texture and a faint erased-chalk smudge layer.
  - Hand-drawn chalk strokes: lines get slight jitter, variable alpha and a grain mask.
  - O's for offense, X's for defense, and yard lines plus hash marks drawn in chalk.
  - The board sits in the upper ~70% of the frame. The title is at the top. The bottom band holds the captions, with the coach in the corner.
- **Cue animations:**
  - `show_formation`: O's are drawn one by one.
  - `run_play`: routes and arrows draw in progressively along their polylines.
  - `show_defense`: X's are chalked in, with assignment arrows.
  - `highlight_key`: a pulsing yellow chalk circle and a label on the key defender.
  - `play_vs_defense`: players move along their paths, then a red chalk "✕" marks the stop or breakup.
  - `recap`: the full diagram stays up, with the defense's name written large.
- Each animation's easing is normalized to its beat duration from `timings.json`.

## Web app (`app.py` and `static/index.html`)
- **Stack:** FastAPI with uvicorn and a single static page; no build step. The app gets its own `.venv` with `fastapi`, `uvicorn`, `python-multipart`, `anthropic`, `pillow` and `numpy`.
- **Form:**
  - headshot upload with a preview
  - formation as 4 cards; play as 2 options that change with the formation
  - voice dropdown (Kokoro voices)
  - an "Enhance face" toggle, on by default
  - a Generate button
- **After submitting:** a stage-by-stage progress display (Script → Voice → Animating coach x/y → Chalkboard → Compositing), then the video player and a download button. The generated script is shown alongside.
- **Endpoints:** `POST /jobs` (multipart), `GET /jobs/{id}` (status JSON), `GET /jobs/{id}/video`.

## Build order
1. `playbook.py`, with a static preview script that renders each play's diagram as a PNG for the user to sanity-check the X's and O's.
2. `chalkboard.py`, run against a hand-written script, previewing `board.mp4` for all 8 plays.
3. `talking-head/tts.py` and `talk.py --audio`.
4. `script_gen.py`. Test it against the gateway with the user's key.
5. `compose.py` and `pipeline.py`, run end to end from the CLI.
6. `app.py` and the form.

## Verification
- **Playbook:** check the PNG previews for all 8 plays by eye; the user reviews the football content.
- **Chalkboard:** run `python chalkboard.py --demo shotgun_mesh` and check that `board.mp4` is 1080×1920 at 30 fps and the cue timing matches a fixed fake timeline.
- **TTS:** run `tts.py` on a sample script and check that the `timings.json` beat ends sum to the wav duration (`ffprobe`).
- **LLM:** run `python script_gen.py --play singleback_pa_boot` against the Vercel AI Gateway. The JSON must validate and come to about 75–85 words. Repeat with `LLM_PROVIDER=anthropic` if a key exists.
- **End to end:** run `python pipeline.py --photo test.jpg --play pistol_zone_read`, then check:
  - `final.mp4` has audio and video durations within 0.1 s of each other
  - the face circle sits in the bottom-right corner
  - the captions are in sync
  - the board cues line up with the narration
- **UI:** start `uvicorn app:app`, open it in the browser, upload a headshot, generate, and watch the progress and final video. Use the claude-in-chrome skill for the browser check.

## Notes and risks
- **Render time is about 10–13 minutes per video,** almost all of it SadTalker. The UI states this up front. A later option is to render the coach at 256 px without enhancement (about 8 minutes), since the face appears small.
- **Memory:** SadTalker and Kokoro together use well under 64 GB. The LLM is remote, so there's no local model contention.
- **Secrets:** the API key goes in `chalk-talk/.env`, which is gitignored and never logged.
