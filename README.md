# Clipping Agent (v0)

Turns a long-form video (podcast, stream, webinar) into captioned, 9:16
short-form clips — automatically.

## Pipeline

1. **Transcribe** (`transcribe.py`) — `faster-whisper`, word-level timestamps.
2. **Select clips** (`select_clips.py`) — sends the transcript to Claude, gets
   back candidate clips with start/end timestamps, a title, a hook, and a
   confidence score.
3. **Render** (`render.py`) — cuts each candidate, crops/scales to 9:16,
   burns in punchy word-chunked captions via ffmpeg + libass.

`main.py` orchestrates all three. Accepts a local file or a YouTube URL
(downloaded via `yt-dlp`).

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

Requires `ffmpeg` on PATH.

## Usage

```bash
python3 main.py input/your_video.mp4
python3 main.py "https://youtube.com/watch?v=..." 5 small
#                                                  ^    ^
#                                            max_clips  whisper model size
```

Output lands in `output/<video_name>/`, one `.mp4` per clip plus its `.ass`
subtitle file.

## Known v0 limitations

- Crop is a dumb center-crop (scale to fill height, crop width) — works for
  a single static speaker in a 16:9 frame, will cut people off in
  multi-person or wide shots. Active-speaker tracking is the natural v1
  upgrade.
- No audio-based moment detection (laughter, energy spikes) — clip
  selection is purely transcript-driven.
- Clip boundaries are only as good as the LLM's segment alignment; not
  frame-perfect.
- No auto-posting yet — clips are rendered to disk, not published anywhere.

## Repo layout

```
transcribe.py      # stage 1
select_clips.py     # stage 2
render.py           # stage 3
main.py              # orchestrator
input/               # source videos (gitignored)
transcripts/          # whisper output JSON (gitignored)
clips/                 # LLM clip-candidate JSON (gitignored)
output/                 # rendered clips (gitignored)
```
