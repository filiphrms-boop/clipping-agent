#!/usr/bin/env python3
"""Build a review.html for a folder of rendered clips.

Usage:
    python3 make_review.py <clips_dir> [--title "Sajd Kvest #4"] [--audible]

Writes <clips_dir>/review.html: every .mp4 in the folder as a player, with its
duration / resolution / size, plus an optional notes table. This is the "you can
actually SEE them" step — clips that exist only in ~/output are, to the person
asking, clips that do not exist. Relative src paths keep it working offline from
file://.

Players are muted + autoplaying + looping, which is what you want for checking
framing, captions and on-screen text. Pass --audible for a sound-effects review:
that swaps in real controls so the cues can actually be heard. (Autoplay is
dropped in that mode — browsers block autoplay with sound, so keeping it would
just show a frozen first frame.)
"""
import json
import subprocess
import sys
from pathlib import Path

FFPROBE_CANDIDATES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe",
    "/opt/homebrew/bin/ffprobe",
    "ffprobe",
]


def find_ffprobe():
    for c in FFPROBE_CANDIDATES:
        try:
            subprocess.run([c, "-version"], capture_output=True, check=True)
            return c
        except (OSError, subprocess.CalledProcessError):
            continue
    return None


def probe(path, ffprobe):
    """-> (duration_s, 'WxH') or (None, None) if ffprobe is unavailable."""
    if not ffprobe:
        return None, None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True).stdout
        d = json.loads(out)
        st = (d.get("streams") or [{}])[0]
        dur = float(d.get("format", {}).get("duration") or 0) or None
        wh = f"{st.get('width')}x{st.get('height')}" if st.get("width") else None
        return dur, wh
    except Exception:
        return None, None


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def build(clips_dir, title, audible=False):
    clips_dir = Path(clips_dir)
    videos = sorted(p for p in clips_dir.glob("*.mp4") if not p.name.startswith("."))
    ffprobe = find_ffprobe()

    # A sound-effects review has to be HEARD. `muted autoplay` is right for
    # reviewing framing and captions, and useless for checking whether a whoosh
    # lands on the cut — so --audible swaps in controls and drops autoplay
    # (browsers refuse to autoplay with sound anyway, so autoplay there would
    # just render a frozen first frame).
    if audible:
        player = "controls playsinline preload=\"metadata\""
    else:
        player = "muted autoplay loop playsinline"

    cards, rows = [], []
    for p in videos:
        dur, wh = probe(p, ffprobe)
        size = human(p.stat().st_size)
        meta = " · ".join(x for x in [f"{dur:.1f}s" if dur else None, wh, size] if x)
        cards.append(f"""
    <figure>
      <video src="{p.name}" {player}></video>
      <figcaption><b>{p.name}</b><br><span class="meta">{meta}</span></figcaption>
    </figure>""")
        rows.append(f"      <tr><td>{p.name}</td><td>{meta}</td></tr>")

    table = ""
    if rows:
        table = ('\n  <h2>Files</h2>\n  <table>\n'
                 '    <thead><tr><th>file</th><th>duration · resolution · size</th></tr></thead>\n'
                 '    <tbody>\n' + "\n".join(rows) + "\n    </tbody>\n  </table>")

    html = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — clip review</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; padding: 28px;
         background: #14161a; color: #e8eaed;
         font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; font-weight: 600; }}
  h2 {{ font-size: 15px; margin: 32px 0 10px; font-weight: 600; color: #9aa0a6; }}
  .sub {{ color: #9aa0a6; margin: 0 0 24px; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 20px; }}
  figure {{ margin: 0; width: 260px; }}
  video {{ width: 100%; border-radius: 10px; background: #000; display: block; }}
  figcaption {{ font-size: 12.5px; margin-top: 7px; word-break: break-all; }}
  .meta {{ color: #9aa0a6; }}
  table {{ border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 6px 14px 6px 0; border-bottom: 1px solid #2a2d33; }}
  th {{ color: #9aa0a6; font-weight: 600; }}
  .empty {{ color: #9aa0a6; }}
</style>
<h1>{title}</h1>
<p class="sub">{len(videos)} clip(s) in <code>{clips_dir.resolve()}</code></p>
<div class="grid">{''.join(cards) or '<p class="empty">No .mp4 files found.</p>'}</div>
{table}
</html>
"""
    out = clips_dir / "review.html"
    out.write_text(html, encoding="utf-8")
    print(f"[review] wrote {out} ({len(videos)} clips)")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    ttl = "Clip review"
    if "--title" in sys.argv:
        ttl = sys.argv[sys.argv.index("--title") + 1]
    build(args[0], ttl, audible="--audible" in sys.argv)
