#!/usr/bin/env python3
"""Dossier of a shoot: every clip in compact text, to read once before editing instead of opening clips and
transcripts one by one.

    python3 dossier.py <clips or folders...> --transcripts <folder of JSON> [--transcribe] [--sheets]
                       [--language por] --out <project>/dossier.md

For each clip: duration, resolution, fps and whether it has sound; the speech in sentences with start and end time in
the clip; pauses over 1.5 s; sentences that start like an earlier one (repeated attempts at the same line: keep the
right one, usually the last complete take); and, with --sheets, a sheet of 6 frames per clip
(<out folder>/sheets/<clip>.jpg) to describe the shot once.
- --transcripts: folder with <clip>.json from Scribe (transcribe.py). With --transcribe, the missing ones are
  transcribed (ELEVENLABS_API_KEY) and saved there.
- The file ends with a "Shot descriptions" section for the agent to fill in once, after looking at the sheets.
  Whoever edits reads the dossier; a clip is only opened (inspect_range.py) when there is a decision to make.
One ffmpeg at a time, with nice and 2 threads.
"""
import argparse
import glob
import json
import os
import re
import subprocess

from transcribe import transcribe

EXT = (".mp4", ".mov", ".m4v", ".mxf", ".mkv")
PAUSE, LONG = 0.6, 1.5


def probe(f):
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", f],
                                  capture_output=True, text=True).stdout or "{}")
    v = next((s for s in d.get("streams", []) if s["codec_type"] == "video"), None)
    if not v:
        return None
    n, q = v.get("r_frame_rate", "0/1").split("/")
    return dict(dur=float(d["format"].get("duration", 0)), w=v["width"], h=v["height"], fps=float(n) / float(q or 1),
                sound=any(s["codec_type"] == "audio" for s in d["streams"]))


def sentences(ws):
    """Words into sentences: split at sentence ends and at pauses over PAUSE."""
    out, cur = [], []
    for w in ws:
        if cur and (w["start"] - cur[-1]["end"] > PAUSE):
            out.append(cur)
            cur = []
        cur.append(w)
        if w["text"].endswith((".", "?", "!")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def key(sentence):
    return " ".join(re.sub(r"[^\w]", "", w["text"].lower()) for w in sentence[:4])


def sheet(f, info, dst):
    """6 frames at equal intervals: one fast ffmpeg per frame (-ss before -i jumps to the keyframe), joined with PIL."""
    from PIL import Image
    tw = 300
    th = round(tw * info["h"] / info["w"]) // 2 * 2
    img = Image.new("RGB", (6 * tw + 5 * 4, th), (255, 255, 255))
    for k in range(6):
        t = info["dur"] * (k + 0.5) / 6
        r = subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-filter_threads", "2", "-filter_complex_threads", "2",
                            "-threads", "2", "-ss", f"{t:.3f}", "-i", f, "-threads", "2", "-frames:v", "1",
                            "-vf", f"scale={tw}:{th}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, stdin=subprocess.DEVNULL)
        if len(r.stdout) == tw * th * 3:
            img.paste(Image.frombytes("RGB", (tw, th), r.stdout), (k * (tw + 4), 0))
    img.save(dst, quality=80)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="clips or folders of clips")
    ap.add_argument("--transcripts", required=True, help="folder with <clip>.json from Scribe")
    ap.add_argument("--transcribe", action="store_true", help="transcribe the clips that have no JSON yet")
    ap.add_argument("--language", default=os.environ.get("SCRIBE_LANGUAGE"), help="ISO 639 code for --transcribe; default: detect")
    ap.add_argument("--sheets", action="store_true", help="a sheet of 6 frames per clip")
    ap.add_argument("--out", required=True, help="the dossier file, e.g. work/dossier.md")
    a = ap.parse_args()

    clips = []
    for x in a.inputs:
        clips += sorted(f for f in glob.glob(os.path.join(x, "*")) if f.lower().endswith(EXT)) if os.path.isdir(x) else [x]
    os.makedirs(a.transcripts, exist_ok=True)
    folder = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(folder, exist_ok=True)
    lines = [f"# Dossier ({len(clips)} clips)", "",
             "Times in seconds of each clip. «repeats C0076 20.2» marks a sentence that starts like an earlier one in that clip",
             "and time (another attempt at the same line): pick the good one and ignore the others.", ""]
    missing, seen = [], {}
    for f in clips:
        name = os.path.splitext(os.path.basename(f))[0]
        info = probe(f)
        if not info:
            continue
        lines.append(f"## {name}  ({info['dur']:.1f} s, {info['w']}x{info['h']}, {info['fps']:g} fps{', sound' if info['sound'] else ', no sound'})")
        if a.sheets:
            os.makedirs(os.path.join(folder, "sheets"), exist_ok=True)
            sh = os.path.join(folder, "sheets", name + ".jpg")
            if os.path.exists(sh) or sheet(f, info, sh):
                lines.append(f"sheet: sheets/{name}.jpg")
        j = os.path.join(a.transcripts, name + ".json")
        d = None
        if os.path.exists(j):
            d = json.load(open(j, encoding="utf-8"))
        elif a.transcribe and info["sound"]:
            d, err = transcribe(f, a.language, events=True)
            if d:
                with open(j, "w", encoding="utf-8") as h:
                    json.dump(d, h, ensure_ascii=False)
        if not d:
            lines += ["(no transcript)" if info["sound"] else "(no sound)", ""]
            missing.append(name)
            continue
        ws = [w for w in d.get("words", []) if w.get("type") == "word"]
        prev = None
        for s in sentences(ws):
            if prev is not None and s[0]["start"] - prev > LONG:
                lines.append(f"   (pause {s[0]['start'] - prev:.1f} s)")
            k = key(s)
            rep = ""
            if len(s) >= 3 and k in seen:
                rep = f"  «repeats {seen[k][0]} {seen[k][1]:.1f}»"
            elif len(s) >= 3:
                seen[k] = (name, s[0]["start"])
            lines.append(f"[{s[0]['start']:.2f}-{s[-1]['end']:.2f}] {' '.join(w['text'] for w in s)}{rep}")
            prev = s[-1]["end"]
        lines.append("")
    lines += ["## Shot descriptions", "", "(one line per clip, filled in once after looking at the sheets: who, where, framing, what happens)", ""]
    with open(a.out, "w", encoding="utf-8") as h:
        h.write("\n".join(lines))
    print(a.out, f"{os.path.getsize(a.out) / 1024:.1f} KB,", len(clips), "clips", (f"| no transcript: {', '.join(missing)}" if missing else ""))


if __name__ == "__main__":
    main()
