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
4. **Assemble** (`assemble.py`) — for campaigns whose assets are too short to
   reach the brief's minimum length, stitches several source clips into one
   edit from a JSON edit decision list, adds required on-screen text, and lays
   a cleared music bed under the source audio.

`main.py` orchestrates stages 1-3. Accepts a local file or a YouTube URL
(downloaded via `yt-dlp`).

### When to use `assemble.py` instead of `render.py`

Use `render.py` for **talking-head material** (podcasts, streams, interviews):
long sources, spoken content, and clip selection driven by a transcript.

Use `assemble.py` for **gameplay or brand-asset material**: short source clips
(3-10s), no speech at all, and a brief that demands a minimum clip length plus
mandatory on-screen text. `select_clips.py` is useless here — there is no
transcript to reason over. Selection has to be visual.

```bash
python3 assemble.py edl.json
```

The EDL is plain JSON:

```json
{
  "out": "output/brand/01_hook.mp4",
  "layout": "crop",
  "music": "input/brand/cleared_music.wav",
  "game_audio_volume": 0.32,
  "segments": [
    { "file": "input/brand/clip_a.mp4", "start": 0.4, "end": 1.9 },
    { "file": "input/brand/clip_b.mp4", "start": 0.6, "end": 2.6 }
  ],
  "overlays": [
    { "text": "GAME NAME",         "start": 0.2, "end": 12.0, "style": "title" },
    { "text": "EARLY ACCESS",      "start": 0.2, "end": 12.0, "style": "sub" },
    { "text": "WISHLIST ON STEAM", "start": 1.2, "end": 12.0, "style": "cta" }
  ]
}
```

Overlay styles: `title` (top, largest), `sub` (top, gold, beneath the title),
`cta` (bottom, inside the safe zone). Segment times are absolute seconds into
each source file; overlay times are relative to the assembled timeline. Source
audio is kept at `game_audio_volume` and mixed under the music bed.

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
select_clips.py     # stage 2 — Claude picks candidates (talking-head only)
render.py           # stage 3 — single-source reframe + burn captions
assemble.py         # stage 4 — multi-clip edit from an EDL + on-screen text
main.py             # orchestrator (stages 1-3)
docs/               # operational notes and campaign research
input/              # source videos (gitignored)
transcripts/        # whisper output JSON (gitignored)
clips/              # LLM clip-candidate JSON (gitignored)
output/             # rendered clips (gitignored)
```

## Pitfalls worth knowing

- **Whisper word timings jitter backwards.** Captions stack on the same frames
  and flicker unless normalised. Both `render.py` and `assemble.py` handle it.
- **Filtergraph chains must be joined with `;`.** Concatenating them with an
  empty string makes ffmpeg read the next input pad as a second input to the
  previous filter, and it fails with a bare `Invalid argument`.
- **`ass=` needs a path that doesn't require escaping.** Write the `.ass` into a
  scratch directory and run ffmpeg with that as its cwd.
- **A campaign may pay nothing below a minimum-payout threshold.** Read
  `minPayoutCents`, not just the headline CPM — see `docs/whop-content-rewards.md`.
