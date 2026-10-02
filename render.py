#!/usr/bin/env python3
"""
Stage 3: Cut a clip from the source video, crop to 9:16, and burn in captions.

Usage:
    python3 render.py input/video.mp4 transcripts/video.json clips/candidates.json output/
"""
import sys
import json
import subprocess
from pathlib import Path


def words_in_range(transcript: dict, start: float, end: float):
    words = []
    for seg in transcript["segments"]:
        for w in seg.get("words", []):
            if w["start"] >= start and w["end"] <= end:
                words.append(w)
    return words


def chunk_words(words, max_words_per_caption=4):
    """Group words into short caption chunks for punchy on-screen text."""
    chunks = []
    for i in range(0, len(words), max_words_per_caption):
        group = words[i:i + max_words_per_caption]
        if not group:
            continue
        chunks.append({
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": "".join(w["word"] for w in group).strip().upper(),
        })
    return chunks


def ass_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int(round((s - int(s)) * 100))
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def write_ass(chunks, clip_start, clip_end, out_path):
    """Write an .ass subtitle file with timestamps relative to the clip start."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,78,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,6,0,2,60,60,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for c in chunks:
        rel_start = max(0.0, c["start"] - clip_start)
        rel_end = max(rel_start + 0.1, c["end"] - clip_start)
        if rel_start >= (clip_end - clip_start):
            continue
        text = c["text"].replace("\n", " ")
        lines.append(
            f"Dialogue: 0,{ass_timestamp(rel_start)},{ass_timestamp(rel_end)},"
            f"Caption,,0,0,0,,{text}\n"
        )
    Path(out_path).write_text("".join(lines), encoding="utf-8")


def render_clip(source_video, transcript, clip, out_dir, index):
    start, end = clip["start"], clip["end"]
    slug = "".join(c if c.isalnum() else "_" for c in clip["title"]).strip("_")[:40]
    base = f"{index:02d}_{slug}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_cut = out_dir / f"{base}_raw.mp4"
    ass_path = out_dir / f"{base}.ass"
    final_out = out_dir / f"{base}.mp4"

    # 1. Cut the segment (re-encode so the cut is frame-accurate).
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(start), "-to", str(end),
        "-i", str(source_video),
        "-c:v", "libx264", "-c:a", "aac",
        "-preset", "veryfast",
        str(raw_cut),
    ], check=True, capture_output=True)

    # 2. Build captions for this clip's time range.
    words = words_in_range(transcript, start, end)
    chunks = chunk_words(words)
    write_ass(chunks, start, end, ass_path)

    # 3. Crop/scale to 9:16 (1080x1920) and burn in captions.
    # Scale to fill height, center-crop width — works for 16:9 source.
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"ass={ass_path}"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(raw_cut),
        "-vf", vf,
        "-c:v", "libx264", "-c:a", "aac",
        "-preset", "veryfast", "-crf", "20",
        str(final_out),
    ], check=True, capture_output=True)

    raw_cut.unlink(missing_ok=True)
    print(f"[render] wrote {final_out}")
    return final_out


def main(source_video, transcript_path, candidates_path, out_dir):
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)
    with open(candidates_path, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    outputs = []
    for i, clip in enumerate(candidates["clips"], start=1):
        print(f"[render] clip {i}: {clip['title']} ({clip['start']:.1f}-{clip['end']:.1f})")
        outputs.append(render_clip(source_video, transcript, clip, out_dir, i))

    print(f"[render] done — {len(outputs)} clips in {out_dir}")
    return outputs


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("usage: python3 render.py <source_video> <transcript_json> <candidates_json> <out_dir>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
