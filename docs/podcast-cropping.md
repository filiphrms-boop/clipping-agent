# Cropping a landscape podcast to 9:16

Written after the *Sajd Kvest #4* job (2026-10-02): a 43-minute Serbian
board-game podcast, 1920x1080, four people on set. Recorded here because the
failure mode is silent — a bad crop still renders, it just looks wrong.

## The arithmetic that decides everything

A 9:16 crop of a 1920x1080 source keeps **608 of 1920 pixels** — 31% of the
width. That is narrower than any two-shot. On this source the two faces sat
**~670px apart**, so no crop can hold both. The only question is *which* 608
pixels you take.

Hence: centre-cropping a multi-person shot always lands between the faces and
slices both. It has to be an **off-centre focus crop**.

```bash
# slide the crop onto a subject instead of centring it
render.py src.mp4 transcript.json candidates.json out/ --layout crop --focus-x 0.29
```

`--focus-x` is where the subject sits in the SOURCE frame as a fraction of
width (0 = hard left, 0.5 = centre, 1 = hard right). Or set `focus_x` per clip
in `candidates.json`, which overrides the flag — necessary, because the right
value differs clip to clip.

For a subject who moves, pass a keyframe list instead of a number; the crop
pans between them:

```json
"focus": [{"t": 0, "x": 0.29}, {"t": 12, "x": 0.71}]
```

## Measuring the number: put a grid on the frame

Do not eyeball it. Draw a ruler and read the position off the picture:

```bash
ffmpeg -ss 2200 -i source.mp4 -frames:v 1 \
  -vf "drawgrid=w=192:h=1080:t=2:c=red@0.85,scale=1200:-2" grid.png
```

`w=192` on a 1920px frame = one line per 0.1 of width, so a face reads
straight off as a fraction. Then **prove it** — render the same seconds at two
or three candidate values and look at the result side by side. Values in this
job (verified against rendered frames, not assumed):

| camera | subject | focus_x |
|---|---|---|
| A — two men, dark tees | left man (curly hair) | 0.29 |
| A — two men, dark tees | right man (spiky hair, tattooed arm) | 0.71 |
| B — man in green + woman | man in green | 0.33 |
| B — man in green + woman | woman | 0.68 |

A 1.5x spread between the two faces is the tell that a centred crop cannot
work.

## Vertical framing cannot clip anyone

The crop is `1080x1920` taken from a frame scaled to 3413x1920 — full height.
Nothing can be cut off vertically, so a head that looks "cropped at the top"
is genuinely above the camera's field of view in the source, not a bug.

## Classify the camera before choosing a moment

This production cut unpredictably between four sources, so a moment picked
from the transcript is not automatically crop-friendly:

| class | content | crop to 9:16? |
|---|---|---|
| A | two-shot, two men | yes, pick a focus |
| B | two-shot, man + woman | yes, pick a focus |
| C | overhead shot of cards on the table | poor — narrow slice of table |
| D | full-screen digital game board | poor — and it carries a strip of four player webcams along the top |

**Check the frame at the exact moment before committing.** Speech-driven
selection lands on whatever camera happened to be live.

## Other pitfalls from this job

- **Pin the language.** Whisper auto-detect drifts across Serbian / Croatian /
  Bosnian and a wrong guess poisons every downstream stage:
  `transcribe.py in.mp4 out.json large-v3 sr`. `small` is too weak for Serbian.
- **Verify the caption font draws your diacritics.** A font missing `č ć ž š đ`
  renders empty boxes and fails silently. Arial Black on macOS is fine —
  proven by burning a test ASS onto black and reading the glyphs back.
- **CPU-heavy work starves the GPU transcription.** Rendering clips while
  `mlx-whisper` runs dropped it from ~250 to ~77 mel-frames/s. Transcribe
  first, render after.
- **Per-word timings jitter backwards**; `build_ass` normalises so two caption
  events never stack on the same frames. Keep that pass.
