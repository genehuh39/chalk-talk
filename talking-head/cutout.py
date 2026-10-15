#!/usr/bin/env python3
"""Talking-head video -> background-removed "sticker" cutout (run with .venv-sadtalker/bin/python).

Uses Robust Video Matting (temporally stable, no flicker), then adds a white outline and a soft
drop shadow. The result is sized to a box, bottom-anchored and horizontally centered, and written as
two videos: straight RGB and a grayscale alpha matte (combine with ffmpeg alphamerge).

Usage: .venv-sadtalker/bin/python cutout.py face.mp4 out_basename [--width 1080 --height 860]
       -> out_basename_rgb.mp4, out_basename_alpha.mp4
"""
import argparse
import json
import subprocess

import numpy as np
import torch
import torch.nn.functional as F


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                          "-show_entries", "stream=width,height,r_frame_rate,nb_read_packets",
                          "-of", "json", path], capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return s["width"], s["height"], float(num) / float(den), int(s["nb_read_packets"])


def writer(path, w, h, fps, pix_fmt):
    return subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", pix_fmt, "-s", f"{w}x{h}",
         "-r", f"{fps}", "-i", "-", "-c:v", "libx264", "-crf", "14", "-preset", "medium",
         "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)


def blur(x, k):
    pad = k // 2
    x = F.avg_pool2d(F.pad(x, (pad, pad, 0, 0), mode="replicate"), (1, k), stride=1)
    return F.avg_pool2d(F.pad(x, (0, 0, pad, pad), mode="replicate"), (k, 1), stride=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=860)
    ap.add_argument("--outline", type=int, default=7, help="white outline thickness in output pixels")
    args = ap.parse_args()

    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = torch.hub.load("PeterL1n/RobustVideoMatting", "mobilenetv3", trust_repo=True, verbose=False)
    model = model.eval().to(dev)

    w, h, fps, n = probe(args.video)
    BW, BH = args.width, args.height
    scale = BH / h
    sw = int(round(w * scale))
    dr = min(1.0, 512 / max(w, h))  # RVM's recommended internal resolution

    reader = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", args.video, "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    out_rgb = writer(args.out + "_rgb.mp4", BW, BH, fps, "rgb24")
    out_a = writer(args.out + "_alpha.mp4", BW, BH, fps, "gray")

    rec = [None] * 4
    r = args.outline
    fade_px = 90.0
    frame_bytes = w * h * 3
    i = 0
    with torch.no_grad():
        while True:
            buf = reader.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            src = torch.from_numpy(np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy())
            src = src.permute(2, 0, 1)[None].float().div(255).to(dev)
            fgr, pha, *rec = model(src, *rec, downsample_ratio=dr)

            fgr = F.interpolate(fgr, size=(BH, sw), mode="bilinear", align_corners=False)
            pha = F.interpolate(pha, size=(BH, sw), mode="bilinear", align_corners=False).clamp(0, 1)
            # Fit the box: crop or pad horizontally, keeping the subject centered
            if sw >= BW:
                x0 = (sw - BW) // 2
                fgr, pha = fgr[..., x0:x0 + BW], pha[..., x0:x0 + BW]
                left, right = 0, BW
            else:
                padl = (BW - sw) // 2
                fgr = F.pad(fgr, (padl, BW - sw - padl))
                pha = F.pad(pha, (padl, BW - sw - padl))
                left, right = padl, padl + sw

            # Where the photo itself crops the body (its left/right edges), fade the body out
            # instead of leaving a hard vertical cut, and don't outline that cut.
            xs = torch.arange(BW, device=dev, dtype=pha.dtype)
            fade = torch.minimum(((xs - left) / fade_px).clamp(0, 1), ((right - 1 - xs) / fade_px).clamp(0, 1))
            if sw >= BW:
                fade = torch.ones_like(fade)
            pha = pha * fade.view(1, 1, 1, BW)

            # Sticker outline: dilate the matte, soften it, fill the ring with white
            ring = F.max_pool2d(pha, 2 * r + 1, stride=1, padding=r)
            ring = blur(ring, 3).clamp(0, 1)
            ring = ring * fade.view(1, 1, 1, BW)
            ring = torch.maximum(ring, pha)
            premult = fgr * pha + (ring - pha)
            # Soft drop shadow below/behind the outline
            shadow = blur(F.pad(ring, (0, 0, 14, 0))[..., :BH, :], 31) * 0.45
            alpha = ring + shadow * (1 - ring)
            rgb = premult / alpha.clamp(min=1e-4)

            out_rgb.stdin.write((rgb.clamp(0, 1)[0].permute(1, 2, 0) * 255).byte().cpu().numpy().tobytes())
            out_a.stdin.write((alpha[0, 0] * 255).byte().cpu().numpy().tobytes())
            i += 1
            if i % 10 == 0 or i == n:
                print(f"Cutout:: {i}/{n}", flush=True)

    reader.wait()
    for p in (out_rgb, out_a):
        p.stdin.close()
        if p.wait() != 0:
            raise SystemExit("ffmpeg failed writing the cutout")


if __name__ == "__main__":
    main()
