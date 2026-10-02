#!/usr/bin/env python3
"""
Stage 0: scout the Content Rewards board for campaigns actually worth working.

The board API is PUBLIC — no login, no credentials, no session. That means
discovery can run unattended, which was the most fragile part of the original
plan and is now a non-issue.

It ranks by **how little you have to do before you get paid**, not by the
headline CPM:

    view gate = minPayoutCents / rateCents * 1000

the views a single clip must reach on ONE platform before it earns a single
cent. A "$1.50 CPM" campaign with a $10 minimum needs 6,667 views per platform.
A "$0.60 CPM" campaign with no minimum needs none. The headline rate is the
less important number, and every guide that leads with it is leading with the
wrong one.

    python3 scout_campaigns.py                       # everything, ranked
    python3 scout_campaigns.py --gaming              # gaming/PC only
    python3 scout_campaigns.py --max-gate 0          # only no-minimum campaigns
    python3 scout_campaigns.py --json board.json

Stdlib only — no dependencies.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://contentrewards.com/api/campaign/campaigns/discover"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) clip-scout/1.0"

# description keywords that indicate an audience-location gate, which is the
# rule most likely to disqualify a campaign you would otherwise qualify for
TIER1_PATTERNS = [
    r"\btier\s*[- ]?\s*1\b", r"\btier\s*[- ]?\s*one\b",
    r"audience location", r"\b(us|uk|usa|united states|united kingdom)[/ ]+(uk|us)?\s*audience",
    r"\d{1,2}\s*%\s*(us|uk|tier)", r"english[- ]speaking (audience|countries)",
]
GAMING_CATEGORIES = {"gaming", "pc-gaming", "mobile-gaming", "esports"}


def fetch(limit=100, sort="newest", cursor=None):
    url = f"{API}?collapseGroups=true&limit={limit}&sortBy={sort}"
    if cursor:
        url += f"&cursor={urllib.parse.quote(cursor)}"
    req = urllib.request.Request(url, headers={"accept": "application/json",
                                               "user-agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def collect(max_pages=12, limit=100):
    """Walk every page, dedupe by id."""
    seen, out, cursor = set(), [], None
    for _ in range(max_pages):
        try:
            page = fetch(limit=limit, cursor=cursor)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            print(f"  ! fetch failed: {e}", file=sys.stderr)
            break
        found = []

        def walk(o):
            if isinstance(o, list):
                return [walk(v) for v in o]
            if not isinstance(o, dict):
                return None
            if "name" in o and "payouts" in o and "budgetCents" in o:
                found.append(o)
                return None
            return [walk(v) for v in o.values()]

        walk(page)
        new = 0
        for c in found:
            cid = c.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(c)
                new += 1

        pg = page.get("pagination") or {}
        cursor = pg.get("cursor") or pg.get("nextCursor") or pg.get("next")
        has_more = pg.get("hasMore", pg.get("has_more", bool(cursor)))
        if not cursor or not has_more or new == 0:
            break
    return out


def analyse(c):
    """Derive the numbers that decide whether a campaign is worth touching."""
    outs = c.get("payouts") or []
    cpm = [p for p in outs if (p.get("payoutType") or "").lower() == "cpm"]
    per_post = [p for p in outs if (p.get("payoutType") or "").lower() != "cpm"]
    platforms = c.get("platforms") or []

    # a campaign can pay differently per platform; take the best-case gate
    gates, caps = [], []
    for p in cpm:
        rate = p.get("rateCents") or 0
        if rate <= 0:
            continue
        gates.append((p.get("minPayoutCents") or 0) / rate * 1000)
        caps.append((p.get("maxPayoutCents") or 0) / 100)

    m = c.get("metrics") or {}
    desc = (c.get("description") or "")
    tier1 = [pat for pat in TIER1_PATTERNS if re.search(pat, desc, re.I)]
    cats = {x.get("id", "") for x in (c.get("categories") or [])}

    launched = c.get("launchDate") or c.get("listedAt") or c.get("createdAt")
    age_h = None
    if launched:
        try:
            t = datetime.fromisoformat(launched.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - t).total_seconds() / 3600
        except ValueError:
            pass

    budget = (c.get("budgetCents") or 0) / 100
    spent = (m.get("budgetSpentCents") or 0) / 100

    return {
        "name": (c.get("name") or "")[:58],
        "org": c.get("organizationName") or "",
        "verified": bool(c.get("organizationVerified")),
        "id": c.get("id"),
        "platforms": platforms,
        "cpm": (min(p.get("rateCents") for p in cpm) / 100) if cpm else None,
        "gate": round(min(gates)) if gates else 0,
        "cap": round(max(caps), 2) if caps else None,
        "per_post": bool(per_post),
        "budget": round(budget, 2),
        "spent": round(spent, 2),
        "remaining": round(budget - spent, 2),
        "approved": m.get("approvedSubmissionCount") or 0,
        "creators": m.get("creatorCount") or 0,
        "age_h": round(age_h, 1) if age_h is not None else None,
        "gaming": bool(cats & GAMING_CATEGORIES),
        "tier1_risk": bool(tier1),
        "requires_application": bool(c.get("requiresApplication")),
        "fresh_slot": spent == 0 and (m.get("approvedSubmissionCount") or 0) == 0,
    }


def score(r):
    """Best-first. Rewards a low view gate, live budget, and multi-platform pay."""
    if r["remaining"] <= 0:
        return -1
    g = max(r["gate"], 1)
    base = 1.0 / g                                    # cheaper to earn per view
    mult = max(1, len(r["platforms"]))                # one edit, several payouts
    fresh = 1.35 if r["fresh_slot"] else 1.0          # first-mover bonus
    pen = 0.55 if r["tier1_risk"] else 1.0            # audience-location gate
    return base * mult * fresh * pen * 1e4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gaming", action="store_true", help="gaming categories only")
    ap.add_argument("--max-gate", type=int, default=None,
                    help="only campaigns whose view gate is <= this")
    ap.add_argument("--platform", default=None, help="must allow this platform")
    ap.add_argument("--json", default=None)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    print("reading the public Content Rewards board (no credentials needed) ...")
    campaigns = collect()
    print(f"  {len(campaigns)} campaigns found\n")

    rows = [analyse(c) for c in campaigns]
    if args.gaming:
        rows = [r for r in rows if r["gaming"]]
    if args.max_gate is not None:
        rows = [r for r in rows if r["gate"] <= args.max_gate]
    if args.platform:
        rows = [r for r in rows if args.platform in (r["platforms"] or [])]
    rows = [r for r in rows if r["remaining"] > 0]
    rows.sort(key=score, reverse=True)

    print(f"{'campaign':58} {'cpm':>5} {'gate':>7} {'cap':>6} {'left':>9} "
          f"{'plats':>5} {'age':>6} {'spent':>6} {'t1':>3} {'fresh':>5}")
    print("-" * 124)
    for r in rows[:args.top]:
        cpm = f"${r['cpm']:.2f}" if r["cpm"] else "  -"
        cap = f"${r['cap']:.0f}" if r["cap"] else "-"
        age = f"{r['age_h']:.0f}h" if r["age_h"] is not None else "-"
        spent = f"{r['spent'] / r['budget']:.0%}" if r["budget"] else "-"
        print(f"{r['name']:58} {cpm:>5} {r['gate']:>7,} {cap:>6} "
              f"${r['remaining']:>8,.0f} {len(r['platforms']):>5} {age:>6} "
              f"{spent:>6} {'YES' if r['tier1_risk'] else ' no':>3} "
              f"{'yes' if r['fresh_slot'] else '':>5}")

    print("\n  gate = views a clip needs on ONE platform before it earns anything")
    print("  t1   = description carries an audience-location (Tier-1) style clause")
    print("  fresh= budget untouched AND no approved submissions yet")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(rows, fh, indent=2)
        print(f"\nwrote {args.json} ({len(rows)} campaigns)")


if __name__ == "__main__":
    main()
