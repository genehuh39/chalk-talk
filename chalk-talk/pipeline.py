"""One job: headshot + play -> final chalk-talk video.

Stages: face check -> script (LLM) -> voice (Kokoro) -> [coach (SadTalker) -> cutout || chalkboard] -> compose

CLI:
    python pipeline.py --photo me.jpg --play pistol_zone_read [--voice am_michael] [--no-enhance]
                       [--script-file script.json]   # skip the LLM with a hand-written script
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

import chalkboard
import compose
import playbook
import script_gen

ROOT = os.path.dirname(os.path.abspath(__file__))
TH = os.path.abspath(os.path.join(ROOT, "..", "talking-head"))
TTS_PY = os.path.join(TH, ".venv-tts", "bin", "python")
ST_PY = os.path.join(TH, ".venv-sadtalker", "bin", "python")
JOBS = os.path.join(ROOT, "jobs")

VOICES = {
    "am_michael": "Michael (US, male)",
    "am_fenrir": "Fenrir (US, male, deep)",
    "bm_george": "George (UK, male)",
    "af_heart": "Heart (US, female)",
    "af_bella": "Bella (US, female)",
    "bf_emma": "Emma (UK, female)",
}

STAGES = ["check", "script", "voice", "coach", "cutout", "board", "compose"]


class Job:
    def __init__(self, job_id=None):
        self.id = job_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = os.path.join(JOBS, self.id)
        os.makedirs(self.dir, exist_ok=True)
        self.status = {"id": self.id, "state": "queued", "stage": None, "error": None,
                       "progress": {s: 0.0 for s in STAGES}, "script": None, "created": time.time()}
        self._lock = threading.Lock()
        self.save()

    def path(self, name):
        return os.path.join(self.dir, name)

    def update(self, **kw):
        with self._lock:
            self.status.update(kw)
            self.save()

    def progress(self, stage, value):
        with self._lock:
            self.status["progress"][stage] = round(max(0.0, min(1.0, value)), 3)
            self.save()

    def save(self):
        tmp = self.path("status.json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.status, f, indent=1)
        os.replace(tmp, self.path("status.json"))


def check_face(photo):
    out = subprocess.run([ST_PY, os.path.join(TH, "face_check.py"), photo],
                         capture_output=True, text=True, cwd=TH)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise RuntimeError("face check failed: " + out.stderr[-500:])


def run_tts(job, script, voice):
    spec = {"voice": voice, "speed": 1.05, "gap": 0.22,
            "beats": [{"cue": b["cue"], "text": b["narration"]} for b in script["beats"]]}
    with open(job.path("tts_in.json"), "w") as f:
        json.dump(spec, f)
    subprocess.run([TTS_PY, os.path.join(TH, "tts.py"), job.path("tts_in.json"), job.path("narration")],
                   check=True, cwd=TH, capture_output=True)
    with open(job.path("narration.json")) as f:
        return json.load(f)


PROGRESS_RE = re.compile(r"(Face Renderer|Face Enhancer)::\s*\d+%\|[^|]*\|\s*(\d+)/(\d+)")


def run_coach(job, photo, enhance):
    """SadTalker via talk.py --audio, streaming tqdm progress into the job status."""
    # --full animates the whole photo (shoulders included) so it can be cut out
    cmd = ["python3", os.path.join(TH, "talk.py"), photo, "--audio", job.path("narration.wav"),
           "--out", job.path("face.mp4"), "--full"]
    if enhance:
        cmd.append("--enhance")
    log = open(job.path("coach.log"), "w")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=TH)
    buf = b""
    # Renderer is ~70% of the time with enhancement on; enhancer the rest
    weights = {"Face Renderer": (0.0, 0.7 if enhance else 1.0), "Face Enhancer": (0.7, 0.3)}
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        log.write(chunk.decode(errors="replace"))
        buf += chunk
        parts = re.split(rb"[\r\n]", buf)
        buf = parts[-1]
        for line in parts[:-1]:
            m = PROGRESS_RE.search(line.decode(errors="replace"))
            if m:
                base, span = weights[m.group(1)]
                job.progress("coach", base + span * int(m.group(2)) / max(int(m.group(3)), 1))
    log.close()
    if proc.wait() != 0 or not os.path.exists(job.path("face.mp4")):
        raise RuntimeError("talking-head render failed (see coach.log)")
    job.progress("coach", 1.0)


CUTOUT_RE = re.compile(r"Cutout:: (\d+)/(\d+)")


def run_cutout(job):
    """Remove the background and add the sticker outline (Robust Video Matting)."""
    _, _, w, h = chalkboard.COACH_BOX
    cmd = [ST_PY, os.path.join(TH, "cutout.py"), job.path("face.mp4"), job.path("coach"),
           "--width", str(w), "--height", str(h)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=TH, text=True)
    tail = []
    for line in proc.stdout:
        tail = (tail + [line])[-20:]
        m = CUTOUT_RE.search(line)
        if m:
            job.progress("cutout", int(m.group(1)) / max(int(m.group(2)), 1))
    if proc.wait() != 0:
        raise RuntimeError("background removal failed: " + "".join(tail)[-400:])
    job.progress("cutout", 1.0)


def run_board(job, play_id, title, timings):
    board = chalkboard.Board(playbook.PLAYS[play_id], title, timings)
    n = int(timings["duration"] * chalkboard.FPS + 0.999)
    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{chalkboard.W}x{chalkboard.H}", "-r", str(chalkboard.FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", job.path("board.mp4")],
        stdin=subprocess.PIPE)
    for i in range(n):
        ff.stdin.write(board.frame(i / chalkboard.FPS).tobytes())
        if i % 15 == 0:
            job.progress("board", i / n)
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("chalkboard render failed")
    job.progress("board", 1.0)


def run(job, photo, play_id, voice="am_michael", enhance=True, script=None):
    try:
        job.update(state="running", play=play_id, voice=voice, enhance=enhance)

        job.update(stage="check")
        face = check_face(photo)
        if not face["ok"]:
            raise RuntimeError(face["reason"])
        job.progress("check", 1.0)

        job.update(stage="script")
        if script is None:
            script = script_gen.generate(play_id)
        job.update(script=script)
        with open(job.path("script.json"), "w") as f:
            json.dump(script, f, indent=1)
        job.progress("script", 1.0)

        job.update(stage="voice")
        timings = run_tts(job, script, voice)
        job.progress("voice", 1.0)

        # The coach (GPU, slow) and the chalkboard (CPU, fast) render side by side
        job.update(stage="coach")
        errors = []

        def board_thread():
            try:
                run_board(job, play_id, script["title"], timings)
            except Exception as e:  # surfaced after the coach finishes
                errors.append(e)

        t = threading.Thread(target=board_thread)
        t.start()
        run_coach(job, photo, enhance)
        job.update(stage="cutout")
        run_cutout(job)
        t.join()
        if errors:
            raise errors[0]

        job.update(stage="compose")
        compose.compose(job.path("board.mp4"), job.path("coach_rgb.mp4"), job.path("coach_alpha.mp4"),
                        job.path("narration.wav"), job.path("final.mp4"), timings["duration"])
        job.progress("compose", 1.0)
        job.update(state="done", stage=None, finished=time.time())
    except Exception as e:
        job.update(state="error", error=str(e))
        raise


def new_job_from_upload(photo_src, play_id, voice, enhance, script=None):
    job = Job()
    ext = os.path.splitext(photo_src)[1].lower() or ".jpg"
    photo = job.path("headshot" + ext)
    shutil.copy(photo_src, photo)
    return job, photo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", required=True)
    ap.add_argument("--play", required=True, choices=sorted(playbook.PLAYS))
    ap.add_argument("--voice", default="am_michael", choices=sorted(VOICES))
    ap.add_argument("--no-enhance", action="store_true")
    ap.add_argument("--script-file", help="use this script JSON instead of calling the LLM")
    args = ap.parse_args()
    script = json.load(open(args.script_file)) if args.script_file else None
    job, photo = new_job_from_upload(args.photo, args.play, args.voice, not args.no_enhance)
    t0 = time.time()
    run(job, photo, args.play, args.voice, not args.no_enhance, script)
    print(f"done in {time.time() - t0:.0f}s: {job.path('final.mp4')}")
