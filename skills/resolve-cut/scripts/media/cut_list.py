#!/usr/bin/env python3
"""Frame-accurate cut list for assemble.py, from word-level transcripts (Scribe) and the camera's own sound.

    python3 cut_list.py plan.json <transcripts folder> <media folder> cuts.json [--fps 25] [--punch-in 1.2]

plan.json, the takes chosen from the dossier, in timeline order:
    {"<timeline>": [["01a", "C0081", 1.9, 12.6], ["01b", "C0083", 5.4, 23.8, {"pre": 0.25, "post": 0.4}], ...]}
- Each entry: take label, clip name (file name without extension), from and to in seconds of the clip (99 = to the
  end). The take runs from the first word that starts at `from` to the last word that ends before `to`.
- In and out points land on the quietest frame boundary near `pre` seconds before the first word and `post` seconds
  after the last one, without catching the neighbouring word. Silence is measured on the clip's own sound, because
  the transcript does not hear whispers and breaths.
- Pauses over --max-pause (1 s) inside a take are shortened with a cut.
- Segments alternate between zoom 1 and --punch-in (1.2), so cuts between takes do not jump; assemble.py makes the
  punch-in. --punch-in 1 turns it off.
Options per take (the dict at the end of an entry):
- "in_frame" / "out_frame": force the first take's in point or the last part's out point to an exact frame of the
  clip, when the cut falls between words with no gap (a false start like "co- contar" cut inside the take).
- "zoom", "pan", "tilt": a fixed framing for that take (assemble.py), and it stays out of the alternation.
- "no_text": true places a take that has no speech, from in_frame to out_frame.
Markers are added afterwards with add_markers.py.
One ffmpeg at a time, with nice and 2 threads, reading only the sound around each cut.
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

VIDEO = (".mp4", ".mov", ".m4v", ".mxf", ".mkv")
_paths, _frames, _sound = {}, {}, {}
A = None
FPS = 25.0


def parse_fps(x):
    x = float(x)
    for ntsc in (23.976, 29.97, 59.94):
        if abs(x - ntsc) < 0.01:
            return round(ntsc + 0.03) * 1000 / 1001
    return x


def media(clip):
    if clip not in _paths:
        hits = [os.path.join(A.media, n) for n in sorted(os.listdir(A.media))
                if os.path.splitext(n)[0] == clip and n.lower().endswith(VIDEO)]
        if not hits:
            sys.exit(f"no video file named {clip}.* in {A.media}")
        _paths[clip] = hits[0]
    return _paths[clip]


def probe_fps(clip):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0",
                        media(clip)], capture_output=True, text=True, check=True)
    n, q = r.stdout.strip().split("/")
    return float(n) / float(q)


def frames(clip):
    if clip not in _frames:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames", "-of", "csv=p=0",
                            media(clip)], capture_output=True, text=True, check=True)
        _frames[clip] = int(r.stdout.strip())
    return _frames[clip]


def energy(clip, lo, hi):
    """RMS (dB) over 40 ms around each frame boundary between lo and hi (seconds)."""
    a = max(0.0, lo - 0.1)
    k = (clip, round(a, 2), round(hi, 2))
    if k not in _sound:
        raw = subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-threads", "2", "-ss", f"{a:.3f}", "-t", f"{hi - a + 0.1:.3f}",
                              "-i", media(clip), "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                             capture_output=True, check=True, stdin=subprocess.DEVNULL).stdout
        _sound[k] = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
    x, out, f = _sound[k], [], math.ceil(lo * FPS)
    while f / FPS <= hi + 1e-9:
        c = int((f / FPS - a) * 48000)
        w = x[max(0, c - 960):c + 960]
        out.append((f, 20 * math.log10(np.sqrt(np.mean(w ** 2)) + 1e-9) if len(w) else 0.0))
        f += 1
    return out


def best(clip, lo, hi, target):
    """Quietest frame boundary between lo and hi; among the quiet ones (up to 3 dB above the quietest, or under
    -50 dB, the room noise), the closest to target."""
    cand = energy(clip, lo, hi) if hi >= lo else []
    if not cand:
        return round(target * FPS)
    m = min(e for _, e in cand)
    return min((f for f, e in cand if e <= max(m + 3, -50)), key=lambda f: abs(f / FPS - target))


def segment(take, clip, t_from, t_to, opts):
    fixed_in, fixed_out = opts.get("in_frame"), opts.get("out_frame")
    if opts.get("no_text"):
        return [{"clip": clip, "in": fixed_in, "out": fixed_out, "text": ""}]
    ws = [w for w in json.load(open(os.path.join(A.transcripts, clip + ".json"), encoding="utf-8"))["words"] if w["type"] == "word"]
    idx = [i for i, w in enumerate(ws) if w["start"] >= t_from - 0.05 and w["end"] <= t_to]
    if not idx:
        sys.exit(f"{take}: no words in {clip} between {t_from} and {t_to} s")
    a, b = idx[0], idx[-1]
    clip_end = frames(clip) / FPS
    parts, start = [], a
    for i in range(a, b):
        if ws[i + 1]["start"] - ws[i]["end"] > A.max_pause:
            parts.append((start, i))
            start = i + 1
    parts.append((start, b))
    pre, post = opts.get("pre", 0.25), opts.get("post", 0.4)
    out = []
    for k, (i, j) in enumerate(parts):
        before = ws[i - 1]["end"] + 0.02 if i > 0 else 0.0
        after = ws[j + 1]["start"] - 0.02 if j + 1 < len(ws) else clip_end
        pr = pre if k == 0 else 0.2
        po = post if k == len(parts) - 1 else 0.25
        f_in = best(clip, max(ws[i]["start"] - 0.4, before), ws[i]["start"] - 0.02, ws[i]["start"] - pr)
        f_out = min(best(clip, ws[j]["end"] + 0.02, min(ws[j]["end"] + po + 0.2, after, clip_end), ws[j]["end"] + po), frames(clip))
        out.append({"clip": clip, "in": f_in, "out": f_out, "text": " ".join(w["text"] for w in ws[i:j + 1])})
    if fixed_in is not None:
        out[0]["in"] = fixed_in
    if fixed_out is not None:
        out[-1]["out"] = fixed_out
    return out


def main():
    global A, FPS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", help="plan.json with the chosen takes")
    ap.add_argument("transcripts", help="folder with <clip>.json from Scribe")
    ap.add_argument("media", help="folder with the camera files")
    ap.add_argument("out", help="cuts.json to write (read by assemble.py)")
    ap.add_argument("--fps", help="timeline frame rate; default: the first clip's")
    ap.add_argument("--punch-in", type=float, default=1.2, help="zoom of every other segment (1 = off)")
    ap.add_argument("--max-pause", type=float, default=1.0, help="pauses longer than this inside a take get cut (s)")
    A = ap.parse_args()
    plan = json.load(open(A.plan, encoding="utf-8"))
    first = next(spec[1] for specs in plan.values() for spec in specs)
    FPS = parse_fps(A.fps) if A.fps else probe_fps(first)

    res = {}
    for name, specs in plan.items():
        segs = []
        for take, clip, t_from, t_to, *extra in specs:
            opts = extra[0] if extra else {}
            for s in segment(take, clip, t_from, t_to, opts):
                s["take"] = take
                s.update({k: opts[k] for k in ("zoom", "pan", "tilt") if k in opts})
                segs.append(s)
        rec = 0
        for k, s in enumerate(segs):
            s["rec"] = rec
            s.setdefault("zoom", 1.0 if k % 2 == 0 else A.punch_in)
            rec += s["out"] - s["in"]
        res[name] = {"segments": segs, "frames": rec, "markers": []}
    with open(A.out, "w", encoding="utf-8") as h:
        json.dump(res, h, ensure_ascii=False, indent=1)
    print(f"{A.out} at {FPS:g} fps")
    for name, t in res.items():
        print(f"\n{name}: {t['frames'] / FPS:.1f} s, {len(t['segments'])} segments")
        for s in t["segments"]:
            print(f"  {s['take']:5} {s['clip']} {s['in'] / FPS:6.2f} to {s['out'] / FPS:6.2f}  zoom {s['zoom']}  | {s['text'][:60]}")


if __name__ == "__main__":
    main()
