"""Animated football chalkboard, rendered frame by frame with Pillow and piped to ffmpeg.

The animation is driven by a timings dict (from talking-head/tts.py):
    {"duration": 31.2,
     "beats": [{"cue": "show_formation", "text": "...", "start": 0.0, "end": 4.1}, ...],
     "words": [{"text": "Mesh", "start": 0.12, "end": 0.40}, ...]}

Usage:
    python chalkboard.py --demo shotgun_mesh          # fake timeline -> previews/shotgun_mesh.mp4
    python chalkboard.py --png                        # one still per play -> previews/<play>.png
"""
import argparse
import math
import os
import random
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import playbook

W, H, FPS = 1080, 1920, 30

# Field geometry: yards -> pixels
SCALE = 23
OX = W // 2
LOS_Y = 760
FIELD_TOP_YD, FIELD_BOTTOM_YD = 20, -10

# Talking-head cutout box (compose.py overlays the coach here, bottom-anchored)
COACH_BOX = (0, H - 860, W, 860)  # x, y, width, height

FONTS = "/System/Library/Fonts/Supplemental/"
CHALKDUSTER = FONTS + "Chalkduster.ttf"
CHALKBOARD = FONTS + "ChalkboardSE.ttc"

SLATE = (30, 44, 38)
WHITE = (238, 238, 228)
DIM = (170, 178, 168)
YELLOW = (246, 214, 92)
RED = (242, 104, 96)
BLUE = (140, 196, 236)

CUES = ["show_formation", "run_play", "show_defense", "highlight_key", "play_vs_defense", "recap"]


def font(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)


def yd(x, y):
    return (OX + x * SCALE, LOS_Y - y * SCALE)


def clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def ease(v):
    v = clamp01(v)
    return v * v * (3 - 2 * v)


# ----------------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------------
def jitter_polyline(pts, seed, step=14, amp=1.3):
    """Subdivide a polyline and wobble it slightly so it looks hand-drawn."""
    rng = random.Random(seed)
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(seg / step))
        nx, ny = (-(y1 - y0) / seg, (x1 - x0) / seg) if seg else (0, 0)
        for i in range(1, n + 1):
            t = i / n
            off = rng.gauss(0, amp) if i < n else 0
            out.append((x0 + (x1 - x0) * t + nx * off, y0 + (y1 - y0) * t + ny * off))
    return out


def cut_polyline(pts, frac):
    """Return the leading `frac` (0..1) of a polyline by length."""
    if frac >= 1:
        return pts
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    target = sum(lens) * frac
    out = [pts[0]]
    for (a, b), L in zip(zip(pts, pts[1:]), lens):
        if target <= L:
            t = target / L if L else 0
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            return out
        target -= L
        out.append(b)
    return out


def point_along(pts, frac):
    return cut_polyline(pts, frac)[-1]


def tip_direction(pts):
    for a, b in zip(reversed(pts[:-1]), reversed(pts[1:])):
        if a != b:
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            return (b[0] - a[0]) / L, (b[1] - a[1]) / L
    return 0.0, -1.0


