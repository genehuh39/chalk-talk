# Chalk Talk
<img width="919" height="822" alt="screenshot" src="https://github.com/user-attachments/assets/9231c4e7-3149-4b1e-a4bd-31c5b5fda68e" />

Turn a headshot into a football coach. Pick an offensive formation and play; Claude writes a 30-second
script on the defense that beats it, and Chalk Talk renders a vertical (9:16) short-form video: an
animated chalkboard draws up the play, and your headshot, animated and background-removed, talks
through it in front of the board with word-by-word captions.

A sample video for how to defend an outside zone run is in the chalk-talk/samples directory. 

Everything except the script runs locally on an Apple Silicon Mac.

## How it works

```
headshot + play ─► face check ─► script (Claude) ─► voice (Kokoro TTS, word timings)
                                                        │
                        ┌───────────────────────────────┴──────────────────────┐
                        ▼                                                      ▼
          talking head (SadTalker on MPS)                      chalkboard (Pillow → ffmpeg)
                        ▼                                       timed to each narration beat
          cutout (Robust Video Matting + outline)                              │
                        └──────────────────────► compose (ffmpeg) ◄────────────┘
                                                      ▼
                                              1080×1920 MP4
```

- **The LLM never draws.** All 8 plays (4 formations × 2 plays) are hand-authored X's and O's in
  `chalk-talk/playbook.py`, each with a vetted defensive answer and a key defender. Claude writes the
  narration and picks which chalkboard cue plays under each line, via structured output.
- **Formations:** Shotgun Spread, Singleback (Ace), I-Formation, Pistol, each with one run and one pass play.

## Requirements

- Apple Silicon Mac (tested on M1 Max, 64 GB). Renders take roughly 15–30 minutes per video.
- `ffmpeg`, [`uv`](https://docs.astral.sh/uv/), `git`
- A [Vercel AI Gateway](https://vercel.com/docs/ai-gateway) key **or** an Anthropic API key

## Setup

```bash
./setup.sh                       # clones + patches SadTalker, downloads weights, builds 3 venvs
```

Then put your key in `chalk-talk/.env.local`:

```bash
LLM_PROVIDER=gateway             # or: anthropic
AI_GATEWAY_API_KEY=...           # or: ANTHROPIC_API_KEY=...
```

## Run

```bash
cd chalk-talk
.venv/bin/uvicorn app:app --port 8000      # open http://localhost:8000
```

Or from the command line:

```bash
.venv/bin/python pipeline.py --photo me.jpg --play shotgun_mesh
.venv/bin/python script_gen.py --play iform_power         # just the script
.venv/bin/python chalkboard.py --demo pistol_smash        # just the chalkboard, fake timing
```

The talking-head engine also works standalone:

```bash
cd talking-head
python3 talk.py photo.jpg "Hello there!" --enhance
```

## Layout

```
chalk-talk/          web app + pipeline
  app.py             FastAPI server and job queue
  pipeline.py        stage orchestration
  playbook.py        formations, plays, defenses (yards-based coordinates)
  script_gen.py      Claude script writer (Claude API or Vercel AI Gateway)
  chalkboard.py      animated chalkboard renderer
  compose.py         final ffmpeg composite
  static/index.html  the form
talking-head/        photo → talking video engine
  talk.py            SadTalker wrapper (text or audio in)
  tts.py             Kokoro TTS with per-word timestamps
  cutout.py          background removal + sticker outline
  face_check.py      rejects photos with zero or multiple faces
  patches/           Apple Silicon (MPS) patch for SadTalker
setup.sh
```

## Responsible use

Only animate photos of yourself or of people who have given you permission.

## Credits

Built on [SadTalker](https://github.com/OpenTalker/SadTalker),
[Kokoro TTS](https://huggingface.co/hexgrad/Kokoro-82M),
[Robust Video Matting](https://github.com/PeterL1n/RobustVideoMatting) and
[GFPGAN](https://github.com/TencentARC/GFPGAN). Each is subject to its own license; their code and
weights are downloaded by `setup.sh` and not included in this repository.
