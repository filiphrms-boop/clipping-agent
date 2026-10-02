#!/usr/bin/env python3
"""
Stage 2b: score short source clips and propose in/out points objectively.

Transcript-based selection (select_clips.py) cannot work on material with no
speech — gameplay, brand assets, trailers. This stage measures the two signals
that actually carry a trick or a fail:

  * AUDIO ENERGY  — impacts, crashes, reactions, music swells (RMS envelope)
  * VISUAL MOTION — how much the frame is changing (mean abs frame difference)

Both are sampled onto a common 100 ms grid, normalised, and combined. The
best-moment window is the highest-energy window of a requested length.

    python3 pick_moments.py clip.mp4 [clip2.mp4 ...]
                            [--window 2.5] [--json ranked.json] [--top 5]

Prints a ranked shortlist with a suggested in/out per clip, and writes JSON.
Nothing here is generative — it only measures what the footage already does.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

GRID = 0.10            # seconds per analysis bin
MOTION_W = 160         # analysis resolution (w x h) — cheap, plenty for motion
MOTION_H = 90
MOTION_WEIGHT = 0.55   # combined score = w*motion + (1-w)*audio
FFMPEG_CANDIDATES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
]


def find_ffmpeg():
    for cand in FFMPEG_CANDIDATES + [shutil.which("ffmpeg")]:
        if cand and Path(cand).exists():
            return cand
    raise SystemExit("ffmpeg not found")


def duration_of(ffmpeg, path):
    fp = str(Path(ffmpeg).with_name("ffprobe"))
    if not Path(fp).exists():
        fp = "ffprobe"
    out = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def has_audio(ffmpeg, path):
    fp = str(Path(ffmpeg).with_name("ffprobe"))
    if not Path(fp).exists():
        fp = "ffprobe"
    out = subprocess.run([fp, "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return bool(out)


def motion_envelope(ffmpeg, path):
    """Per-frame mean absolute difference between consecutive greyscale frames."""
    cmd = [ffmpeg, "-v", "error", "-i", str(path),
           "-vf", f"scale={MOTION_W}:{MOTION_H},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    px = MOTION_W * MOTION_H
    n = len(raw) // px
    if n < 2:
        return np.zeros(0)
    frames = np.frombuffer(raw[:n * px], dtype=np.uint8).reshape(n, px).astype(np.float32)
    return np.abs(np.diff(frames, axis=0)).mean(axis=1)


def audio_envelope(ffmpeg, path, sr=8000):
    """RMS in ~100 ms windows."""
    cmd = [ffmpeg, "-v", "error", "-i", str(path),
           "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    if not raw:
        return np.zeros(0)
    x = np.frombuffer(raw[:len(raw) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    win = max(1, int(sr * GRID))
    n = len(x) // win
    if n == 0:
        return np.zeros(0)
    return np.sqrt((x[:n * win].reshape(n, win) ** 2).mean(axis=1))


def resample(env, src_rate, grid=GRID):
    """Linear-resample a per-frame envelope onto the common time grid."""
    if env.size == 0:
        return np.zeros(0)
    src_t = np.arange(env.size) / src_rate
    n = int(src_t[-1] / grid) + 1
    tgt_t = np.arange(n) * grid
    return np.interp(tgt_t, src_t, env)


def norm(v):
    if v.size == 0:
        return v
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-9:
        return np.zeros_like(v)
    return (v - lo) / (hi - lo)


def smooth(v, k=3):
    if v.size < k:
        return v
    ker = np.ones(k) / k
    return np.convolve(v, ker, mode="same")


def best_window(score, grid, length):
    """Start time of the highest-mean window of `length` seconds."""
    w = max(1, int(round(length / grid)))
    if score.size <= w:
        return 0.0
    csum = np.concatenate([[0.0], np.cumsum(score)])
    means = (csum[w:] - csum[:-w]) / w
    return float(int(np.argmax(means)) * grid)


def analyse(ffmpeg, path, window=2.5):
    dur = duration_of(ffmpeg, path)
    fps = 30.0  # sources are 30/60fps; normalised by resampling anyway
    try:
        fp = str(Path(ffmpeg).with_name("ffprobe"))
        r = subprocess.run([fp, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True).stdout.strip()
        num, den = r.split("/")
        fps = float(num) / float(den or 1)
    except Exception:
        pass

    mo = norm(resample(motion_envelope(ffmpeg, path), fps))
    au_raw = audio_envelope(ffmpeg, path)
    au = norm(resample(au_raw, 1.0 / GRID))
    if not has_audio(ffmpeg, path) or au_raw.size == 0:
        au = np.zeros_like(mo) if mo.size else np.zeros(0)

    n = max(mo.size, au.size)
    if n == 0:
        return None
    mo = np.pad(mo, (0, n - mo.size))
    au = np.pad(au, (0, n - au.size))

    combined = MOTION_WEIGHT * mo + (1 - MOTION_WEIGHT) * au
    combined = smooth(combined, 3)

    start = best_window(combined, GRID, window)
    end = min(dur, start + window)
    peak_i = int(np.argmax(combined))
    audio_peak_i = int(np.argmax(au)) if au.size else 0

    return {
        "file": str(path),
        "name": Path(path).stem,
        "duration": round(dur, 2),
        "peak_time": round(peak_i * GRID, 2),
        "peak_score": round(float(combined[peak_i]), 3),
        "audio_peak_time": round(audio_peak_i * GRID, 2),
        "motion_mean": round(float(mo.mean()), 3),
        "audio_mean": round(float(au.mean()), 3),
        "action_share": round(float((combined > 0.55).mean()), 3),
        "suggested_in": round(start, 2),
        "suggested_out": round(end, 2),
        "combined": combined,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--window", type=float, default=2.5)
    ap.add_argument("--json", default=None)
    ap.add_argument("--top", type=int, default=0)
    args = ap.parse_args()

    ffmpeg = find_ffmpeg()
    results = []
    for c in args.clips:
        r = analyse(ffmpeg, c, args.window)
        if r:
            results.append(r)

    results.sort(key=lambda r: r["peak_score"], reverse=True)
    ranked = results[:args.top] if args.top else results

    print(f"{'#':>2}  {'clip':46} {'dur':>5} {'score':>6} {'peak@':>6} "
          f"{'motion':>6} {'audio':>6} {'action':>6}  suggested")
    print("-" * 118)
    for i, r in enumerate(ranked, 1):
        print(f"{i:>2}  {r['name'][:46]:46} {r['duration']:>5.1f} {r['peak_score']:>6.2f} "
              f"{r['peak_time']:>6.1f} {r['motion_mean']:>6.2f} {r['audio_mean']:>6.2f} "
              f"{r['action_share']:>6.0%}  in {r['suggested_in']:.1f} out {r['suggested_out']:.1f}")

    if args.json:
        slim = [{k: v for k, v in r.items() if k != "combined"} for r in results]
        Path(args.json).write_text(json.dumps(slim, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
