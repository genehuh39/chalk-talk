#!/usr/bin/env python3
"""Quick check that a photo has exactly one usable face (run with .venv-sadtalker/bin/python).

Prints JSON: {"faces": 1, "ok": true, "reason": ""}
Usage: .venv-sadtalker/bin/python face_check.py photo.jpg
"""
import json
import os
import sys

import cv2
import torch
from facexlib.detection import init_detection_model

WEIGHTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SadTalker", "gfpgan", "weights")


def check(path):
    img = cv2.imread(path)
    if img is None:
        return {"faces": 0, "ok": False, "reason": "couldn't read the image"}
    h, w = img.shape[:2]
    scale = 800 / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    det = init_detection_model("retinaface_resnet50", half=False, device="cpu", model_rootpath=WEIGHTS)
    with torch.no_grad():
        boxes = det.detect_faces(img, 0.9)
    faces = [b for b in boxes if (b[2] - b[0]) * (b[3] - b[1]) > 0.01 * img.shape[0] * img.shape[1]]
    if not faces:
        return {"faces": 0, "ok": False, "reason": "no face found; use a clear, front-facing headshot"}
    if len(faces) > 1:
        return {"faces": len(faces), "ok": False, "reason": "more than one face; use a photo of just one person"}
    return {"faces": 1, "ok": True, "reason": ""}


if __name__ == "__main__":
    print(json.dumps(check(sys.argv[1])))