# ----------------------------------------------------------------------------
# Chalk drawing primitives (everything is drawn on an RGBA layer, then grained)
# ----------------------------------------------------------------------------
def stroke(d, pts, color, width, alpha=255, dashed=False):
    if len(pts) < 2:
        return
    fill = color + (alpha,)
    if not dashed:
        d.line(pts, fill=fill, width=width, joint="curve")
        return
    on, off, acc, drawing, seg = 16, 11, 0.0, True, [pts[0]]
    for a, b in zip(pts, pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        pos = 0.0
        while pos < L:
            left = (on if drawing else off) - acc
            step = min(left, L - pos)
            pos += step
            acc += step
            p = (a[0] + (b[0] - a[0]) * pos / L, a[1] + (b[1] - a[1]) * pos / L)
            if drawing:
                seg.append(p)
            if acc >= (on if drawing else off):
                if drawing and len(seg) > 1:
                    d.line(seg, fill=fill, width=width)
                drawing, acc, seg = not drawing, 0.0, [p]
    if drawing and len(seg) > 1:
        d.line(seg, fill=fill, width=width)


def arrowhead(d, tip, direction, color, width, alpha=255, size=17):
    dx, dy = direction
    for s in (1, -1):
        ang = math.atan2(dy, dx) + math.pi + s * 0.5
        d.line([tip, (tip[0] + size * math.cos(ang), tip[1] + size * math.sin(ang))],
               fill=color + (alpha,), width=width)


def t_end(d, tip, direction, color, width, alpha=255, size=13):
    dx, dy = direction
    px, py = -dy, dx
    d.line([(tip[0] + px * size, tip[1] + py * size), (tip[0] - px * size, tip[1] - py * size)],
           fill=color + (alpha,), width=width)


def chalk_circle(d, c, r, color, width, frac=1.0, alpha=255, start=-90):
    if frac <= 0:
        return
    box = [c[0] - r, c[1] - r, c[0] + r, c[1] + r]
    if frac >= 1:
        d.ellipse(box, outline=color + (alpha,), width=width)
    else:
        d.arc(box, start, start + 360 * frac, fill=color + (alpha,), width=width)


def chalk_x(d, c, r, color, width, frac=1.0, alpha=255):
    a = clamp01(frac * 2)
    b = clamp01(frac * 2 - 1)
    if a > 0:
        d.line([(c[0] - r, c[1] - r), (c[0] - r + 2 * r * a, c[1] - r + 2 * r * a)], fill=color + (alpha,), width=width)
    if b > 0:
        d.line([(c[0] + r, c[1] - r), (c[0] + r - 2 * r * b, c[1] - r + 2 * r * b)], fill=color + (alpha,), width=width)


def text_center(d, xy, text, fnt, color, alpha=255):
    d.text(xy, text, font=fnt, fill=color + (alpha,), anchor="mm")


def wrap(text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ----------------------------------------------------------------------------
# Static background (slate texture, field markings, frames) -- built once
# ----------------------------------------------------------------------------
def make_grain(seed=7):
    rng = np.random.default_rng(seed)
    fine = rng.random((H, W)).astype(np.float32)
    coarse = np.asarray(Image.fromarray((rng.random((H // 24, W // 24)) * 255).astype(np.uint8))
                        .resize((W, H), Image.BICUBIC), dtype=np.float32) / 255
    return np.clip(0.42 + 0.45 * fine + 0.25 * coarse, 0, 1)


def apply_grain(layer, grain):
    arr = np.asarray(layer, dtype=np.float32).copy()
    arr[..., 3] *= grain
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def make_slate(seed=3):
    rng = np.random.default_rng(seed)
    base = np.ones((H, W, 3), np.float32) * np.array(SLATE, np.float32)
    blotch = np.asarray(Image.fromarray((rng.random((H // 90, W // 90)) * 255).astype(np.uint8))
                        .resize((W, H), Image.BICUBIC), dtype=np.float32)[..., None] / 255
    base += (blotch - 0.5) * 16
    base += rng.normal(0, 3.5, (H, W, 1))
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")
    # Faint erased-chalk smudges
    smudge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(smudge)
    r = random.Random(seed)
    for _ in range(14):
        x, y = r.uniform(0, W), r.uniform(0, H)
        sd.line([(x, y), (x + r.uniform(-260, 260), y + r.uniform(-60, 60))],
                fill=(255, 255, 255, r.randint(8, 18)), width=r.randint(40, 90))
    smudge = smudge.filter(ImageFilter.GaussianBlur(26))
    img = Image.alpha_composite(img.convert("RGBA"), smudge)
    return img


def draw_static(play, title, grain):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Title
    for size in (62, 56, 50, 44):
        tf = font(CHALKDUSTER, size)
        lines = wrap(title.upper(), tf, W - 110)
        if len(lines) == 1:
            break
    lines = lines[:2]
    lh = int(size * 1.2)
    y0 = 78 if len(lines) == 1 else 56
    for i, line in enumerate(lines):
        text_center(d, (W / 2, y0 + i * lh), line, tf, WHITE)
    uy = y0 + (len(lines) - 1) * lh + int(size * 0.85)
    stroke(d, jitter_polyline([(140, uy), (W - 140, uy)], 1, amp=2), YELLOW, 5)

    # Formation / play line under the title
    sub = f"{playbook.FORMATIONS[play['formation']]['name']}  \u00b7  {play['name']}".upper()
    text_center(d, (W / 2, uy + 38), sub, font(CHALKBOARD, 30, 2), DIM, 235)

    # Field: 5-yard lines, LOS, hash ticks, numbers
    nf = font(CHALKBOARD, 26, 1)
    for yv in range(FIELD_BOTTOM_YD, FIELD_TOP_YD + 1, 5):
        y = yd(0, yv)[1]
        stroke(d, jitter_polyline([(40, y), (W - 40, y)], 100 + yv, amp=1.0), DIM, 3, alpha=110)
        if yv > 0:
            d.text((52, y - 34), f"+{yv}", font=nf, fill=DIM + (120,))
    for yv in range(FIELD_BOTTOM_YD, FIELD_TOP_YD + 1):
        y = yd(0, yv)[1]
        for hx in (-6.7, 6.7):
            x = yd(hx, 0)[0]
            d.line([(x - 8, y), (x + 8, y)], fill=DIM + (90,), width=3)
    los = yd(0, 0)[1]
    stroke(d, jitter_polyline([(40, los), (W - 40, los)], 99, amp=1.2), BLUE, 4, alpha=200, dashed=True)

    base = make_slate()
    return Image.alpha_composite(base, apply_grain(layer, grain)), uy


# ----------------------------------------------------------------------------
# Animated board
# ----------------------------------------------------------------------------
class Board:
    def __init__(self, play, title, timings):
        self.play = play
        self.timings = timings
        self.grain = make_grain()
        self.base, self.header_y = draw_static(play, title, self.grain)
        self.f_label = font(CHALKBOARD, 22, 2)
        self.f_answer = font(CHALKBOARD, 32, 2)
        self.f_callout = font(CHALKBOARD, 34, 2)
        self.f_stamp = font(CHALKDUSTER, 54)
        self.f_recap = font(CHALKDUSTER, 66)
        self.f_caption = font(CHALKBOARD, 62, 2)

        self.off = [self._prep(p, i, "o") for i, p in enumerate(play["offense"])]
        self.dfn = [self._prep(p, i, "d") for i, p in enumerate(play["defense"])]
        self.key = next(e for e in self.dfn if e["id"] == play["key_defender"])
        self.stop_px = yd(*play["stop_point"])

        beats = timings["beats"]
        first = lambda *cues: next((b for b in beats if b["cue"] in cues), None)
        dur = timings["duration"]
        self.b_form = first("show_formation") or {"start": 0.0, "end": 0.01}
        self.b_route = first("run_play")
        self.b_def = first("show_defense") or self._quick(first("highlight_key", "play_vs_defense", "recap"), dur)
        self.b_hl = [b for b in beats if b["cue"] == "highlight_key"]
        self.b_pvd = first("play_vs_defense")
        self.b_recap = first("recap")
        self.captions = self._caption_chunks(timings)

    @staticmethod
    def _quick(beat, dur):
        s = beat["start"] if beat else dur
        return {"start": s, "end": s + 1.2}

    def _prep(self, p, i, side):
        start = yd(*p["pos"])
        raw = [start] + [yd(*q) for q in p["path"]]
        return {
            "id": p["id"], "label": p["label"], "kind": p["kind"], "i": i,
            "start": start, "raw": raw,
            "path": jitter_polyline(raw, hash((side, p["id"])) & 0xFFFF) if len(raw) > 1 else raw,
        }

    # -- timing helpers -------------------------------------------------------
    @staticmethod
    def prog(t, beat, a=0.0, b=1.0):
        """Progress through the [a, b] fraction of a beat."""
        if not beat:
            return 0.0
        dur = max(beat["end"] - beat["start"], 0.01)
        return clamp01((t - beat["start"] - a * dur) / ((b - a) * dur))

    def motion(self, t):
        return ease(self.prog(t, self.b_pvd, 0.05, 0.7)) if self.b_pvd else 0.0

    # -- captions --------------------------------------------------------------
    @staticmethod
    def _caption_chunks(timings):
        words = timings.get("words") or []
        if not words:  # fall back to spreading each beat's words evenly
            for b in timings["beats"]:
                ws = b["text"].split()
                span = (b["end"] - b["start"]) / max(len(ws), 1)
                words += [{"text": w, "start": b["start"] + i * span, "end": b["start"] + (i + 1) * span}
                          for i, w in enumerate(ws)]
        chunks, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= 4 or w["text"][-1:] in ".,!?;:":
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)
        for i, c in enumerate(chunks):
            c_end = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else c[-1]["end"] + 0.6
            chunks[i] = {"words": c, "start": c[0]["start"], "end": c_end}
        return chunks

    # -- drawing ----------------------------------------------------------------
    def _draw_path(self, d, e, frac, color, alpha=255, dfn=False):
        if frac <= 0 or len(e["path"]) < 2 or not e["kind"]:
            return
        pts = cut_polyline(e["path"], frac)
        kind = e["kind"]
        width = {"run": 7, "fill": 7, "pull": 5}.get(kind, 4)
        dashed = kind in ("fake", "drop", "zone")
        stroke(d, pts, color, width, alpha, dashed)
        direction = tip_direction(pts)
        if kind in ("block", "pull"):
            if frac >= 0.999:
                t_end(d, pts[-1], direction, color, width, alpha)
        elif kind != "drop":
            arrowhead(d, pts[-1], direction, color, width, alpha)

    def _player(self, d, e, pos, frac, dfn, alpha=255):
        if frac <= 0:
            return
        if dfn:
            chalk_x(d, pos, 15, YELLOW, 6, frac, alpha)
            if frac >= 1 and e["label"]:
                d.text((pos[0] + 16, pos[1] - 34), e["label"], font=self.f_label, fill=YELLOW + (alpha,))
        else:
            chalk_circle(d, pos, 18, WHITE, 5, frac, alpha)
            if frac >= 1 and e["label"]:
                d.text(pos, e["label"], font=self.f_label, fill=WHITE + (alpha,), anchor="mm")

    def frame(self, t):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        m = self.motion(t)
        p_form = self.prog(t, self.b_form, 0, 0.6)
        p_def_players = self.prog(t, self.b_def, 0, 0.45)
        p_def_paths = self.prog(t, self.b_def, 0.45, 0.9)
        p_route = self.prog(t, self.b_route, 0, 0.75) if self.b_route else 0.0

        def pos_of(e):
            return point_along(e["raw"], m) if m > 0 and len(e["raw"]) > 1 else e["start"]

        # Offense paths: drawn in during run_play; during the live rep they become faint plans + solid trails
        for e in self.off:
            if m > 0:
                self._draw_path(d, e, 1.0, WHITE, 70)
                self._draw_path(d, e, m, WHITE, 255)
            else:
                self._draw_path(d, e, p_route, WHITE)
        for e in self.dfn:
            if m > 0:
                self._draw_path(d, e, 1.0, YELLOW, 70, True)
                self._draw_path(d, e, m, YELLOW, 255, True)
            else:
                self._draw_path(d, e, p_def_paths, YELLOW, 255, True)

        n_off, n_def = len(self.off), len(self.dfn)
        for e in self.off:
            k = e["i"] / n_off * 0.7
            self._player(d, e, pos_of(e), clamp01((p_form - k) / 0.3), False)
        for e in self.dfn:
            k = e["i"] / n_def * 0.7
            self._player(d, e, pos_of(e), clamp01((p_def_players - k) / 0.3), True)

        # Key defender spotlight
        hl_active = any(b["start"] <= t < b["end"] for b in self.b_hl)
        hl_seen = any(t >= b["start"] for b in self.b_hl)
        if hl_seen:
            kp = pos_of(self.key)
            first_hl = next(b for b in self.b_hl if t >= b["start"])
            draw_in = self.prog(t, first_hl, 0, 0.25)
            r = 38 + (6 * math.sin(t * 2 * math.pi * 1.4) if hl_active else 0)
            chalk_circle(d, kp, r, RED, 6, draw_in)
            if draw_in >= 1 and (hl_active or m == 0):
                label = self.play["key_label"]
                lw = self.f_callout.getlength(label)
                cx = min(max(kp[0], lw / 2 + 30), W - lw / 2 - 30)
                cy = kp[1] - r - 34
                d.rounded_rectangle([cx - lw / 2 - 14, cy - 26, cx + lw / 2 + 14, cy + 26], 10,
                                    fill=SLATE + (235,), outline=RED + (255,), width=3)
                text_center(d, (cx, cy), label, self.f_callout, RED)

        # Stop stamp after the live rep
        if self.b_pvd:
            p_stamp = self.prog(t, self.b_pvd, 0.7, 0.82)
            if p_stamp > 0:
                chalk_x(d, self.stop_px, 34, RED, 9, p_stamp)
                if p_stamp >= 1:
                    sx = min(max(self.stop_px[0], 240), W - 240)
                    sy = self.stop_px[1] - 78 if self.stop_px[1] > 330 else self.stop_px[1] + 80
                    sw = self.f_stamp.getlength(self.play["stop_text"])
                    d.rounded_rectangle([sx - sw / 2 - 18, sy - 40, sx + sw / 2 + 18, sy + 40], 12,
                                        fill=SLATE + (235,), outline=RED + (255,), width=4)
                    text_center(d, (sx, sy), self.play["stop_text"], self.f_stamp, RED)

        # Recap banner
        if self.b_recap:
            p_rc = ease(self.prog(t, self.b_recap, 0, 0.25))
            if p_rc > 0:
                name = self.play["defense_name"].upper()
                bw = self.f_recap.getlength(name) + 80
                cy = yd(0, 17.5)[1]
                box = [W / 2 - bw / 2, cy - 58, W / 2 + bw / 2, cy + 58]
                d.rectangle(box, fill=SLATE + (int(230 * p_rc),), outline=YELLOW + (int(255 * p_rc),), width=6)
                text_center(d, (W / 2, cy), name, self.f_recap, YELLOW, int(255 * p_rc))

        # "The answer" line under the title, revealed with the defense
        if p_def_players > 0:
            a = int(255 * clamp01(p_def_players * 3))
            lead, name = "THE ANSWER:  ", self.play["defense_name"].upper()
            fa = self.f_answer
            x = (W - fa.getlength(lead + name)) / 2
            y = self.header_y + 80
            d.text((x, y), lead, font=fa, fill=DIM + (a,), anchor="lm")
            d.text((x + fa.getlength(lead), y), name, font=fa, fill=YELLOW + (a,), anchor="lm")

        self._draw_caption(d, t)
        return Image.alpha_composite(self.base, apply_grain(layer, self.grain)).convert("RGB")

    def _draw_caption(self, d, t):
        chunk = next((c for c in self.captions if c["start"] <= t < c["end"]), None)
        if not chunk:
            return
        f = self.f_caption
        words = [w["text"] for w in chunk["words"]]
        space = f.getlength(" ")
        lines, cur, cur_w = [], [], 0
        for i, w in enumerate(words):
            wl = f.getlength(w)
            if cur and cur_w + space + wl > W - 120:
                lines.append(cur)
                cur, cur_w = [], 0
            cur_w += (space if cur else 0) + wl
            cur.append(i)
        lines.append(cur)
        y = 1032 - (len(lines) - 1) * 40
        for line in lines:
            total = sum(f.getlength(words[i]) for i in line) + space * (len(line) - 1)
            x = (W - total) / 2
            for i in line:
                w = chunk["words"][i]
                color = YELLOW if w["start"] <= t < max(w["end"], w["start"] + 0.12) else WHITE
                d.text((x, y), words[i], font=f, fill=color + (255,), anchor="lm",
                       stroke_width=5, stroke_fill=(16, 24, 20, 255))
                x += f.getlength(words[i]) + space
            y += 80


def render(play_id, title, timings, out_path, fps=FPS):
    """Render the chalkboard video (no audio) for one play, timed to the narration."""
    board = Board(playbook.PLAYS[play_id], title, timings)
    n = int(math.ceil(timings["duration"] * fps))
    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", out_path],
        stdin=subprocess.PIPE)
    for i in range(n):
        ff.stdin.write(board.frame(i / fps).tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed rendering the chalkboard")
    return out_path


def demo_timings(play):
    script = [
        ("show_formation", f"Here's the {playbook.FORMATIONS[play['formation']]['name']}."),
        ("run_play", f"They love to run {play['name']}."),
        ("show_defense", f"Here's how you stop it: {play['defense_name']}."),
        ("highlight_key", "Watch this guy. He's the whole key."),
        ("play_vs_defense", "Snap it, and there's nowhere to go."),
        ("recap", f"{play['defense_name']}. Go win the down."),
    ]
    beats, t = [], 0.0
    for cue, text in script:
        dur = 5.0 if cue != "play_vs_defense" else 6.0
        beats.append({"cue": cue, "text": text, "start": t, "end": t + dur})
        t += dur
    return {"duration": t, "beats": beats, "words": []}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", help="play id to render with a fake timeline")
    ap.add_argument("--png", action="store_true", help="render a still diagram of every play")
    args = ap.parse_args()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previews")
    os.makedirs(out_dir, exist_ok=True)
    if args.png:
        for pid, p in playbook.PLAYS.items():
            tm = demo_timings(p)
            tm["beats"] = [b for b in tm["beats"] if b["cue"] != "play_vs_defense" and b["cue"] != "recap"]
            board = Board(p, f"Beat the {p['name']}", tm)
            board.frame(tm["beats"][-1]["end"] - 0.5).save(os.path.join(out_dir, f"{pid}.png"))
            print("wrote", pid)
    if args.demo:
        p = playbook.PLAYS[args.demo]
        out = render(args.demo, f"How to stop {p['name']}", demo_timings(p),
                     os.path.join(out_dir, f"{args.demo}.mp4"))
        print("wrote", out)
