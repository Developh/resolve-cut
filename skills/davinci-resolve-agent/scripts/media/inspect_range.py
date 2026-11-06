#!/usr/bin/env python3
"""A range of a video in one image: a strip of frames, the waveform and the words at the time each one starts.
To decide a cut, check a caption or look at a defect without asking for loose frames or whole transcripts.

    python3 inspect_range.py <video> <t0> <t1> [--words transcript.json] [--offset 0] [--frames 8]
                             [--transcribe] [--language por] [--out /abs/range.png]

- t0 and t1 in seconds of the video (12.4) or in frames with f (f310).
- --words: Scribe JSON (words with start, end, type) timed on the same file; --offset adds seconds to its times (the
  transcript of a clip that starts elsewhere on the timeline).
- --transcribe: without a JSON, transcribes only the range with Scribe (ELEVENLABS_API_KEY).
- The image shows, top to bottom: the frames with their time and frame number, the waveform with a tick every
  0.5 s, and the words where they start, on alternating rows so they do not overlap.
- The image goes to the current folder by default, never next to the video (raw footage folders stay untouched).
- Font: INSPECT_FONT / INSPECT_FONT_BOLD (paths to .ttf), else Arial or DejaVu Sans if present, else Pillow's own.
Two ffmpeg calls (raw frames through a pipe, then sound as PCM), one at a time, with nice and 2 threads.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from transcribe import transcribe, words

WIDTH = 1600
FONTS = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:\\Windows\\Fonts\\arial.ttf"]
FONTS_BOLD = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"]


def font(env, candidates, size):
    for p in [os.environ.get(env)] + candidates:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:   # Pillow < 10.1
        return ImageFont.load_default()


def probe(f):
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", f], capture_output=True, text=True).stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    n, q = v["r_frame_rate"].split("/")
    return int(v["width"]), int(v["height"]), float(n) / float(q), any(s["codec_type"] == "audio" for s in d["streams"])


def seconds(x, fps):
    return int(x[1:]) / fps if x.startswith("f") else float(x)


def ff(*a, **kw):
    return subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-threads", "2", *a], capture_output=True, stdin=subprocess.DEVNULL, **kw)


def grab_frames(f, t0, t1, n, tw, th, fps):
    dur = t1 - t0
    ts = [t0 + dur * (k + 0.5) / n for k in range(n)]
    base = max(0, t0 - 0.5)
    select = "+".join(f"eq(n\\,{round((t - base) * fps)})" for t in ts)
    # one ffmpeg from t0: select by frame number (exact), raw RGB out
    r = ff("-ss", f"{base:.3f}", "-i", f, "-t", f"{dur + 1:.3f}",
           "-vf", f"setpts=PTS-STARTPTS,select='{select}',scale={tw}:{th}:flags=area", "-vsync", "0",
           "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-")
    buf = np.frombuffer(r.stdout, np.uint8)
    k = len(buf) // (tw * th * 3)
    return ts[:k], buf[:k * tw * th * 3].reshape(k, th, tw, 3)


def waveform(f, t0, t1, width):
    r = ff("-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", f, "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "s16le", "-")
    a = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
    if not len(a):
        return None
    cols = np.array_split(a, width)
    return np.array([[c.min(), c.max()] if len(c) else [0, 0] for c in cols])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("t0", help="start, in seconds (12.4) or frames (f310)")
    ap.add_argument("t1", help="end, in seconds or frames")
    ap.add_argument("--words", help="Scribe JSON of the same file")
    ap.add_argument("--offset", type=float, default=0.0, help="seconds added to the JSON's times")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--transcribe", action="store_true", help="transcribe just this range")
    ap.add_argument("--language", default=os.environ.get("SCRIBE_LANGUAGE"), help="ISO 639 code; default: detect")
    ap.add_argument("--out", help="PNG to write (default: ./<video>-<t0>-<t1>.png)")
    a = ap.parse_args()

    W, H, fps, has_sound = probe(a.video)
    t0, t1 = seconds(a.t0, fps), seconds(a.t1, fps)
    if t1 <= t0:
        sys.exit("t1 must be after t0")
    n, gap = a.frames, 6
    tw = (WIDTH - gap * (n - 1)) // n
    th = round(tw * H / W) // 2 * 2
    ts, fr = grab_frames(a.video, t0, t1, n, tw, th, fps)

    ws = []
    if a.words:
        ws = [dict(w, start=w["start"] + a.offset, end=w["end"] + a.offset) for w in json.load(open(a.words, encoding="utf-8"))["words"]
              if w.get("type") == "word"]
    elif a.transcribe and has_sound:
        d, err = transcribe(a.video, a.language, start=t0, duration=t1 - t0)
        if err:
            sys.exit(err)
        ws = [dict(w, start=w["start"] + t0, end=w["end"] + t0) for w in words(d)]
    ws = [w for w in ws if w["end"] > t0 and w["start"] < t1]

    f_n, f_b = font("INSPECT_FONT", FONTS, 22), font("INSPECT_FONT_BOLD", FONTS_BOLD, 24)
    head, wave_h, words_h = 40, 150, (110 if ws else 0)
    img = Image.new("RGB", (WIDTH, head + th + 44 + wave_h + words_h + 20), (24, 24, 24))
    d = ImageDraw.Draw(img)
    d.text((12, 8), f"{os.path.basename(a.video)}   {t0:.2f} to {t1:.2f} s   (frames {round(t0 * fps)} to {round(t1 * fps)}, {fps:g} fps)",
           font=f_b, fill=(240, 240, 240))
    for k, (t, im) in enumerate(zip(ts, fr)):
        x = k * (tw + gap)
        img.paste(Image.fromarray(im), (x, head))
        d.text((x + 4, head + th + 6), f"{t:.2f} s  f{round(t * fps)}", font=f_n, fill=(200, 200, 200))
    y0 = head + th + 44
    X = lambda t: int((t - t0) / (t1 - t0) * (WIDTH - 1))
    if has_sound:
        o = waveform(a.video, t0, t1, WIDTH)
        if o is not None:
            mid = y0 + wave_h // 2
            for x, (lo, hi) in enumerate(o):
                d.line((x, mid - hi * wave_h / 2, x, mid - lo * wave_h / 2), fill=(120, 200, 255))
    step = 0.5 if t1 - t0 <= 12 else 1.0
    t = (int(t0 / step) + 1) * step
    while t < t1:
        d.line((X(t), y0, X(t), y0 + wave_h), fill=(70, 70, 70))
        d.text((X(t) + 3, y0 + 2), f"{t:g}", font=f_n, fill=(150, 150, 150))
        t += step
    for k, w in enumerate(ws):
        x = X(max(t0, w["start"]))
        y = y0 + wave_h + 8 + (k % 3) * 34
        xt = min(x + 3, WIDTH - 4 - d.textlength(w["text"], font=f_b))   # a word at the end of the range stays inside
        d.line((x, y0, x, y), fill=(255, 210, 90))
        d.text((xt, y), w["text"], font=f_b, fill=(255, 210, 90))
    out = a.out or os.path.join(os.getcwd(), os.path.splitext(os.path.basename(a.video))[0] + f"-{t0:.2f}-{t1:.2f}.png")
    img.save(out)
    print(out)
    print(" ".join(f"[{w['start']:.2f}] {w['text']}" for w in ws) if ws else ("no words" if has_sound else "no sound"))


if __name__ == "__main__":
    main()
