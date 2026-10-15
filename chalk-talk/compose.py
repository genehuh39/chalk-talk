"""Final composite: chalkboard + background-removed coach cutout + narration audio."""
import subprocess

from chalkboard import COACH_BOX


def compose(board_mp4, cut_rgb_mp4, cut_alpha_mp4, narration_wav, out_mp4, duration):
    x, y, w, h = COACH_BOX
    graph = (
        f"[1:v]scale={w}:{h},format=rgba[c];"
        f"[2:v]scale={w}:{h},format=gray[a];"
        f"[c][a]alphamerge[coach];"
        f"[0:v][coach]overlay={x}:{y}:eof_action=repeat[v]"
    )
    cmd = [
        "ffmpeg", "-loglevel", "error", "-y",
        "-i", board_mp4, "-i", cut_rgb_mp4, "-i", cut_alpha_mp4, "-i", narration_wav,
        "-filter_complex", graph, "-map", "[v]", "-map", "3:a",
        "-t", f"{duration:.3f}", "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_mp4,
    ]
    subprocess.run(cmd, check=True)
    return out_mp4
