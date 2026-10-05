#!/usr/bin/env python3
"""
SFX cue layer for `assemble.py`.

Turns a list of sound-effect cues into ffmpeg filter chains, so an edit
decision list can carry the audio punctuation that short-form video actually
needs: an impact on the opening beat, a whoosh on every segment join, a
comedic sting on the fail.

Design decisions worth knowing:

* **Roles, not filenames.** A cue says `"role": "whoosh"`, not a path. The
  library resolves roles against `assets/sfx/manifest.json`, so the pack can be
  re-curated without touching a single EDL.
* **Repeated roles rotate, deterministically.** Four whoosh cues in one edit
  pull four *different* whooshes, cycling through the pack in manifest order.
  No RNG, so a re-render is byte-comparable instead of "sounds different
  today". `pick` forces a specific index; `file` bypasses roles entirely.
* **The limiter is the safety net, not the mix.** Cues are summed
  (`amix normalize=0`) so the existing game+music bed is never attenuated by
  adding SFX, and a final `alimiter` catches the peak that summing may create.
  Without this, every whoosh you add would quietly duck the music.

Cue shape (all times in seconds on the ASSEMBLED timeline):

    { "role": "whoosh", "at": 3.4 }                  # -6 dB default
    { "role": "impact", "at": 0.05, "gain": -3 }
    { "role": "impact", "at": 8.1, "pick": 2 }       # 3rd impact file
    { "file": "assets/sfx/472-slow-sad-trombone-fail.wav",
      "at": 4.0, "gain": -4, "trim": 0.1, "duration": 2.5, "fade_out": 0.3 }

`gain` is dB relative to the file. -12..-4 is the useful range; go louder only
for the opening hit. `trim` starts partway into the file, `duration` caps how
much of it is used, `fade_out` tapers the tail so a sting does not end abruptly
under a voice-over.

CLI:
    python3 sfx.py list                       # the pack, by role
    python3 sfx.py list whoosh                # one role in detail
    python3 sfx.py check edl.json out.mp4     # did the cues actually land?
"""
from __future__ import annotations

import array
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
SFX_DIR = REPO / "assets" / "sfx"
MANIFEST = SFX_DIR / "manifest.json"

DEFAULT_GAIN_DB = -6.0
TARGET_RATE = None          # None = let ffmpeg negotiate against the bed


class SfxError(Exception):
    """A cue that cannot be rendered. Raised with the cue text attached."""


