# Clipping Agent

Turns a long-form video (podcast, stream, webinar, gameplay capture) into
captioned, 9:16 short-form clips.

**Nothing here publishes anything.** Every stage writes files to disk. Posting,
scheduling and campaign submission are deliberate human actions — see
[Human in the loop](#human-in-the-loop).

---

## What it actually does

```
source video ──▶ transcript ──▶ moments ──▶ 9:16 clips with burned-in captions
 (file or       (word-level    (start/end    (1080x1920, H.264, AAC)
  YouTube URL)   timestamps)    + framing)
```

The hard part is not the cutting. It is **framing**: a 9:16 crop of a 1920x1080
source keeps only **608 of 1920 pixels** (31%), which is narrower than any
two-person shot. A naive centre crop renders perfectly happily and quietly cuts
the speaker in half. See [Framing](#framing-how-169-becomes-916).

---

## The pipeline

| # | Stage | Script | What it does | Needs a key? |
|---|---|---|---|---|
| 0 | Scout | `scout_campaigns.py` | Reads the public Content Rewards board, ranks live campaigns by *how many views you need before you earn anything* | no — public API |
| 1 | Transcribe | `transcribe.py` | Word-level timestamps via mlx-whisper (Apple Silicon GPU) or faster-whisper (CPU) | no — runs locally |
| 2 | Select moments | `select_clips.py` | Sends the transcript to Claude, gets back candidate clips | **yes — `ANTHROPIC_API_KEY`** |
| 2b | Score moments | `pick_moments.py` | Objective scoring for material with **no speech** — audio energy (RMS envelope) weighted against visual motion (mean absolute frame difference) | no |
| 3 | Render | `render.py` | Cuts, reframes to 9:16, burns in word-highlighted captions | no |
| 4 | Assemble | `assemble.py` | Stitches several short sources into one edit from an EDL, adds on-screen text and a music bed | no |
| 4b | Sound effects | `fetch_sfx.py` + `sfx.py` | Royalty-free SFX pack, and the cue layer that places effects on the assembled timeline | no |

`main.py` orchestrates **stages 1→2→3** only. Stages 0, 2b and 4 are run
directly. Helper scripts (`find_phrase.py`, `make_review.py`) sit alongside them.

### Stage 1 — transcribe

```bash
python3 transcribe.py <input_media> <out.json> [model_size] [language]
```

Two backends, chosen automatically: **mlx-whisper** on Apple Silicon (GPU, much
faster) and **faster-whisper** (CPU int8) everywhere else. The output JSON is
byte-identical in shape, so no downstream stage knows or cares which ran.

**Always pin the language if you know it.** Whisper's auto-detect drifts across
closely-related languages — Serbian / Croatian / Bosnian, Danish / Norwegian —
and a wrong guess poisons every stage after it:

```bash
python3 transcribe.py input/ep4.mp4 transcripts/ep4.json large-v3 sr
```

Model size matters more than the docs usually admit: `small` is too weak for
lower-resource languages like Serbian. `large-v3` is the safe choice.

### Stage 2 — picking moments, two honest paths

`select_clips.py` is the automated path: it sends the transcript to Claude and
writes a candidates JSON. **It needs `ANTHROPIC_API_KEY`.**

When that key isn't set — or when the material needs a judgement call — the
agent reads the transcript directly and hand-authors the candidates file. This
is not a downgrade: for a podcast, reading the transcript and choosing the six
moments with the strongest hook *is* the job, and a human-in-the-loop pass on
the boundary timestamps produces better cuts than an API round-trip.

Use `find_phrase.py` to get exact boundaries instead of eyeballing a coarse
transcript, which lands cuts mid-word:

```bash
python3 find_phrase.py transcripts/ep4.json "TikTok je učinio svoje" "seci ovo"
```

It prints the segment containing each phrase plus its neighbours, so you can set
in/out points on real timestamps.

### When to use `assemble.py` instead of `render.py`

- **`render.py`** — talking-head material (podcasts, streams, interviews): one
  long source, spoken content, transcript-driven selection.
- **`assemble.py`** — gameplay or brand-asset material: many *short* sources
  (3–10s), often no speech at all, and a brief demanding a minimum length plus
  mandatory on-screen text. `select_clips.py` is useless here — there is no
  transcript to reason over, so selection has to be visual.

---

## Framing: how 16:9 becomes 9:16

### The arithmetic that decides everything

A 9:16 crop of a 1920x1080 source keeps **608 of 1920 pixels**. That is
narrower than any two-shot. On a real podcast job the two faces sat **~670px
apart** — so no crop can hold both, and the only question is *which* 608 you
take.

### Layouts

| Layout | What it does | Use for |
|---|---|---|
| `pad` *(default)* | Whole 16:9 frame scaled to width, centred on a blurred, zoomed copy of itself. Nothing is cropped. | Wide shots, multi-person frames, screen shares, game UI |
| `crop` | Scales to fill and cuts the sides — **centred** by default | A single centred speaker |
| `crop` + `focus` | Same, but the window **slides onto a chosen subject** | Any multi-person shot |

### `focus` — the off-centre crop

`focus_x` is where the subject sits in the **source** frame, as a fraction of
width: `0` = hard left, `0.5` = centre, `1` = hard right.

```bash
# slide the crop onto a subject instead of centring it
python3 render.py src.mp4 transcript.json candidates.json out/ --layout crop --focus-x 0.29
```

Better: set it **per clip** in the candidates JSON, which overrides the flag —
the right value differs from clip to clip.

```json
{
  "clips": [
    { "title": "ship-life", "start": 982.4, "end": 1011.0, "focus_x": 0.37 },
    { "title": "15-loyal-people", "start": 658.5, "end": 675.6, "focus_x": 0.26 }
  ]
}
```

For a subject who moves, pass keyframes instead of a number and the crop pans
between them:

```json
"focus": [{"t": 0, "x": 0.29}, {"t": 12, "x": 0.71}]
```

### Measuring the number

**Do not eyeball it.** Draw a ruler on the frame and read the position off the
picture — `drawgrid` at 192px on a 1920px frame is one line per 0.1 of width:

```bash
ffmpeg -ss 982 -i source.mp4 -frames:v 1 \
  -vf "drawgrid=w=192:h=1080:t=2:c=red@0.85,scale=1200:-2" grid.png
```

Then **prove it** — render the same seconds at two or three candidate values and
look at the result side by side. A value that "should" work is not the same as a
value you have seen work.

### Classify the camera before choosing a moment

Productions cut unpredictably, so a moment picked from the transcript is not
automatically crop-friendly. Check the frame at the exact moment before
committing — speech-driven selection lands on whatever camera happened to be
live:

| Class | Content | Crop to 9:16? |
|---|---|---|
| A | two-shot, two men | yes — pick a focus |
| B | two-shot, man + woman | yes — pick a focus |
| C | overhead shot of cards on a table | poor — a narrow slice of table |
| D | full-screen game board / UI | poor — and it may carry a webcam strip along the top |

### Vertical framing cannot clip anyone

The crop is 1080x1920 taken from a frame scaled to 3413x1920 — full height.
Nothing can be cut off vertically. A head that looks "cropped at the top" is
genuinely above the camera's field of view in the source, not a crop bug.

---

## Captions

- Short chunks (≤3 words, ≤22 chars) grouped on **pauses**, so a caption never
  straddles a silence and drifts out of sync.
- The **active word is highlighted gold**, the rest stay white — one subtitle
  event per word, so the highlight tracks speech.
- Captions sit clear of the bottom edge, out of the way of the TikTok/Reels UI.
- **Timing is normalised.** Whisper word timings jitter *backwards*, which
  stacks two captions on the same frames and makes them flicker. A post-pass
  walks the events in time order and forces each to begin after the previous
  ended. Do not remove it — verified 0 overlapping events.
- `WrapStyle: 0` (smart wrap) in **both** `render.py` and `assemble.py`.
  `WrapStyle: 2` disables wrapping *entirely*, so an over-wide chunk runs off
  the frame edge and gets clipped instead of breaking onto a second line.
- **Check your font can draw your language.** A font missing `č ć ž š đ` renders
  empty boxes, and it fails silently. Arial Black on macOS is verified fine —
  burn a test `.ass` onto black and read the glyphs back before trusting it.

---

## Human in the loop

By design, and non-negotiable:

- **Credentials belong to the human.** The agent never types a login, and never
  clicks through a sign-in or a "link your social accounts" screen.
- **Nothing is published.** No auto-posting to TikTok / Reels / Shorts / YouTube.
  Platform APIs also make this a bad idea: unaudited TikTok clients can only
  post `SELF_ONLY`, YouTube uploads from an unverified project land private, and
  IG Reels needs a Business account plus a linked Facebook Page.
- **Rendered clips are handed over as files**, plus a `review.html` built by
  `make_review.py` so a human can actually look at them. Clips that exist only
  in `output/` are, to the person asking, clips that do not exist.
- **Royalties matter more than the pipeline.** Only clip footage you own or have
  been given permission to use. A paid campaign grants that permission through
  its brief; "it was on YouTube" does not.

---

## Setup

```bash
# 1. Python env (uv is fastest; a plain venv works too)
uv venv .venv --python 3.11
.venv/bin/python -m pip install -r requirements.txt

# 2. Only needed for the automated stage-2 path
export ANTHROPIC_API_KEY=sk-ant-...
```

### ffmpeg — this one will bite you

You need an ffmpeg built **with libass**. Homebrew's *plain* `ffmpeg` formula
ships with **no libass, freetype or drawtext filters at all**, so caption
burn-in is impossible and ffmpeg fails with an opaque filter error.

```bash
brew install ffmpeg-full        # keg-only, lands at /opt/homebrew/opt/ffmpeg-full
```

`render.py` probes every ffmpeg it can find for the `ass` filter and picks the
first that has it. If none works it names the paths it checked and what to
install, instead of failing inside ffmpeg.

### `uv` on PATH in non-interactive shells

Background/automation shells do **not** inherit `~/.hermes/bin`, so a bare `uv`
can fail with `command not found` and abort an install script silently. Either
call it by absolute path or export PATH first:

```bash
export PATH="$HOME/.hermes/bin:/opt/homebrew/bin:$PATH"
```

---

## Usage

```bash
# Full pipeline on a local file or a YouTube URL (stages 1-3)
python3 main.py input/your_video.mp4
python3 main.py "https://youtube.com/watch?v=..." 5 small
#                                                  ^    ^
#                                            max_clips  whisper model

# Render a hand-written or LLM-written candidates file
python3 render.py <source_video> <transcript_json> <candidates_json> <out_dir> \
                  [--layout pad|crop] [--focus-x 0..1] [--font NAME] [--size N] [--no-captions]

# Multi-clip assembly from an edit decision list
python3 assemble.py edl.json

# Rank live campaigns before you commit to one
python3 scout_campaigns.py --gaming --min-platforms 3 --has-assets --fresh-only

# Build a review page for a folder of finished clips
python3 make_review.py output/<name> --title "Episode 4"
```

The `assemble.py` EDL is plain JSON:

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
  ],
  "sfx": [
    { "role": "impact", "at": 0.05, "gain": -4 },
    { "role": "whoosh", "at": 1.45, "gain": -7 }
  ]
}
```

Overlay styles: `title` (top, largest), `sub` (top, gold, beneath the title),
`cta` (bottom, inside the safe zone), `hook` (top, pop-in scale then fade).
Segment times are absolute seconds into each source file; overlay **and SFX**
times are relative to the assembled timeline. Source audio is kept at
`game_audio_volume` and mixed under the music bed.

---

## Sound effects

`sfx` is optional and additive — an EDL without it renders exactly as it did
before the feature existed (verified below).

```bash
python3 fetch_sfx.py sync         # download the pack into assets/sfx/
python3 sfx.py list               # what's in it, by role
python3 sfx.py list whoosh
python3 sfx.py check edl.json output/x.mp4 --control output/x_nosfx.mp4
```

### The pack

Cues name a **role**, never a path:

| Role | Use for |
|---|---|
| `impact` | the opening beat, a cut onto a hit |
| `whoosh` | carrying a segment-to-segment transition |
| `fail` | comedic failure — a crash, a missed flip |
| `win` | payoff, achievement, a clean landing |

`assets/sfx/pack.json` is the curated list (edit this, not the wavs);
`fetch_sfx.py sync` downloads the audio and writes `manifest.json` with real
per-file metadata — duration, channels, bit depth, size and sha256. `sfx.py`
resolves roles against that manifest, so re-curating the pack never touches an
EDL. `python3 fetch_sfx.py verify` re-checks the pack against its hashes.

Audio comes from **Mixkit** (<https://mixkit.co/free-sound-effects/>), under the
Mixkit Free Sound Effects License: royalty-free, no attribution required,
commercial use permitted. Mixkit serves each effect as a full-quality 24-bit WAV
at a guessable URL, so the fetcher takes `…/sfx/<id>/<id>.wav` — **not** the
`-preview.mp3` in the page markup, which is the browser player's downgrade.
Confirm the licence at <https://mixkit.co/license/> before shipping a paid job;
it is permissive but not ours to guarantee.

### Cue shape

```json
{ "role": "whoosh", "at": 3.4 }
{ "role": "impact", "at": 0.05, "gain": -3 }
{ "role": "impact", "at": 8.1, "pick": 2 }
{ "file": "assets/sfx/472-slow-sad-trombone-fail.wav",
  "at": 4.0, "gain": -4, "trim": 0.1, "duration": 2.5, "fade_out": 0.3 }
