#!/usr/bin/env python3
"""
Stage 3: Cut a clip from the source video, reframe to 9:16, and burn in captions.

Usage:
    python3 render.py <source_video> <transcript_json> <candidates_json> <out_dir> \
                      [--layout pad|crop] [--font "Arial Black"] [--size 72] [--no-captions]

Requires ffmpeg WITH libass. Homebrew's *plain* ffmpeg formula has no
ass/subtitles/drawtext filters at all, so captions are silently impossible with
it — install `ffmpeg-full` (keg-only) instead:
    brew install ffmpeg-full
This module probes for a binary that actually has the `ass` filter and says so
plainly, rather than dying inside ffmpeg with an unreadable filter error.

Works with both transcript shapes: word timings may be at transcript["words"]
(flat) or transcript["segments"][n]["words"] (segmented).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 9:16 short-form canvas
W, H = 1080, 1920
# Reserve the lower part of the frame for TikTok/Reels UI + their caption overlay
SAFE_BOTTOM = 380
MIN_EVENT = 0.08          # shortest on-screen time for a caption event
HIGHLIGHT = "&H0000D4FF"  # ASS colour is &HBBGGRR -> gold #FFD400
WHITE = "&H00FFFFFF"

FFMPEG_CANDIDATES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",  # macOS, keg-only full build
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
]


def find_ffmpeg():
    """Return an ffmpeg that actually has the `ass` filter, or explain why not."""
    tried = []
    for cand in FFMPEG_CANDIDATES + [shutil.which("ffmpeg")]:
        if not cand or not os.path.exists(cand):
            continue
        try:
            out = subprocess.run([cand, "-hide_banner", "-filters"],
                                 capture_output=True, text=True).stdout
        except OSError:
            continue
        tried.append(cand)
        if re.search(r"^\s*[TSC.]*\s+ass\s", out, re.M):
            return cand
    raise SystemExit(
        "No ffmpeg with libass found.\n"
        f"  checked: {', '.join(tried) or 'nothing'}\n"
        "Plain Homebrew ffmpeg ships without libass/freetype/drawtext.\n"
        "  brew install ffmpeg-full\n"
        "then this will find /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg automatically."
    )


def iter_words(transcript):
    """Yield word dicts with absolute start/end, from either transcript shape."""
    if transcript.get("words"):
        for w in transcript["words"]:
            yield w
        return
    for seg in transcript.get("segments", []):
        for w in seg.get("words", []) or []:
            yield w


def words_in_range(transcript, start, end):
    return [w for w in iter_words(transcript)
            if w["end"] > start and w["start"] < end]


def chunk_words(words, max_words=3, max_gap=0.45, max_len=1.9, max_chars=22):
    """Group words into short on-screen caption chunks.

    Chunking on gaps and length (rather than a fixed word count) keeps captions
    from straddling a pause, which is what makes them feel out of sync.
    """
    chunks, cur = [], []
    for w in words:
        if not cur:
            cur = [w]
            continue
        gap = w["start"] - cur[-1]["end"]
        span = w["end"] - cur[0]["start"]
        text_len = sum(len(x["word"]) + 1 for x in cur) + len(w["word"])
        if gap > max_gap or len(cur) >= max_words or span > max_len or text_len > max_chars:
            chunks.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(words, clip_start, clip_end, font, size, outline, upper=True):
    """One event per word: the whole chunk stays on screen, the active word is gold.

    Returns None when nothing falls inside the cut range.
    """
    rel = []
    for w in words:
        if w["end"] <= clip_start or w["start"] >= clip_end:
            continue
        rel.append({
            "word": w["word"].upper() if upper else w["word"],
            "start": max(0.0, w["start"] - clip_start),
            "end": max(0.0, min(w["end"], clip_end) - clip_start),
        })
    if not rel:
        return None

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{font},{size},{WHITE},{WHITE},&H00000000,&H80000000,"
        f"1,0,0,0,100,100,0,0,1,{outline},2,2,60,60,{SAFE_BOTTOM},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # Pass 1 — one raw event per word, chunk text with the active word coloured.
    events = []
    chunks = chunk_words(rel)
    for ci, chunk in enumerate(chunks):
        next_start = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else None
        for i, active in enumerate(chunk):
            parts = []
            for j, w in enumerate(chunk):
                if j == i:
                    parts.append(f"{{\\c{HIGHLIGHT}}}{w['word']}{{\\c{WHITE}}}")
                else:
                    parts.append(w["word"])
            start = active["start"]
            end = chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk[-1]["end"] + 0.12
            if next_start is not None:
                end = min(end, next_start)
            events.append((start, end, " ".join(parts)))

    # Pass 2 — normalise. Whisper word timings jitter *backwards*, which would
    # otherwise stack two captions on the same frames and flicker. Walk in time
    # order and force every event to begin after the previous one ended.
    events.sort(key=lambda e: e[0])
    cursor = 0.0
    for idx, (start, end, text) in enumerate(events):
        nxt = events[idx + 1][0] if idx + 1 < len(events) else None
        start = max(start, cursor)
        end = max(end, start + MIN_EVENT)
        if nxt is not None and nxt > start:
            end = min(end, nxt)
        if end <= start:
            end = start + MIN_EVENT
        lines.append(f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},"
                     f"Caption,,0,0,0,,{text}")
        cursor = end

    return "\n".join(lines) + "\n"


def _focus_expr(focus):
    """ffmpeg expression for the crop x-offset that centres `focus`.

    `focus` is where the subject sits in the SOURCE frame as a fraction of
    width (0 = hard left, 0.5 = centre, 1 = hard right), or a list of
    {"t": seconds, "x": fraction} keyframes, linearly interpolated between.

    Written in terms of in_w so it stays correct whatever the source aspect
    is: after force_original_aspect_ratio=increase the frame is wider than the
    output, and we slide the window so the subject lands mid-frame.
    """
    if isinstance(focus, (list, tuple)):
        ks = sorted(((float(k["t"]), float(k["x"])) for k in focus), key=lambda p: p[0])
        if not ks:
            expr = repr(0.5)          # empty keyframe list -> centred
        else:
            expr = repr(ks[-1][1])
            for (t0, x0), (t1, x1) in zip(reversed(ks[:-1]), reversed(ks[1:])):
                seg = f"{x0}+({x1}-{x0})*(t-{t0})/({t1}-{t0})"
                expr = f"if(lt(t,{t1}),{seg},{expr})"
    else:
        expr = repr(float(focus))
    # commas separate filter args, so every comma *inside* the expression
    # must be escaped or ffmpeg reads the expression as two arguments
    return f"max(0,min(in_w-{W},({expr})*in_w-{W}/2))".replace(",", "\\,")


def build_filter(layout, ass_name, captions=True, focus=None):
    """pad = blurred background behind the whole 16:9 frame (nothing cropped).

    crop = fill the frame and cut the sides. Good for a single centred speaker,
    cuts people off in wide or multi-person shots.

    focus (crop only) = where in the source the subject sits; see _focus_expr.
    Omit it and the crop is centred, which is wrong for any two-shot.
    """
    pad = (f"[0:v]split=2[bga][fga];"
           f"[bga]scale={W}:{H}:force_original_aspect_ratio=increase,"
           f"crop={W}:{H},gblur=sigma=28[bgb];"
           f"[fga]scale={W}:-2[fgc];"
           f"[bgb][fgc]overlay=(W-w)/2:(H-h)/2[base]")
    if layout == "crop":
        base = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        head = (base + f"crop={W}:{H}[base]") if focus is None else \
               (base + f"crop={W}:{H}:{_focus_expr(focus)}:0[base]")
    else:
        head = pad
    tail = f"[base]ass={ass_name}[v]" if captions else "[base]null[v]"
    return f"{head};{tail}"


def render_clip(source_video, transcript, clip, out_dir, index, ffmpeg,
                layout="pad", font="Arial Black", size=72, outline=7,
                captions=True, crf=20, focus=None):
    start, end = float(clip["start"]), float(clip["end"])
    if end <= start:
        raise ValueError(f"clip {index}: end ({end}) must be greater than start ({start})")

    # per-clip framing wins over the CLI default: in a two-shot the crop has to
    # slide onto whoever is speaking, and that differs from clip to clip
    clip_focus = clip.get("focus", clip.get("focus_x", focus))

    slug = "".join(c if c.isalnum() else "_" for c in clip["title"]).strip("_")[:40]
    base = f"{index:02d}_{slug}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    final_out = out_dir / f"{base}.mp4"
    ass_out = out_dir / f"{base}.ass"

    words = words_in_range(transcript, start, end)
    have_captions = captions and bool(words)

    # ffmpeg runs from a scratch cwd so the ass filename needs no escaping
    workdir = tempfile.mkdtemp(prefix="cliprender_")
    sub_name = "caps.ass"
    if have_captions:
        ass = build_ass(words, start, end, font, size, outline)
        if ass is None:
            have_captions = False
        else:
            Path(workdir, sub_name).write_text(ass, encoding="utf-8")
            ass_out.write_text(ass, encoding="utf-8")
    if captions and not have_captions:
        print(f"[render] clip {index}: no words inside the cut range — captions skipped")

    # Single encode: cut + reframe + burn-in in one pass (no generation loss).
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
        "-i", str(Path(source_video).resolve()),
        "-filter_complex", build_filter(layout, sub_name, captions=have_captions,
                                        focus=clip_focus),
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        str(final_out.resolve()),
    ]
    proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    shutil.rmtree(workdir, ignore_errors=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on clip {index}:\n{proc.stderr[-2000:]}")

    print(f"[render] wrote {final_out}")
    return final_out


def main(source_video, transcript_path, candidates_path, out_dir,
         layout="pad", font="Arial Black", size=72, captions=True, focus=None):
    ffmpeg = find_ffmpeg()
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)
    with open(candidates_path, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    outputs = []
    for i, clip in enumerate(candidates["clips"], start=1):
        title = clip.get("title", f"clip_{i}")
        print(f"[render] clip {i}: {title} ({clip['start']:.1f}-{clip['end']:.1f})")
        outputs.append(render_clip(source_video, transcript, clip, out_dir, i,
                                   ffmpeg, layout=layout, font=font, size=size,
                                   captions=captions, focus=focus))

    print(f"[render] done — {len(outputs)} clips in {out_dir}")
    return outputs


if __name__ == "__main__":
    # Parse flag/value PAIRS properly. The old version filtered out every token
    # starting with "--" and then took argv[0:4] positionally, so
    # `render.py --layout crop src json cand out` silently read "crop" as the
    # source video. A flag's VALUE must be consumed along with its flag.
    argv = sys.argv[1:]
    kw, positional, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--layout":
            kw["layout"] = argv[i + 1]; i += 2
        elif a == "--focus-x":
            kw["focus"] = float(argv[i + 1]); i += 2
        elif a == "--font":
            kw["font"] = argv[i + 1]; i += 2
        elif a == "--size":
            kw["size"] = int(argv[i + 1]); i += 2
        elif a == "--no-captions":
            kw["captions"] = False; i += 1
        elif a.startswith("--"):
            print(f"unknown flag: {a}")
            sys.exit(2)
        else:
            positional.append(a); i += 1

    if len(positional) < 4:
        print("usage: python3 render.py <source_video> <transcript_json> "
              "<candidates_json> <out_dir> [--layout pad|crop] [--focus-x 0..1] "
              "[--font NAME] [--size N] [--no-captions]")
        sys.exit(1)

    main(positional[0], positional[1], positional[2], positional[3], **kw)
