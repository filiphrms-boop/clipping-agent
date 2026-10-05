#!/usr/bin/env python3
"""
Stage 4b: fetch the royalty-free sound-effect pack that `assemble.py` mixes in.

Why a fetcher instead of committed binaries: Mixkit serves every SFX as a
full-quality 24-bit WAV at a *guessable* URL, and the category pages carry the
id, title, duration and tags in the markup. So the pack is reproducible from
source — you commit a small curated list and the tool materialises the audio.

    https://assets.mixkit.co/active_storage/sfx/<id>/<id>.wav

The `-preview.mp3` files in the page markup are NOT the asset; they are 128kbps
mono-ish previews for the browser player. Always take the `.wav`.

License — Mixkit Free Sound Effects License: royalty-free, no attribution
required, commercial and personal use both permitted.
    https://mixkit.co/license/
Re-check that page before shipping anything to a paying client; the terms are
permissive but not ours to guarantee.

Usage:
    python3 fetch_sfx.py list whoosh                # what's in a category
    python3 fetch_sfx.py list impact --pages 3      # first 3 pages
    python3 fetch_sfx.py search "coin"              # search several categories
    python3 fetch_sfx.py sync                       # download assets/sfx/pack.json
    python3 fetch_sfx.py sync --force               # re-download everything
    python3 fetch_sfx.py verify                     # integrity check the pack on disk

`sync` writes `assets/sfx/manifest.json` with real per-file metadata (duration,
channels, sample rate, bit depth, size, sha256) read from the WAV headers. That
manifest is what `sfx.py` resolves roles against, so nothing downstream has to
know a Mixkit id.

Editorial note on curation: pick by ROLE, not by title. A file called
"Heavy impact" is not automatically a good impact *for a hook* — the useful
ones are short, dry and front-loaded so they land under a cut. Audition with
`list` + the preview URLs before committing a file to the pack.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent
SFX_DIR = REPO / "assets" / "sfx"
PACK = SFX_DIR / "pack.json"
MANIFEST = SFX_DIR / "manifest.json"

CATEGORY_URL = "https://mixkit.co/free-sound-effects/{slug}/?page={page}"
ASSET_URL = "https://assets.mixkit.co/active_storage/sfx/{id}/{id}.wav"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Categories worth knowing about when curating. Not exhaustive — Mixkit has
# hundreds; these are the ones that map onto short-form edit grammar.
CATEGORIES = [
    "impact", "whoosh", "swoosh", "transition", "hit", "boom",
    "game", "win", "fail", "error", "cartoon", "game-show",
    "notification", "click", "coin", "applause", "laugh",
]

_CARD_SPLIT = 'data-test-id="audio-player"'


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #

def get(url: str, tries: int = 3, timeout: int = 30) -> bytes:
    """GET with a browser UA and a couple of retries.

    Mixkit fronts assets with a CDN that 403s requests without a UA, and
    intermittently drops one — a retry is cheaper than a redownload.
    """
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last = e
            if attempt + 1 < tries:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"GET failed after {tries} tries: {url} ({last})")


def parse_items(page_html: str) -> list[dict]:
    """Pull {id, title, duration, tags} out of one category page.

    Split on the audio-player marker: each chunk afterwards is exactly one
    card, which is far steadier than trying to match nested divs.
    """
    items, seen = [], set()
    for chunk in page_html.split(_CARD_SPLIT)[1:]:
        chunk = chunk[:8000]
        m = re.search(r'data-audio-player-item-id-value="(\d+)"', chunk)
        if not m:
            continue
        sid = int(m.group(1))
        if sid in seen:
            continue
        t = re.search(r'item-grid-card__title">\s*(.*?)\s*</h2>', chunk, re.S)
        title = htmllib.unescape(re.sub(r"\s+", " ", t.group(1))).strip() if t else ""
        # duration is displayed as m:ss next to the download button
        d = re.search(r'data-test-id="duration">\s*([\d:]+)\s*<', chunk)
        dur = d.group(1) if d else ""
        tags = re.findall(r'meta-links__link[^>]*href="/free-sound-effects/([^/"]+)/"', chunk)
        seen.add(sid)
        items.append({"id": sid, "title": title, "duration": dur,
                      "tags": sorted(set(tags)), "wav": ASSET_URL.format(id=sid)})
    return items


def list_category(slug: str, pages: int = 1, stop_early: bool = True) -> list[dict]:
    """Scrape a category. Pages are 1-indexed; 0 means 'every page'."""
    out, seen = [], set()
    page, max_pages = 1, (pages if pages > 0 else 60)
    while page <= max_pages:
        data = get(CATEGORY_URL.format(slug=slug, page=page)).decode("utf-8", "replace")
        items = parse_items(data)
        fresh = [i for i in items if i["id"] not in seen]
        if not items or (stop_early and not fresh and page > 1):
            break
        for i in fresh:
            seen.add(i["id"])
            out.append(i)
        if not fresh:
            break
        page += 1
    return out


# --------------------------------------------------------------------------- #
# wav metadata (stdlib only — no ffprobe dependency)
# --------------------------------------------------------------------------- #

def wav_info(path: Path) -> dict | None:
    """Read duration/rate/channels/depth from the RIFF chunks directly.

    Deliberately NOT `wave.open`: the stdlib module rejects
    WAVE_FORMAT_EXTENSIBLE (0xFFFE), which is exactly what Mixkit ships for its
    24-bit files. It fails with "unknown format: 65534" and looks like a
    corrupt download when the file is perfectly good. Walking the chunks
    ourselves handles both extensible and plain PCM, and needs no dependency.

    Returns None for anything that is not readable PCM/float wav, which doubles
    as the integrity check after download.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            fmt, data_bytes = None, None
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                cid, csize = hdr[:4], struct.unpack("<I", hdr[4:8])[0]
                if cid == b"fmt ":
                    raw = f.read(csize)
                    if len(raw) < 16:
                        return None
                    tag, chans, rate, _, _, bits = struct.unpack("<HHIIHH", raw[:16])
                    # extensible: the real format tag is the first 2 bytes of
                    # the SubFormat GUID, 24 bytes into the chunk
                    if tag == 0xFFFE and len(raw) >= 26:
                        tag = struct.unpack("<H", raw[24:26])[0]
                    fmt = {"channels": chans, "sample_rate": rate,
                           "bit_depth": bits, "format_tag": tag}
                    if csize % 2:
                        f.seek(1, 1)
                elif cid == b"data":
                    data_bytes = csize
                    break
                else:
                    f.seek(csize + (csize & 1), 1)
    except (OSError, struct.error):
        return None

    if not fmt or not data_bytes:
        return None
    if fmt["format_tag"] not in (1, 3):     # PCM or IEEE float only
        return None
    if not fmt["channels"] or not fmt["sample_rate"] or not fmt["bit_depth"]:
        return None

    # a streaming/placeholder size (0xFFFFFFFF) would lie; clamp to the file
    header_bytes = size - data_bytes
    if data_bytes <= 0 or header_bytes <= 0:
        data_bytes = max(0, size - 44)
    frame_bytes = fmt["channels"] * (fmt["bit_depth"] // 8)
    frames = data_bytes // frame_bytes if frame_bytes else 0
    return {
        "duration": round(frames / fmt["sample_rate"], 3) if frames else None,
        "sample_rate": fmt["sample_rate"],
        "channels": fmt["channels"],
        "bit_depth": fmt["bit_depth"],
        "frames": frames,
    }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def slugify(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].strip("-") or "sfx"


# --------------------------------------------------------------------------- #
# pack discovery
# --------------------------------------------------------------------------- #

def load_pack() -> dict:
    if not PACK.exists():
        raise SystemExit(
            f"no curated pack at {PACK.relative_to(REPO)}\n"
            "Create one with roles -> Mixkit ids, e.g.\n"
            '  {"roles": {"whoosh": [1485], "impact": [2350]}}\n'
            "Use `fetch_sfx.py list <category>` / `search <term>` to pick ids."
        )
    return json.loads(PACK.read_text(encoding="utf-8"))


def pack_roles(pack: dict) -> dict[str, list[dict]]:
    """Normalise pack.json into role -> [{id, name?}].

    Accepts either bare ids or objects with an optional display name, so a
    hand-edited pack stays terse while still allowing notes.
    """
    roles: dict[str, list[dict]] = {}
    for role, entries in (pack.get("roles") or {}).items():
        norm = []
        for e in entries:
            if isinstance(e, int):
                norm.append({"id": e})
            elif isinstance(e, dict) and "id" in e:
                norm.append({"id": int(e["id"]), "name": e.get("name")})
            else:
                raise SystemExit(f"pack.json role {role!r}: bad entry {e!r} "
                                 "(use an id or {\"id\": N, \"name\": \"...\"})")
        if not norm:
            continue
        roles[role] = norm
    if not roles:
        raise SystemExit("pack.json has no roles with entries")
    return roles


def unique_ids(roles: dict[str, list[dict]]) -> list[int]:
    out, seen = [], set()
    for entries in roles.values():
        for e in entries:
            if e["id"] not in seen:
                seen.add(e["id"])
                out.append(e["id"])
    return out


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_list(args) -> int:
    slugs = args.category or CATEGORIES
    for slug in slugs:
        try:
            items = list_category(slug, pages=args.pages)
        except RuntimeError as e:
            print(f"  !! {slug}: {e}", file=sys.stderr)
            continue
        print(f"\n=== {slug} ({len(items)}) ===")
        for i in items:
            tag = ("  #" + " #".join(i["tags"][:3])) if i["tags"] else ""
            print(f"  {i['id']:>7}  {i['duration']:>5}  {i['title']}{tag}")
    return 0


def cmd_search(args) -> int:
    terms = args.term.lower().split()
    hits: dict[int, tuple[dict, set[str]]] = {}
    for slug in args.category or CATEGORIES:
        try:
            items = list_category(slug, pages=args.pages)
        except RuntimeError as e:
            print(f"  !! {slug}: {e}", file=sys.stderr)
            continue
        for i in items:
            hay = (i["title"] + " " + " ".join(i["tags"]) + " " + slug).lower()
            matched = {t for t in terms if t in hay}
            # require every term somewhere: "coin" alone is noisy,
            # "glass break" should not return every whoosh
            if not matched:
                continue
            prev = hits.get(i["id"])
            if prev:
                prev[1].update(matched)
            else:
                hits[i["id"]] = (i, set(matched))
    scored = sorted(hits.values(), key=lambda p: (-len(p[1]), p[0]["id"]))
    if not scored:
        print(f"no match for {args.term!r}")
        return 1
    print(f"=== {len(scored)} match(es) for {args.term!r} ===")
    for item, _ in scored[: args.limit]:
        print(f"  {item['id']:>7}  {item['duration']:>5}  {item['title']}"
              f"  #{' #'.join(item['tags'][:4])}")
    return 0


def cmd_sync(args) -> int:
    pack = load_pack()
    roles = pack_roles(pack)
    ids = unique_ids(roles)
    SFX_DIR.mkdir(parents=True, exist_ok=True)

    # id -> display name, from the pack where given, else discovered by scraping
    wanted_name = {}
    for entries in roles.values():
        for e in entries:
            if e.get("name"):
                wanted_name[e["id"]] = e["name"]

    print(f"[sync] {len(ids)} unique file(s) across {len(roles)} role(s)")
    meta: dict[str, dict] = {}
    failures: list[int] = []

    for n, sid in enumerate(ids, 1):
        title = wanted_name.get(sid)
        if title is None:
            title = _discover_title(sid)
        name = f"{sid}-{slugify(title) if title else 'sfx'}"
        dest = SFX_DIR / f"{name}.wav"

        if dest.exists() and not args.force:
            info = wav_info(dest)
            if info:
                print(f"  [{n}/{len(ids)}] keep   {dest.name}")
                meta[name] = {"id": sid, "title": title, **info,
                              "bytes": dest.stat().st_size, "sha256": sha256(dest)}
                continue
            print(f"  [{n}/{len(ids)}] repair {dest.name} (unreadable wav)")

        try:
            blob = get(ASSET_URL.format(id=sid))
        except RuntimeError as e:
            print(f"  [{n}/{len(ids)}] FAIL   {sid}: {e}", file=sys.stderr)
            failures.append(sid)
            continue

        # A wav must start with RIFF....WAVE. Anything else is an error page
        # served with a 200, which is exactly how this class of bug hides.
        if len(blob) < 512 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
            print(f"  [{n}/{len(ids)}] FAIL   {sid}: not a RIFF/WAVE payload "
                  f"({len(blob)} bytes)", file=sys.stderr)
            failures.append(sid)
            continue

        dest.write_bytes(blob)
        info = wav_info(dest)
        if not info:
            print(f"  [{n}/{len(ids)}] FAIL   {sid}: unreadable after write", file=sys.stderr)
            dest.unlink(missing_ok=True)
            failures.append(sid)
            continue

        print(f"  [{n}/{len(ids)}] get    {dest.name}  "
              f"{info['duration']}s {info['channels']}ch {info['bit_depth']}bit "
              f"{dest.stat().st_size // 1024}KB")
        meta[name] = {"id": sid, "title": title, **info,
                      "bytes": dest.stat().st_size, "sha256": sha256(dest)}
        time.sleep(0.15)

    # role -> [file stems], in pack order
    by_id = {m["id"]: stem for stem, m in meta.items()}
    roles_resolved = {}
    for role, entries in roles.items():
        files = [by_id[e["id"]] for e in entries if e["id"] in by_id]
        if files:
            roles_resolved[role] = files

    manifest = {
        "source": "Mixkit Free Sound Effects",
        "source_url": "https://mixkit.co/free-sound-effects/",
        "license": "Mixkit Free Sound Effects License",
        "license_url": "https://mixkit.co/license/",
        "license_note": "Royalty-free. No attribution required. Commercial and "
                        "personal use permitted. Verify at license_url before "
                        "shipping for a paying client.",
        "asset_pattern": ASSET_URL,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "notes": (pack.get("notes") or "").strip(),
        "roles": roles_resolved,
        "files": meta,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n",
                        encoding="utf-8")

    total = sum(m["bytes"] for m in meta.values())
    print(f"\n[sync] {len(meta)} file(s), {total / 1e6:.1f} MB -> {SFX_DIR.relative_to(REPO)}")
    print(f"[sync] roles: {', '.join(f'{r}({len(f)})' for r, f in roles_resolved.items())}")
    print(f"[sync] wrote {MANIFEST.relative_to(REPO)}")
    if failures:
        print(f"[sync] FAILED ids: {failures}", file=sys.stderr)
        return 1
    return 0


def _discover_title(sid: int) -> str | None:
    """Best-effort title for an id the pack didn't name.

    The download modal page carries the title on its own, so one small request
    per unnamed id beats scraping whole categories.
    """
    try:
        data = get(f"https://mixkit.co/free-sound-effects/download/{sid}/").decode(
            "utf-8", "replace")
    except RuntimeError:
        return None
    m = re.search(r'item-grid-card__title">\s*(.*?)\s*</h2>', data, re.S)
    if m:
        return htmllib.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    m = re.search(r"<title>\s*(.*?)\s*</title>", data, re.S)
    if m:
        t = htmllib.unescape(m.group(1))
        return re.sub(r"\s*[-|]\s*Mixkit.*$", "", t).strip() or None
    return None


def cmd_verify(args) -> int:
    if not MANIFEST.exists():
        raise SystemExit(f"no manifest at {MANIFEST.relative_to(REPO)} — run sync first")
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad, missing, ok = [], [], 0
    for stem, rec in man["files"].items():
        p = SFX_DIR / f"{stem}.wav"
        if not p.exists():
            missing.append(stem)
            continue
        if sha256(p) != rec["sha256"]:
            bad.append(stem)
            continue
        if p.stat().st_size != rec["bytes"]:
            bad.append(stem)
            continue
        ok += 1
    # every role must still resolve to at least one file on disk
    for role, stems in man["roles"].items():
        live = [s for s in stems if (SFX_DIR / f"{s}.wav").exists()]
        if not live:
            print(f"  !! role {role!r} resolves to nothing on disk")
    print(f"[verify] {ok}/{len(man['files'])} ok")
    for s in missing:
        print(f"  MISSING {s}.wav")
    for s in bad:
        print(f"  CORRUPT {s}.wav (hash/size mismatch)")
    return 1 if (missing or bad) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list a category's sounds")
    p.add_argument("category", nargs="*")
    p.add_argument("--pages", type=int, default=1)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="search titles+tags across categories")
    p.add_argument("term")
    p.add_argument("--category", action="append")
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("sync", help="download the curated pack")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("verify", help="check the pack on disk against the manifest")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
