# Clipping Agent

Turns a long-form video (podcast, stream, webinar) into captioned, 9:16
short-form clips — automatically.

## Pipeline

1. **Transcribe** (`transcribe.py`) — word-level timestamps.
   Uses **mlx-whisper** on Apple Silicon (GPU, much faster) and falls back to
   **faster-whisper** (CPU int8) everywhere else. The output JSON is identical
   either way, so no downstream stage needs to care which ran.
2. **Select clips** (`select_clips.py`) — sends the transcript to Claude, gets
   back candidate clips with start/end timestamps, a title, a hook, and a
   confidence score.
3. **Render** (`render.py`) — cuts each candidate, reframes to 9:16, and burns
   in word-chunked captions with the spoken word highlighted, via ffmpeg + libass.

`main.py` orchestrates all three. Accepts a local file or a YouTube URL
(downloaded via `yt-dlp`).

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

### ffmpeg — this one will bite you

You need an ffmpeg built **with libass**. Homebrew's *plain* `ffmpeg` formula
ships with **no libass, freetype or drawtext filters at all**, so caption
burn-in is impossible with it and ffmpeg fails with an opaque filter error.

```bash
brew install ffmpeg-full        # keg-only, lands at /opt/homebrew/opt/ffmpeg-full
```

`render.py` probes every ffmpeg it can find for the `ass` filter and picks the
first one that has it, so the full build is found automatically. If none works
it tells you which paths it checked and what to install, instead of failing
inside ffmpeg.

## Usage

```bash
python3 main.py input/your_video.mp4
python3 main.py "https://youtube.com/watch?v=..." 5 small
#                                                  ^    ^
#                                            max_clips  whisper model size
```

Render a single set of candidates directly:

```bash
python3 render.py <source_video> <transcript_json> <candidates_json> <out_dir> \
                  [--layout pad|crop] [--no-captions]
```

### Layouts

| Layout | What it does | Use for |
|---|---|---|
| `pad` *(default)* | Whole 16:9 frame scaled to width, centred on a blurred, zoomed copy of itself. Nothing is cropped. | Wide shots, multi-person frames, screen shares |
| `crop` | Scales to fill the frame and cuts the sides. | A single centred speaker |

`crop` was the only option before, and it cuts people off in wide or
multi-person shots. `pad` is now the default because it never loses anyone.

## Output

`output/<video_name>/`, one `.mp4` per clip plus the `.ass` subtitle file that
produced its captions.

## Captions

- Short chunks (≤3 words, ≤22 chars) grouped on **pauses**, so a caption never
  straddles a silence and drifts out of sync.
- The **active word is highlighted gold**, the rest stay white — one subtitle
  event per word, so the highlight tracks speech.
- Captions sit **380px clear of the bottom** edge, out of the way of the
  TikTok/Reels UI and their caption overlay.
- **Timing is normalised.** Whisper word timings jitter *backwards*, which
  stacks two captions on the same frames and makes them flicker. A post-pass
  walks the events in time order and forces each to begin after the previous
  ended. Do not remove it — verified 0 overlapping events.

## Known limitations

- `crop` is still a dumb centre-crop — no active-speaker tracking. Use `pad`
  when the frame has more than one person in it.
- No audio-based moment detection (laughter, energy spikes) — clip selection is
  purely transcript-driven. **This is wrong for gameplay footage**, where the
  payoff is visual rather than spoken; gaming clips need audio-energy and
  scene-change signals, not just speech.
- Clip boundaries are only as good as the LLM's segment alignment; not
  frame-perfect.
- No auto-posting — clips are rendered to disk, not published anywhere.

## Repo layout

```
transcribe.py       # stage 1 — mlx-whisper / faster-whisper
select_clips.py     # stage 2 — Claude picks candidates
render.py           # stage 3 — reframe + burn captions
main.py             # orchestrator
docs/               # operational notes and campaign research
input/              # source videos (gitignored)
transcripts/        # whisper output JSON (gitignored)
clips/              # LLM clip-candidate JSON (gitignored)
output/             # rendered clips (gitignored)
```
