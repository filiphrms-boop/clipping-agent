#!/usr/bin/env python3
"""
Stage 1: Transcribe a video/audio file into word-level timestamped JSON.

Usage:
    python3 transcribe.py input/video.mp4 transcripts/video.json
"""
import sys
import json
from pathlib import Path

from faster_whisper import WhisperModel


def transcribe(input_path: str, output_path: str, model_size: str = "small"):
    print(f"[transcribe] loading whisper model '{model_size}'...")
    # CPU-friendly settings; switch to device="cuda" if a GPU is available.
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    print(f"[transcribe] transcribing {input_path} ...")
    segments, info = model.transcribe(
        input_path,
        word_timestamps=True,
        vad_filter=True,  # strips silence, keeps timestamps tight
    )

    result = {
        "language": info.language,
        "duration": info.duration,
        "segments": [],
    }

    full_text_parts = []
    for seg in segments:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word,
                    "start": round(w.start, 2),
                    "end": round(w.end, 2),
                })
        result["segments"].append({
            "id": seg.id,
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": words,
        })
        full_text_parts.append(seg.text.strip())
        print(f"  [{seg.start:7.2f}s -> {seg.end:7.2f}s] {seg.text.strip()}")

    result["text"] = " ".join(full_text_parts)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[transcribe] wrote {output_path} ({len(result['segments'])} segments)")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python3 transcribe.py <input_media> <output_json> [model_size]")
        sys.exit(1)
    model_size = sys.argv[3] if len(sys.argv) > 3 else "small"
    transcribe(sys.argv[1], sys.argv[2], model_size)
