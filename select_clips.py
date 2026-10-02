#!/usr/bin/env python3
"""
Stage 2: Ask Claude to pick the best short-form clip candidates from a transcript.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 select_clips.py transcripts/video.json clips/candidates.json
"""
import sys
import json
import os
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-5"  # swap for whichever Claude model you have access to

SYSTEM_PROMPT = """You are a short-form video editor. You're given a timestamped \
transcript of a long-form video (podcast, stream, webinar, etc). Your job is to \
find the segments with the highest potential to work as standalone short-form \
clips (TikTok / Reels / Shorts).

A good clip:
- Is self-contained: makes sense without the surrounding context
- Has a strong hook in the first 1-3 seconds (a bold claim, a question, a surprising fact)
- Is 20-90 seconds long
- Has a clear payoff, punchline, or insight, not just rambling
- Does NOT cut off mid-sentence at either end

Return ONLY valid JSON, no prose, in this exact shape:
{
  "clips": [
    {
      "start": <seconds, float>,
      "end": <seconds, float>,
      "title": "<short catchy title for the clip, max 8 words>",
      "hook": "<the exact line or moment that hooks viewers>",
      "reason": "<one sentence on why this will perform>",
      "score": <1-10 integer, your confidence this clips well>
    }
  ]
}
"""


def select_clips(transcript_path: str, output_path: str, max_clips: int = 5):
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    # Build a compact timestamped transcript the model can reason over.
    lines = []
    for seg in transcript["segments"]:
        lines.append(f"[{seg['start']:.1f}-{seg['end']:.1f}] {seg['text']}")
    transcript_text = "\n".join(lines)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    print(f"[select_clips] asking Claude for up to {max_clips} candidate clips...")
    message = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Here is the timestamped transcript (duration: "
                f"{transcript['duration']:.0f}s). Pick up to {max_clips} of the "
                f"strongest clip candidates.\n\n{transcript_text}"
            ),
        }],
    )

    raw = message.content[0].text.strip()
    # Models sometimes wrap JSON in ```json fences despite instructions; strip them.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = json.loads(raw)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    for c in data["clips"]:
        print(f"  [{c['start']:7.1f}-{c['end']:7.1f}] ({c['score']}/10) {c['title']}")

    print(f"[select_clips] wrote {output_path} ({len(data['clips'])} candidates)")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python3 select_clips.py <transcript_json> <output_json> [max_clips]")
        sys.exit(1)
    max_clips = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    select_clips(sys.argv[1], sys.argv[2], max_clips)
