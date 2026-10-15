#!/usr/bin/env python3
"""Narration beats -> one wav + timings (run with .venv-tts/bin/python).

Input JSON:  {"voice": "am_michael", "speed": 1.0, "gap": 0.25,
              "beats": [{"cue": "show_formation", "text": "..."}, ...]}
Outputs:     <out>.wav and <out>.json:
             {"duration": 31.2,
              "beats": [{"cue": ..., "text": ..., "start": 0.0, "end": 4.1}, ...],
              "words": [{"text": "Mesh", "start": 0.12, "end": 0.40}, ...]}

Usage: .venv-tts/bin/python tts.py script.json out_basename
"""
import json
import sys

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SR = 24000


def synthesize(beats, voice="af_heart", speed=1.0, gap=0.25):
    pipe = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M")
    audio, out_beats, words, t = [], [], [], 0.0
    silence = np.zeros(int(gap * SR), dtype=np.float32)
    for beat in beats:
        start = t
        for r in pipe(beat["text"], voice=voice, speed=speed):
            chunk = r.audio.numpy() if hasattr(r.audio, "numpy") else np.asarray(r.audio)
            for tok in r.tokens or []:
                if tok.start_ts is None:
                    continue
                if not any(ch.isalnum() for ch in tok.text) and words:
                    words[-1]["text"] += tok.text  # attach punctuation to the previous word
                    continue
                words.append({"text": tok.text, "start": round(t + tok.start_ts, 3),
                              "end": round(t + (tok.end_ts or tok.start_ts), 3)})
            audio.append(chunk)
            t += len(chunk) / SR
        out_beats.append({**beat, "start": round(start, 3), "end": round(t + gap, 3)})
        audio.append(silence)
        t += gap
    return np.concatenate(audio), {"duration": round(t, 3), "beats": out_beats, "words": words}


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    wav, timings = synthesize(spec["beats"], spec.get("voice", "af_heart"),
                              spec.get("speed", 1.0), spec.get("gap", 0.25))
    sf.write(out + ".wav", wav, SR)
    json.dump(timings, open(out + ".json", "w"), indent=1)
    print(f"{timings['duration']:.2f}s, {len(timings['words'])} words")
