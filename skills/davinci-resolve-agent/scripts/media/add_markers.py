#!/usr/bin/env python3
"""Add timeline markers (script notes, alternatives, lines still to record) to a cut list from cut_list.py.

    python3 add_markers.py cuts.json markers.json <transcripts folder> [--fps 25]

markers.json: {"<timeline>": [{"color": "Blue", "name": "...", "note": "...", <anchor>}]}, with one of two anchors:
- "seg": k, "plus": n  → n frames after the start of the k-th segment of the timeline (0 = the first);
- "clip": "C0083", "word": "today", "after": 13  → at the start of that word, the first one from 13 s into the clip.
Anchored this way, markers follow the segments when the cut list changes. Refuses two markers on the same frame
(Resolve keeps one marker per frame) and markers outside the timeline. assemble.py places them.
"""
import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cuts", help="cuts.json from cut_list.py (updated in place)")
    ap.add_argument("markers", help="markers.json")
    ap.add_argument("transcripts", help="folder with <clip>.json from Scribe")
    ap.add_argument("--fps", type=float, default=25.0, help="the cut list's frame rate (default 25)")
    a = ap.parse_args()
    cuts = json.load(open(a.cuts, encoding="utf-8"))

    def frame(tl, m):
        segs = cuts[tl]["segments"]
        if "seg" in m:
            return segs[m["seg"]]["rec"] + m.get("plus", 0)
        ws = [w for w in json.load(open(os.path.join(a.transcripts, m["clip"] + ".json"), encoding="utf-8"))["words"] if w["type"] == "word"]
        word = m["word"].lower()
        t = next((w["start"] for w in ws if w["start"] >= m.get("after", 0) and w["text"].strip(".,?!«»\"'").lower() == word), None)
        if t is None:
            sys.exit(f"{tl}: no word {m['word']!r} in {m['clip']} after {m.get('after', 0)} s")
        f = round(t * a.fps)
        s = next((s for s in segs if s["clip"] == m["clip"] and s["in"] <= f < s["out"]), None)
        if s is None:
            sys.exit(f"{tl}: {m['word']!r} at {t:.2f} s of {m['clip']} is not inside any segment")
        return s["rec"] + f - s["in"]

    for tl, marks in json.load(open(a.markers, encoding="utf-8")).items():
        cuts[tl]["markers"] = [{"frame": frame(tl, m), "color": m["color"], "name": m["name"], "note": m.get("note", "")} for m in marks]
        fs = [m["frame"] for m in cuts[tl]["markers"]]
        if len(fs) != len(set(fs)):
            sys.exit(f"two markers on the same frame in {tl}")
        if not all(0 <= f < cuts[tl]["frames"] for f in fs):
            sys.exit(f"marker outside the timeline in {tl}")
        print(tl, [(m["frame"], m["name"]) for m in cuts[tl]["markers"]])
    with open(a.cuts, "w", encoding="utf-8") as h:
        json.dump(cuts, h, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