```

`at` is required. `gain` is dB (default **-6**; -12…-4 is the working range,
louder only for the opening hit). `trim` starts partway into the file,
`duration` caps how much is used, `fade_out` tapers the tail so a sting does not
end abruptly under a voice-over. `pick` chooses a specific file from a role.

**Repeated roles rotate.** Four `whoosh` cues pull four *different* whooshes,
cycling the pack in manifest order — deterministic, so a re-render is
byte-comparable rather than "sounds different today".

### Why the mix looks the way it does

Cues are **summed into** the bed, not mixed *with* it:

```
[bed] ─┐
       ├─ amix(normalize=0, duration=first) ─ afade ─ alimiter ─ [aout]
[sfxall] ─┘
```

`amix` normalises by default — it divides by the input count — so folding
effects into the existing two-input music mix would quietly duck the music by a
further 1/N for every cue added, and a four-cue edit would sound measurably
thinner than a one-cue edit for no musical reason. `normalize=0` keeps the bed
where it was. The cost is that summing can exceed full scale, so a lookahead
`alimiter` sits on the output. The fade moved *after* the effects for the same
reason: an impact on the last beat should still be an impact.

### Verifying a render

ffmpeg exiting 0 says nothing about whether a sound is audible. A cue with the
wrong gain, or an `at` that drifted, still renders a perfectly valid file.

`sfx.py check` measures it. Given the same EDL rendered twice — once with its
`sfx` block, once without (`--control`) — it subtracts the two decoded signals
and reports what each cue actually contributed:

```
[check] test_sfx.mp4  18.48s  7 cue(s)
[check] baseline -36.9 dBFS — residual vs test_control.mp4
[check]   # role                           at    peak   added  verdict
[check]   1 quick-zoom-impact            0.05  +0.51s  +24.1dB  OK
[check]   2 fast-whoosh-transition       1.45  +0.71s  +14.8dB  OK
[check]   3 cinematic-whoosh-fast-tran   3.45  +1.07s  +14.9dB  OK
[check]   7 swirling-whoosh             14.45  +1.96s  +15.2dB  OK
[check] every cue measurably landed
```

The `peak` column is where the cue's loudest moment landed relative to `at`.
For a swell that is legitimately late (a whoosh peaks near its end); a peak
*outside* the cue is flagged as a timing bug. The four whooshes above carry the
same -7 dB gain and measure 14.8–15.2 dB, i.e. within 0.4 dB of each other —
which is what a correct gain calculation looks like.

Without `--control` the baseline is the clip-wide median, which is only good
enough to catch a cue that is missing entirely.

---

## Output

`output/<video_name>/` — one `.mp4` per clip, the `.ass` subtitle file that
produced its captions, and a `review.html` if `make_review.py` has been run.

---

## Repo layout

```
scout_campaigns.py  # stage 0 — rank live campaigns by the view gate
transcribe.py       # stage 1 — mlx-whisper / faster-whisper, word timestamps
select_clips.py     # stage 2 — Claude picks candidates (needs ANTHROPIC_API_KEY)
pick_moments.py     # stage 2b — objective scoring for speechless material
render.py           # stage 3 — single-source reframe + focus crop + captions
assemble.py         # stage 4 — multi-clip edit from an EDL + on-screen text
fetch_sfx.py        # stage 4b — download / verify the royalty-free SFX pack
sfx.py              # stage 4b — SFX cue layer + "did the cues land?" checker
main.py             # orchestrator (stages 1-3)
find_phrase.py      # helper — exact timestamp of a phrase, for clean cuts
make_review.py      # helper — review.html for a folder of clips
assets/sfx/         # curated SFX pack (committed — fixed inputs, not per-run output)
docs/               # operational notes and campaign research
input/              # source videos (gitignored)
transcripts/        # whisper output JSON (gitignored)
clips/              # clip-candidate JSON (gitignored)
output/             # rendered clips (gitignored)
```

---

## Known limitations

- **No active-speaker tracking.** `focus` is set per clip, by hand, from a frame
  you have looked at. It does not follow a conversation automatically — if two
  people trade lines, switch that clip to `pad`.
- **No audio-based moment detection** (laughter, energy spikes) in
  `render.py` — clip selection is transcript-driven. `pick_moments.py` covers
  speechless material, but the two are not yet combined into one selector.
- **Clip boundaries are only as good as the transcript.** ASR errors land in the
  captions. Serbian in particular comes back with real misses (`SVEĆAM` for
  `SEĆAM`, `SECI` for `SEĆI`). Read the rendered captions before shipping, and
  prefer a correction pass over silently trusting the transcript.
- **No auto-posting**, by design — see [Human in the loop](#human-in-the-loop).

## Pitfalls worth knowing

- **Whisper word timings jitter backwards.** Captions stack on the same frames
  and flicker unless normalised. Both `render.py` and `assemble.py` handle it.
- **Filtergraph chains must be joined with `;`.** Concatenating them with an
  empty string makes ffmpeg read the next input pad as a second input to the
  previous filter, and it fails with a bare `Invalid argument`.
- **ffmpeg expressions inside filter args need their commas escaped.** A
  `max(0,min(...))` in a `crop` x-position will otherwise be read as two
  arguments. `_focus_expr` escapes them.
- **`ass=` needs a path that doesn't require escaping.** Write the `.ass` into a
  scratch directory and run ffmpeg with that as its cwd.
- **`WrapStyle: 2` disables word wrapping — long text gets CLIPPED, not
  wrapped.** Short labels fit, so it hides until someone adds a long one. Both
  renderers now use `WrapStyle: 0`. Check every new string at the frame edges.
- **Heavy CPU work starves GPU transcription.** Rendering while mlx-whisper runs
  dropped it from ~250 to ~77 mel-frames/s. Transcribe first, render after.
- **`amix` normalises by default.** It divides by the input count, so every
  effect folded into the music mix would duck the music further — eight cues and
  the bed is 9× quieter for no musical reason. Pass `normalize=0` and put a
  limiter on the output instead. `assemble.py` does both, but only when a cue
  exists, so a no-SFX EDL is bit-identical to before the feature.
- **Python's `wave` module cannot read WAVE_FORMAT_EXTENSIBLE (0xFFFE).** Mixkit
  ships its 24-bit files that way, and `wave.open` fails with
  `unknown format: 65534` — which reads exactly like a corrupt download and
  isn't. `fetch_sfx.py` walks the RIFF chunks itself. Don't "fix" it by
  re-downloading.
- **A whoosh is a swell, so its first 400 ms are nearly silent.** Verifying a
  cue by measuring the window at its start reports a perfectly good whoosh as
  missing. Measure the cue's whole length — or subtract a no-SFX control render
  and measure the residual, which is what `sfx.py check --control` does.
- **Mixkit's `-preview.mp3` is not the asset.** The page markup is full of them
  and they are the browser player's downgrade. The real file is
  `https://assets.mixkit.co/active_storage/sfx/<id>/<id>.wav`, 24-bit, no auth.
- **`adelay` needs `all=1` for stereo.** Without it the delay is applied to one
  channel only and the cue arrives half-channeled — which sounds like a phase
  problem, not a timing one, so it sends you looking in the wrong place.
- **A campaign may pay nothing below a minimum-payout threshold.** Read
  `minPayoutCents`, not just the headline CPM — see
  `docs/whop-content-rewards.md`.
- **Rank campaigns by the view gate, not the CPM.** `minPayout ÷ rate × 1000` is
  the views one clip needs before it earns a cent. A high CPM with a high gate
  pays worse than a lower CPM you can actually clear. The *cap* matters too: it
  decides the views at which a hit stops earning.
