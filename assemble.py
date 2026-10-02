#!/usr/bin/env python3
"""
Stage 3b: assemble a full short-form edit from an edit decision list (EDL).

The campaign assets are 3-10s each and platform briefs ask for 10-30s, so a
qualifying clip has to be STITCHED from several source clips, reframed to 9:16,
carried by a cleared music bed, and overlaid with required on-screen text.

    python3 assemble.py edl.json

EDL shape:
{
  "out": "output/flipmaster/01_fail.mp4",
  "layout": "crop",                  # crop | pad
  "music": "input/.../music.wav",
  "music_start": 0.0,
  "music_volume": 1.0,
  "game_audio_volume": 0.35,         # source SFX under the music
  "segments": [
     {"file": "input/..../clip.mp4", "start": 0.5, "end": 3.2},
     ...
  ],
  "overlays": [
     {"text": "FLIP MASTER",         "start": 0.2, "end": 4.0, "style": "title"},
     {"text": "EARLY ACCESS ON STEAM","start": 0.8, "end": 8.0, "style": "sub"},
     {"text": "WISHLIST ON STEAM",   "start": 2.0, "end": 9.0, "style": "cta"}
  ],
  "font": "Arial Black"
}

Segment timings are absolute seconds inside each source file. Overlay timings
are relative to the assembled timeline.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

W, H = 1080, 1920
SAFE_BOTTOM = 380
SAFE_TOP = 190
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
GOLD = "&H0000D4FF"   # ASS &HBBGGRR

FFMPEG_CANDIDATES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
]


def find_ffmpeg():
    tried = []
    for cand in FFMPEG_CANDIDATES + [shutil.which("ffmpeg")]:
        if not cand or not os.path.exists(cand):
            continue
        out = subprocess.run([cand, "-hide_banner", "-filters"],
                             capture_output=True, text=True).stdout
        tried.append(cand)
        if re.search(r"^\s*[TSC.]*\s+ass\s", out, re.M):
            return cand
    raise SystemExit(f"No ffmpeg with libass. Checked: {', '.join(tried) or 'nothing'}. "
                     "brew install ffmpeg-full")


def ts(seconds):
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 3600)}:{int((seconds % 3600) // 60):02d}:{seconds % 60:05.2f}"


def build_overlays(overlays, font):
    """Static on-screen text (game name, CTA). Distinct from spoken captions."""
    if not overlays:
        return None
    # [name, alignment, fontsize, MarginV, outline, colour]
    styles = {
        "title": ("Title", 8, 92, SAFE_TOP, 8, WHITE),
        "sub":   ("Sub",   8, 54, SAFE_TOP + 128, 6, GOLD),
        "cta":   ("Cta",   2, 64, SAFE_BOTTOM, 7, WHITE),
    }
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
    ]
    for _, (name, _al, size, mv, outline, colour) in styles.items():
        lines.append(
            f"Style: {name},{font},{size},{colour},{colour},{BLACK},&H80000000,"
            f"1,0,0,0,100,100,0,0,1,{outline},3,{_al},60,60,{mv},1"
        )
    lines += ["", "[Events]",
              "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    for ov in overlays:
        style = ov.get("style", "cta")
        if style not in styles:
            raise SystemExit(f"unknown overlay style {style!r}; use {list(styles)}")
        name = styles[style][0]
        text = ov["text"].replace("\n", r"\N")
        lines.append(f"Dialogue: 0,{ts(ov['start'])},{ts(ov['end'])},{name},,"
                     f"0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def video_chain(idx, segment, layout):
    """Reframe source `idx`'s [start,end] to 9:16, labelled [v{idx}]."""
    src = f"[{idx}:v]"
    ss = f"trim=start={segment['start']:.3f}:end={segment['end']:.3f},setpts=PTS-STARTPTS,"
    if layout == "crop":
        return (f"{src}{ss}scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},fps=30,setsar=1[v{idx}]")
    return (f"{src}{ss}split=2[a{idx}][b{idx}];"
            f"[a{idx}]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},gblur=sigma=28[bg{idx}];"
            f"[b{idx}]scale={W}:-2[fg{idx}];"
            f"[bg{idx}][fg{idx}]overlay=(W-w)/2:(H-h)/2,fps=30,setsar=1[v{idx}]")


