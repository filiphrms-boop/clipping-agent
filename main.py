#!/usr/bin/env python3
"""
v0 clipping agent orchestrator.

Takes a local video file OR a YouTube URL, transcribes it, asks Claude to pick
the best short-form clip candidates, then renders each as a captioned 9:16 clip.

Usage:
    python3 main.py input/video.mp4
    python3 main.py "https://youtube.com/watch?v=..."

Env:
    ANTHROPIC_API_KEY must be set for the clip-selection stage.
"""
import sys
import subprocess
from pathlib import Path

from transcribe import transcribe
from select_clips import select_clips
from render import main as render_all

BASE = Path(__file__).parent
INPUT_DIR = BASE / "input"
TRANSCRIPT_DIR = BASE / "transcripts"
CLIPS_DIR = BASE / "clips"
OUTPUT_DIR = BASE / "output"


def download_if_url(source: str) -> Path:
    if not source.startswith("http"):
        return Path(source)

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_template = str(INPUT_DIR / "%(id)s.%(ext)s")
    print(f"[main] downloading {source} ...")
    subprocess.run([
        "yt-dlp", "-f", "mp4/best",
        "-o", out_template,
        source,
    ], check=True)
    # Find the downloaded file (yt-dlp prints it, but re-globbing is simpler for v0)
    candidates = sorted(INPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise RuntimeError("yt-dlp finished but no .mp4 was found in input/")
    return candidates[-1]


def run(source: str, max_clips: int = 5, whisper_model: str = "small"):
    video_path = download_if_url(source)
    stem = video_path.stem

    transcript_path = TRANSCRIPT_DIR / f"{stem}.json"
    candidates_path = CLIPS_DIR / f"{stem}_candidates.json"
    out_dir = OUTPUT_DIR / stem

    print("=" * 60)
    print(f"STAGE 1/3: transcribing {video_path.name}")
    print("=" * 60)
    transcript = transcribe(str(video_path), str(transcript_path), whisper_model)

    print("=" * 60)
    print("STAGE 2/3: selecting clip candidates")
    print("=" * 60)
    select_clips(str(transcript_path), str(candidates_path), max_clips)

    print("=" * 60)
    print("STAGE 3/3: rendering clips")
    print("=" * 60)
    outputs = render_all(str(video_path), str(transcript_path), str(candidates_path), str(out_dir))

    print("=" * 60)
    print(f"DONE — {len(outputs)} clips ready in {out_dir}")
    print("=" * 60)
    for o in outputs:
        print(f"  {o}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 main.py <video_file_or_youtube_url> [max_clips] [whisper_model]")
        sys.exit(1)
    max_clips = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    whisper_model = sys.argv[3] if len(sys.argv) > 3 else "small"
    run(sys.argv[1], max_clips, whisper_model)
