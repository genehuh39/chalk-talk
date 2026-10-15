#!/usr/bin/env python3
"""Photo + text -> talking-head video.

Step 1: Kokoro TTS (in .venv-tts) turns text into speech.
Step 2: SadTalker (in .venv-sadtalker) lip-syncs the photo to that speech.

Usage:
    python3 talk.py photo.jpg "Hello there!"            # text inline
    python3 talk.py photo.jpg -f script.txt             # text from a file
    python3 talk.py photo.jpg "Hi" --voice am_michael --enhance --out hello.mp4
    python3 talk.py photo.jpg --audio speech.wav        # animate to existing audio
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
TTS_PY = os.path.join(ROOT, ".venv-tts", "bin", "python")
ST_PY = os.path.join(ROOT, ".venv-sadtalker", "bin", "python")
ST_DIR = os.path.join(ROOT, "SadTalker")

TTS_SCRIPT = """
import sys, numpy as np, soundfile as sf
from kokoro import KPipeline
text, voice, speed, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
pipe = KPipeline(lang_code=voice[0], repo_id='hexgrad/Kokoro-82M')
audio = np.concatenate([a for _, _, a in pipe(text, voice=voice, speed=speed)])
sf.write(out, audio, 24000)
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", help="portrait photo (face clearly visible, looking roughly at the camera)")
    ap.add_argument("text", nargs="?", help="what the face should say")
    ap.add_argument("-f", "--text-file", help="read the script from a text file instead")
    ap.add_argument("--audio", help="animate to this existing audio file instead of generating speech")
    ap.add_argument("--voice", default="af_heart",
                    help="Kokoro voice, e.g. af_heart, af_bella, am_michael, am_fenrir, bf_emma, bm_george")
    ap.add_argument("--speed", type=float, default=1.0, help="speech speed (default 1.0)")
    ap.add_argument("--out", help="output .mp4 path (default: outputs/<photo>_<time>.mp4)")
    ap.add_argument("--full", action="store_true",
                    help="paste the animated face back into the full photo (default: cropped face only)")
    ap.add_argument("--move", action="store_true", help="allow more head movement (default: steadier head)")
    ap.add_argument("--enhance", action="store_true", help="sharpen the face with GFPGAN (slower, better detail)")
    ap.add_argument("--size", type=int, choices=[256, 512], default=256, help="face resolution (512 is ~4x slower)")
    args = ap.parse_args()

    text = None
    if args.audio:
        if not os.path.exists(args.audio):
            sys.exit(f"audio not found: {args.audio}")
    elif args.text_file:
        with open(args.text_file) as fh:
            text = fh.read().strip()
    elif args.text:
        text = args.text
    else:
        ap.error("give the text inline, with -f script.txt, or --audio speech.wav")

    photo = os.path.abspath(args.photo)
    if not os.path.exists(photo):
        sys.exit(f"photo not found: {photo}")

    stem = os.path.splitext(os.path.basename(photo))[0]
    out = os.path.abspath(args.out or os.path.join(ROOT, "outputs", f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"))
    os.makedirs(os.path.dirname(out), exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, f"{stem}.wav")
        if args.audio:
            shutil.copy(args.audio, wav)
        else:
            print(f"[1/2] Generating speech ({args.voice})...", flush=True)
            subprocess.run([TTS_PY, "-c", TTS_SCRIPT, text, args.voice, str(args.speed), wav], check=True)

        print("[2/2] Animating face (this takes a few minutes)...", flush=True)
        cmd = [ST_PY, "inference.py", "--driven_audio", wav, "--source_image", photo,
               "--result_dir", tmp, "--size", str(args.size),
               "--preprocess", "full" if args.full else "crop"]
        if not args.move:
            cmd.append("--still")
        if args.enhance:
            cmd += ["--enhancer", "gfpgan"]
        env = dict(os.environ, PYTORCH_ENABLE_MPS_FALLBACK="1")
        subprocess.run(cmd, cwd=ST_DIR, env=env, check=True)

        videos = glob.glob(os.path.join(tmp, "*.mp4"))
        if not videos:
            sys.exit("SadTalker finished but produced no video (was a face detected in the photo?)")
        shutil.move(videos[0], out)

    print(f"\nDone: {out}")


if __name__ == "__main__":
    main()