def main(edl_path):
    edl = json.loads(Path(edl_path).read_text())
    segments = edl["segments"]
    if not segments:
        raise SystemExit("EDL has no segments")
    layout = edl.get("layout", "crop")
    font = edl.get("font", "Arial Black")
    ffmpeg = find_ffmpeg()

    out_abs = Path(edl["out"]).resolve()
    out_abs.parent.mkdir(parents=True, exist_ok=True)

    workdir = tempfile.mkdtemp(prefix="fmassemble_")
    overlay_name = "overlays.ass"
    ass = build_overlays(edl.get("overlays") or [], font)
    if ass:
        Path(workdir, overlay_name).write_text(ass, encoding="utf-8")

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for seg in segments:
        cmd += ["-i", str(Path(seg["file"]).resolve())]
    # music bed last
    music_idx = None
    if edl.get("music"):
        music_idx = len(segments)
        cmd += ["-i", str(Path(edl["music"]).resolve())]

    # Each element of `chains` is ONE filtergraph chain; they are joined with
    # ';'. Never concatenate them with '' — that merges chains and ffmpeg reads
    # the next input pad as a second input to the previous filter.
    total = sum(s["end"] - s["start"] for s in segments)
    chains, labels = [], []
    for i, seg in enumerate(segments):
        chains.append(video_chain(i, seg, layout))
        labels.append(f"[v{i}]")

    chains.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=0[catv]")
    chains.append(f"[catv]ass={overlay_name}[v]" if ass else "[catv]null[v]")

    # audio: source SFX from every segment, then mixed under the cleared music
    game = []
    for i, seg in enumerate(segments):
        g = edl.get("game_audio_volume")
        vol = f",volume={g}" if g is not None else ""
        chains.append(f"[{i}:a]atrim=start={seg['start']:.3f}:end={seg['end']:.3f},"
                      f"asetpts=PTS-STARTPTS{vol}[a{i}]")
        game.append(f"[a{i}]")

    if music_idx is not None:
        chains.append(f"{''.join(game)}concat=n={len(segments)}:v=0:a=1[gamea]")
        chains.append(f"[{music_idx}:a]atrim=start={edl.get('music_start', 0.0):.3f},"
                      f"asetpts=PTS-STARTPTS,volume={edl.get('music_volume', 1.0)}[mus]")
        chains.append(f"[gamea][mus]amix=inputs=2:duration=longest:dropout_transition=0,"
                      f"atrim=0:{total:.3f},"
                      f"afade=t=out:st={max(0.0, total - 0.6):.3f}:d=0.6[aout]")
    else:
        chains.append(f"{''.join(game)}concat=n={len(segments)}:v=0:a=1,"
                      f"atrim=0:{total:.3f}[aout]")

    amap = "[aout]"
    chain = ";".join(chains)

    cmd += [
        "-filter_complex", chain,
        "-map", "[v]", "-map", amap,
        "-c:v", "libx264", "-preset", "medium", "-crf", str(edl.get("crf", 20)),
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-t", f"{total:.3f}",
        str(out_abs),
    ]

    proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr[-3000:], file=sys.stderr)
        shutil.rmtree(workdir, ignore_errors=True)
        raise SystemExit("ffmpeg failed")

    if edl.get("debug_subs"):
        shutil.copy(Path(workdir, overlay_name),
                    out_abs.with_suffix(".ass"))
    shutil.rmtree(workdir, ignore_errors=True)

    print(f"[assemble] {len(segments)} segments -> {total:.1f}s -> {out_abs}")
    return out_abs


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 assemble.py <edl.json>")
        sys.exit(1)
    main(sys.argv[1])
