#!/usr/bin/env python3
"""Find a phrase in a transcript and show its exact timestamp + neighbours.

Usage:
    python3 find_phrase.py <transcript.json> "phrase" ["another phrase" ...]

Picking clip in/out points by eye from a coarse transcript lands cuts
mid-word. This prints the segment that actually contains the phrase and the
segments either side, so boundaries can be set on real timestamps.
"""
import json
import sys


def show(segs, phrase, ctx=2):
    pl = phrase.lower()
    for i, s in enumerate(segs):
        if pl in s["text"].lower():
            print(f'--- "{phrase}"   (segment {i}) ---')
            for j in range(max(0, i - ctx), min(len(segs), i + ctx + 1)):
                st, en, tx = segs[j]["start"], segs[j]["end"], segs[j]["text"]
                mark = ">>" if j == i else "  "
                print(f"{mark} [{st:7.2f} -> {en:7.2f}] {tx}")
            print()
            return i
    print(f'--- "{phrase}": NOT FOUND ---\n')
    return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        segs = json.load(f)["segments"]
    for phrase in sys.argv[2:]:
        show(segs, phrase)