class SfxLibrary:
    """The pack on disk, as described by manifest.json."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else REPO
        self.dir = self.root / "assets" / "sfx"
        manifest = self.dir / "manifest.json"
        if not manifest.exists():
            raise SfxError(
                f"no SFX manifest at {manifest}\n"
                "Run: python3 fetch_sfx.py sync"
            )
        self.man = json.loads(manifest.read_text(encoding="utf-8"))
        self.files: dict[str, dict] = self.man.get("files") or {}
        self.roles: dict[str, list[str]] = self.man.get("roles") or {}
        if not self.files:
            raise SfxError(f"{manifest} lists no files — re-run fetch_sfx.py sync")

        # deterministic rotation cursor, per role
        self._cursor: dict[str, int] = {}

    # -- resolution -------------------------------------------------------- #

    def path_for(self, stem: str) -> Path:
        p = self.dir / f"{stem}.wav"
        if not p.exists():
            raise SfxError(f"missing on disk: {p.name} (run fetch_sfx.py sync)")
        return p

    def choose(self, role: str, pick: int | None = None) -> str:
        """Resolve a role to a file stem, rotating on repeat calls."""
        stems = self.roles.get(role)
        if not stems:
            known = ", ".join(sorted(self.roles)) or "(none)"
            raise SfxError(f"unknown SFX role {role!r}; pack has: {known}")
        if pick is not None:
            if not 0 <= pick < len(stems):
                raise SfxError(
                    f"pick {pick} out of range for role {role!r} "
                    f"(0..{len(stems) - 1})"
                )
            return stems[pick]
        i = self._cursor.get(role, 0)
        self._cursor[role] = (i + 1) % len(stems)
        return stems[i]

    def relative(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)

    def duration_of(self, stem: str) -> float | None:
        rec = self.files.get(stem) or {}
        d = rec.get("duration")
        return float(d) if d else None


# --------------------------------------------------------------------------- #
# cue -> filter chain
# --------------------------------------------------------------------------- #

def _linear_gain(db: float) -> float:
    """dB -> linear multiplier, computed here rather than in ffmpeg.

    `volume=-6dB` is valid ffmpeg, but a bare negative number inside a
    filtergraph arg is exactly the shape that has bitten this repo before
    (see the escaped commas in render.py's _focus_expr). A plain float cannot
    be misparsed.
    """
    return round(10.0 ** (float(db) / 20.0), 6)


def normalise_cues(cues, lib: SfxLibrary, total: float) -> list[dict]:
    """Validate + resolve cues. Fails loudly rather than rendering silence."""
    out = []
    for n, cue in enumerate(cues, 1):
        if not isinstance(cue, dict):
            raise SfxError(f"cue {n}: expected an object, got {type(cue).__name__}")
        if "at" not in cue:
            raise SfxError(f"cue {n}: missing required 'at' (seconds on the timeline)")

        at = float(cue["at"])
        if at < 0:
            raise SfxError(f"cue {n}: 'at' must be >= 0, got {at}")

        role, pick = cue.get("role"), cue.get("pick")
        explicit = cue.get("file")

        if explicit and role:
            raise SfxError(f"cue {n}: 'file' and 'role' are mutually exclusive")
        if not explicit and not role:
            raise SfxError(f"cue {n}: needs 'role' or 'file'")

        if explicit:
            p = Path(explicit)
            if not p.is_absolute():
                p = lib.root / p
            if not p.exists():
                raise SfxError(f"cue {n}: file not found: {explicit}")
            stem = p.stem
        else:
            assert role is not None      # guard above guarantees one of file/role
            stem = lib.choose(str(role), pick)
            p = lib.path_for(stem)

        gain = float(cue.get("gain", DEFAULT_GAIN_DB))
        trim = float(cue.get("trim", 0.0) or 0.0)
        if trim < 0:
            raise SfxError(f"cue {n}: 'trim' must be >= 0")

        natural = lib.duration_of(stem)
        dur = cue.get("duration")
        if dur is not None:
            dur = float(dur)
            if dur <= 0:
                raise SfxError(f"cue {n}: 'duration' must be > 0")

        fade_out = cue.get("fade_out")
        if fade_out is not None:
            fade_out = float(fade_out)
            if fade_out <= 0:
                raise SfxError(f"cue {n}: 'fade_out' must be > 0")
            if dur is not None and fade_out >= dur:
                raise SfxError(
                    f"cue {n}: fade_out ({fade_out}s) must be shorter than "
                    f"duration ({dur}s), or the cue never reaches full level"
                )

        usable = (natural - trim) if natural else None
        if dur is not None and usable is not None and dur > usable + 1e-6:
            # not fatal — the tail is simply silence — but it is almost always
            # a typo, and silence is invisible until you watch the render
            print(f"[sfx] cue {n}: duration {dur}s exceeds the {usable:.2f}s "
                  f"left in {stem} after trim; the tail will be silent",
                  file=sys.stderr)

        out.append({
            "n": n, "stem": stem, "path": p, "at": at, "gain": gain,
            "trim": trim, "duration": dur, "fade_out": fade_out,
            "natural": natural,
        })

        if total and at >= total:
            print(f"[sfx] cue {n}: 'at' ({at}s) is past the end of the "
                  f"{total:.2f}s edit — it will be trimmed away", file=sys.stderr)

    _sum_check(out)
    return out


def _sum_check(resolved: list[dict]) -> None:
    """Warn when near-simultaneous cues will sum into the limiter.

    Stacking three loud cues on the same beat is a legitimate technique, but it
    is worth a line of output: the limiter will hold the peak down and the
    result will sound flatter than the gains suggest.
    """
    for a, b in zip(resolved, resolved[1:]):
        if abs(a["at"] - b["at"]) < 0.05:
            print(f"[sfx] cues {a['n']} and {b['n']} land within 50ms of each "
                  f"other at {a['at']:.2f}s — they will sum", file=sys.stderr)


def build_chains(resolved: list[dict], first_index: int
                 ) -> tuple[list[str], list[str], list[str]]:
    """One ffmpeg input per cue, and the chains that place them in time.

    Returns (input_paths, chains, labels). input `first_index + k` belongs to
    cue k, whose output pad is labels[k].
    """
    inputs: list[str] = []
    chains: list[str] = []
    labels: list[str] = []

    for k, c in enumerate(resolved):
        idx = first_index + k
        inputs.append(str(c["path"].resolve()))

        parts = []
        # 1. take the slice of the file we want, and zero its clock
        if c["duration"] is not None:
            start = c["trim"]
            parts.append(f"atrim=start={start:.4f}:end={start + c['duration']:.4f}")
        elif c["trim"] > 0:
            parts.append(f"atrim=start={c['trim']:.4f}")
        else:
            parts.append("anull")
        parts.append("asetpts=PTS-STARTPTS")

        # 2. force a common shape so amix never has to guess (mono packs are
        #    out there, and channel mismatch is an unhelpful amix error)
        if TARGET_RATE:
            parts.append(f"aformat=sample_fmts=fltp:channel_layouts=stereo:"
                         f"sample_rates={TARGET_RATE}")
        else:
            parts.append("aformat=sample_fmts=fltp:channel_layouts=stereo")

        # 3. level
        parts.append(f"volume={_linear_gain(c['gain'])}")

        # 4. taper the tail (relative to the cue's own clock — before adelay)
        if c["fade_out"]:
            length = c["duration"] if c["duration"] is not None else (
                (c["natural"] or 0) - c["trim"])
            st = max(0.0, length - c["fade_out"])
            parts.append(f"afade=t=out:st={st:.3f}:d={c['fade_out']:.3f}")

        # 5. slide it to its position on the assembled timeline
        parts.append(f"adelay={int(round(c['at'] * 1000))}:all=1")

        label = f"sfx{k}"
        chains.append(f"[{idx}:a]{','.join(parts)}[{label}]")
        labels.append(f"[{label}]")

    return inputs, chains, labels


def build_sfx_mix(resolved: list[dict], chains: list[str], labels: list[str]) -> str:
    """Sum the cues into one stream.

    `normalize=0` is the point: amix's default divides by the input count, so
    each added cue would drop every other cue's level. `duration=longest` keeps
    a late cue from being cut off by an early one.
    """
    return (f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:"
            f"dropout_transition=0:normalize=0[sfxall]")


# --------------------------------------------------------------------------- #
# verification — did the cues actually land in the render?
# --------------------------------------------------------------------------- #

DB_FLOOR = -100.0


def _decode_mono(path: Path, rate: int = 16000) -> bytes:
    """Decode any media file to raw mono PCM.

    Only *decoding* is needed here, so a plain ffmpeg is enough — this is
    deliberately not the libass-probing locator that render.py/assemble.py
    carry, because a caption filter has nothing to do with reading audio.
    """
    exe = shutil.which("ffmpeg")
    if not exe:
        for cand in ("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
                     "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
            if os.path.exists(cand):
                exe = cand
                break
    if not exe:
        raise SfxError("no ffmpeg on PATH — needed to decode the render for --check")

    proc = subprocess.run(
        [exe, "-v", "error", "-i", str(path), "-vn",
         "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True)
    if proc.returncode != 0:
        raise SfxError(f"ffmpeg could not decode {path}:\n"
                       f"{proc.stderr.decode('utf-8', 'replace')[-400:]}")
    return proc.stdout


def _residual(a: bytes, b: bytes) -> bytes:
    """a - b, sample by sample, as s16le.

    This is the honest way to measure a cue's contribution: two renders of the
    same EDL that differ only by the `sfx` block produce identical programme
    audio, so subtracting one from the other leaves the effects themselves.
    It beats comparing window energies against a bed, because a whoosh is
    quiet for its first few hundred milliseconds — measuring the bed's level
    where a swell has not risen yet reports a perfectly good cue as missing.
    """
    n = min(len(a), len(b)) // 2
    if n <= 0:
        return b""
    A = array.array("h")
    A.frombytes(a[: 2 * n])
    B = array.array("h")
    B.frombytes(b[: 2 * n])
    diff = array.array("h", bytes(2 * n))
    for i in range(n):
        v = A[i] - B[i]
        diff[i] = -32768 if v < -32768 else (32767 if v > 32767 else v)
    return diff.tobytes()


def _envelope(pcm: bytes, rate: int, win_ms: int = 20, hop_ms: int = 5
              ) -> tuple[array.array, float]:
    """Short-window RMS, in dBFS. Returns (envelope, hop_seconds)."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    win = max(1, rate * win_ms // 1000)
    hop = max(1, rate * hop_ms // 1000)
    env = array.array("f")
    for i in range(0, max(0, len(samples) - win + 1), hop):
        acc = 0
        for v in samples[i:i + win]:
            acc += v * v
        rms = math.sqrt(acc / win) / 32768.0
        env.append(20.0 * math.log10(rms) if rms > 0 else DB_FLOOR)
    return env, hop / rate


def _window_peak(env: array.array, hop: float, t0: float, t1: float
                 ) -> tuple[float, float]:
    """Loudest envelope frame in [t0,t1), and when it happened.

    Window spans the cue's OWN length (not a fixed slice): a swell must be
    allowed to reach its peak, or the measurement answers a question nobody
    asked.
    """
    a = max(0, int(t0 / hop))
    b = min(len(env), max(a + 1, int(math.ceil(t1 / hop))))
    if a >= len(env):
        return DB_FLOOR, t0
    best_i, best = a, DB_FLOOR
    for i in range(a, b):
        if env[i] > best:
            best, best_i = env[i], i
    return best, best_i * hop


def _median(values: list[float]) -> float:
    if not values:
        return DB_FLOOR
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def cmd_check(args) -> int:
    """Measure the energy each cue actually contributed to the rendered file.

    A successful ffmpeg run proves nothing about whether a sound is *audible*:
    a cue with the wrong gain, or an `at` that drifted, still exits 0 and
    produces a file that looks correct in every listing. So measure the audio.

    With `--control` (the same EDL rendered with its `sfx` block removed) the
    two renders are subtracted and the reported figure is what the cue itself
    added — programme material and codec noise cancel out. Without a control
    the baseline is the clip-wide median, which only catches a missing cue.

    The measurement window is the cue's own length, not a fixed slice: a whoosh
    spends its first few hundred milliseconds rising, and a short window would
    call a perfectly good swell "missing".
    """
    edl = json.loads(Path(args.edl).read_text(encoding="utf-8"))
    cues = edl.get("sfx") or []
    if not cues:
        print("error: that EDL has no 'sfx' block", file=sys.stderr)
        return 1

    lib = SfxLibrary()
    total = sum(s["end"] - s["start"] for s in edl["segments"])
    resolved = normalise_cues(cues, lib, total)

    rate = 16000
    render_pcm = _decode_mono(Path(args.render), rate)
    if args.control:
        ctrl_pcm = _decode_mono(Path(args.control), rate)
        if abs(len(render_pcm) - len(ctrl_pcm)) > rate:      # >0.5s apart
            print(f"error: control is {abs(len(render_pcm) - len(ctrl_pcm)) / 2 / rate:.2f}s "
                  f"different in length — it must be the same EDL minus 'sfx'",
                  file=sys.stderr)
            return 1
        env, hop = _envelope(_residual(render_pcm, ctrl_pcm), rate)
        baseline = _median(list(env))
        source = f"residual vs {Path(args.control).name}"
    else:
        env, hop = _envelope(render_pcm, rate)
        baseline = _median(list(env))
        source = "clip-wide median (rough — pass --control for an exact figure)"

    print(f"[check] {Path(args.render).name}  {len(env) * hop:.2f}s  "
          f"{len(resolved)} cue(s)")
    print(f"[check] baseline {baseline:.1f} dBFS — {source}")
    print(f"[check] {'#':>3} {'role':<26} {'at':>6} {'peak':>7} {'added':>7}  verdict")

    worst = 0
    for c in resolved:
        # span the cue's real length so a swell can reach its peak; cap at 4s
        # so one long cue does not swallow the next one's window
        length = min(4.0, max(0.2, c["natural"] or 0.4))
        peak_db, peak_t = _window_peak(env, hop, c["at"], c["at"] + length)
        added = peak_db - baseline
        offset = peak_t - c["at"]

        if added >= 6.0:
            verdict, weight = "OK", 0
        elif added >= 3.0:
            verdict, weight = "faint — raise gain", 0
        elif added >= 1.0:
            verdict, weight = "WEAK — likely lost under the bed", 1
        else:
            verdict, weight = "MISSING — not in the render", 2
        worst = max(worst, weight)

        # a peak that lands outside the cue means the sound is not where the
        # EDL asked for it, which is a different bug from "too quiet"
        if offset < 0 or offset > length + hop:
            verdict = f"TIMING? peak at {peak_t:.2f}s, outside the cue"
            worst = max(worst, 2)

        label = c["stem"].split("-", 1)[-1]
        print(f"[check] {c['n']:>3} {label[:26]:<26} {c['at']:>6.2f} "
              f"{offset:>+6.2f}s {added:>+6.1f}dB  {verdict}")

    if worst >= 2:
        print("\n[check] at least one cue is not in the render — check its 'at' "
              "against the cut points, and its gain")
    elif worst == 1:
        print("\n[check] all cues landed; at least one is quiet enough to be "
              "swallowed by a loud bed")
    else:
        print("\n[check] every cue measurably landed")
    return worst


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_list(args) -> int:
    lib = SfxLibrary()
    roles = [args.role] if args.role else sorted(lib.roles)
    for role in roles:
        stems = lib.roles.get(role)
        if not stems:
            print(f"unknown role {role!r}; pack has: {', '.join(sorted(lib.roles))}",
                  file=sys.stderr)
            return 1
        print(f"\n=== {role} ({len(stems)}) ===")
        for i, stem in enumerate(stems):
            rec = lib.files.get(stem, {})
            d = rec.get("duration")
            print(f"  [{i}] {stem}")
            print(f"      {rec.get('title', '')}  "
                  f"{d}s  {rec.get('channels')}ch {rec.get('bit_depth')}bit  "
                  f"{rec.get('bytes', 0) // 1024}KB")
    print(f"\nsource: {lib.man.get('source')} — {lib.man.get('license')}")
    print(f"license: {lib.man.get('license_url')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("list", help="show the pack, by role")
    p.add_argument("role", nargs="?")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("check", help="verify cues are audible in a render")
    p.add_argument("edl", help="the EDL that was rendered")
    p.add_argument("render", help="the rendered .mp4")
    p.add_argument("--control", help="same EDL rendered without its sfx block, "
                                     "for an exact measurement")
    p.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    try:
        return args.func(args)
    except SfxError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
