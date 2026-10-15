"""Chalk Talk web app.

Run:  .venv/bin/uvicorn app:app --port 8000      then open http://localhost:8000
"""
import io
import json
import os
import queue
import threading

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

import pipeline
import playbook
import script_gen

ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_UPLOAD = 15 * 1024 * 1024

app = FastAPI(title="Chalk Talk")
work = queue.Queue()
pending = []  # job ids waiting, in order
pending_lock = threading.Lock()


def worker():
    # One job at a time: SadTalker owns the GPU
    while True:
        job, photo, play_id, voice, enhance = work.get()
        with pending_lock:
            pending.remove(job.id)
        try:
            pipeline.run(job, photo, play_id, voice, enhance)
        except Exception:
            pass  # already recorded in the job status
        work.task_done()


threading.Thread(target=worker, daemon=True).start()


@app.get("/api/menu")
def menu():
    return {"formations": playbook.menu(), "voices": pipeline.VOICES}


@app.get("/api/config")
def config():
    try:
        provider, _, model = script_gen.make_client()
        return {"llm_ready": True, "provider": provider, "model": model}
    except RuntimeError as e:
        return {"llm_ready": False, "error": str(e)}


@app.post("/api/jobs")
async def create_job(photo: UploadFile = File(...), play_id: str = Form(...),
                     voice: str = Form("am_michael"), enhance: bool = Form(True)):
    if play_id not in playbook.PLAYS:
        raise HTTPException(400, "Unknown play")
    if voice not in pipeline.VOICES:
        raise HTTPException(400, "Unknown voice")
    try:
        script_gen.make_client()
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    data = await photo.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Photo is over 15 MB")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception:
        raise HTTPException(400, "Couldn't read that image. Use a JPG or PNG.")
    img.thumbnail((1024, 1024))  # SadTalker --full + enhancer doubles this

    job = pipeline.Job()
    path = job.path("headshot.jpg")
    img.save(path, quality=92)
    with pending_lock:
        pending.append(job.id)
    work.put((job, path, play_id, voice, enhance))
    return {"id": job.id}


def load_status(job_id):
    path = os.path.join(pipeline.JOBS, os.path.basename(job_id), "status.json")
    if not os.path.exists(path):
        raise HTTPException(404, "No such job")
    with open(path) as f:
        return json.load(f)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    status = load_status(job_id)
    with pending_lock:
        status["queue_position"] = pending.index(job_id) + 1 if job_id in pending else 0
    return status


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: str, download: bool = False):
    load_status(job_id)
    path = os.path.join(pipeline.JOBS, os.path.basename(job_id), "final.mp4")
    if not os.path.exists(path):
        raise HTTPException(404, "Video isn't ready")
    status = load_status(job_id)
    name = f"chalk-talk-{status.get('play', 'play')}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=name if download else None)


app.mount("/", StaticFiles(directory=os.path.join(ROOT, "static"), html=True), name="static")
