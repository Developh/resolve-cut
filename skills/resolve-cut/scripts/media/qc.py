#!/usr/bin/env python3
"""Check an exported video in one command: the numbers first, then a single sheet of frames.

    python3 qc.py <video.mp4> [--frames 347,596,671] [--ref other.mp4] [--expected 914] [--strip 12]
                  [--no-guides] [--transcribe] [--language por] [--sheet /abs/sheet.jpg] [--simulate]

Text report:
- streams (video, sound and anything extra, such as a tmcd timecode track), codec, profile, resolution, fps,
  frames, bitrate, colour tags;
- moov before mdat (faststart), and an edit list (elst atom) if there is one: YouTube asks for MP4 without them;
- sound: integrated LUFS and true peak (ebur128), MD5 of the decoded audio;
- black first frame (blackdetect over the first 0.2 s): it is what a feed shows before the video starts;
- frozen frames (freezedetect) and irregular timestamps (dropped or doubled frames);
- with --ref: whether the audio is identical (MD5) and the PSNR at each of --frames;
- with --transcribe: Scribe's text with the time of every word (ELEVENLABS_API_KEY). Read it for repeated or cut
  words at the cuts ("decide, decide"): it is the defect a cut list makes most often;
- a 25 fps 9:16 warning: Instagram serves 25 fps Reels at 25 (measured on served files, November 2026), but
  ProMotion iPhones have no 25 or 50 Hz mode and show it with uneven cadence. Do not convert footage shot at 25;
  shoot the next ones at 29.97 with a 1/50 shutter under 50 Hz lights;
- with --simulate: re-encodes like Instagram's basic delivery to accounts with few views (H.264 720x1280 at about
  1.35 Mbps), measures VMAF NEG against the master, both at 1080x1920, and lists the 5 worst seconds to review by
  eye. Needs ffmpeg built with libvmaf. About 30 s for a 36 s Reel.
Sheet: one image up to 1200 px wide, with a strip of --strip consecutive frames starting 2 before each of --frames.
A 9:16 sheet carries Instagram's UI zones measured on an iPhone (header at y 240 to 300, content from y 360, side
margins at x 110 and 1330, in 1440x2560); --no-guides removes them.
One ffmpeg at a time, with nice and 2 threads.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import tempfile

from transcribe import transcribe, words


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


def ff(*a):
    """ffmpeg at low priority with 2 filter threads. This -threads 2 limits only the first input: repeat it before every
    other -i and before the output's encoder."""
    return ["nice", "-n", "15", "ffmpeg", "-hide_banner", "-filter_threads", "2", "-filter_complex_threads", "2", "-threads", "2", *a]


def probe(f):
    return json.loads(run(["nice", "-n", "15", "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", f]).stdout)


def atoms(f):
    """Order of the MP4/MOV top-level atoms (to see if moov comes before mdat)."""
    out, size = [], os.path.getsize(f)
    with open(f, "rb") as h:
        pos = 0
        while pos + 8 <= size and len(out) < 20:
            h.seek(pos)
            n, t = struct.unpack(">I4s", h.read(8))
            if n == 1:
                n = struct.unpack(">Q", h.read(8))[0]
            elif n == 0:
                n = size - pos
            out.append(t.decode("latin-1"))
            pos += n
    return out


def has_editlist(f):
    """Looks for an elst atom inside moov (reads only moov, which is small)."""
    size = os.path.getsize(f)
    with open(f, "rb") as h:
        pos = 0
        while pos + 8 <= size:
            h.seek(pos)
            n, t = struct.unpack(">I4s", h.read(8))
            head = 8
            if n == 1:
                n = struct.unpack(">Q", h.read(8))[0]
                head = 16
            elif n == 0:
                n = size - pos
            if t == b"moov":
                h.seek(pos + head)
                return b"elst" in h.read(min(n - head, 64 * 1024 * 1024))
            pos += n
    return False


def loudness(f):
    e = run(ff("-nostats", "-i", f, "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-")).stderr
    i = re.findall(r"^\s+I:\s+(-?[\d.]+) LUFS", e, re.M)
    p = re.findall(r"^\s+Peak:\s+(-?[\d.]+) dBFS", e, re.M)
    return (float(i[-1]) if i else None), (float(p[-1]) if p else None)


def audio_md5(f):
    o = run(ff("-v", "error", "-i", f, "-map", "0:a:0", "-threads", "2", "-f", "md5", "-")).stdout.strip()
    return o.split("=")[-1] if o else None


def frozen(f):
    # hardware decoding (VideoToolbox on macOS) at full size, ~20 % faster; software if it fails
    cmd = lambda hw: ff("-nostats", *(["-hwaccel", "videotoolbox"] if hw else []), "-i", f, "-map", "0:v:0",
                        "-vf", "freezedetect=n=0.0008:d=0.2", "-f", "null", "-")
    r = run(cmd(True))
    e = r.stderr if r.returncode == 0 else run(cmd(False)).stderr
    start = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", e)]
    dur = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", e)]
    return list(zip(start, dur + [None] * (len(start) - len(dur))))


def irregular_times(f, fps):
    # packet timestamps, no decoding: the same as the frames', 0.1 s instead of 10 s for a 36 s Reel
    o = run(["nice", "-n", "15", "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time", "-of", "csv=p=0", f]).stdout
    ts = sorted(float(x.split(",")[0]) for x in o.split() if x.split(",")[0].strip())
    step = 1 / fps
    return [round(b, 3) for a, b in zip(ts, ts[1:]) if abs((b - a) - step) > step * 0.5]


def psnr(a, b, fr, fps):
    t = f"{fr / fps:.4f}"
    e = run(ff("-nostats", "-ss", t, "-i", a, "-threads", "2", "-ss", t, "-i", b, "-frames:v", "1", "-lavfi", "psnr", "-f", "null", "-")).stderr
    m = re.findall(r"average:([\d.inf]+)", e)
    return m[-1] if m else "?"


def sheet(f, frames, fps, w, h, strip, guides, dst):
    from PIL import Image
    strip_w = 1200
    tw = strip_w // strip
    th = round(tw * h / w)
    boxes = []
    if guides and abs(w / h - 9 / 16) < 0.01:
        k = w / 1440   # zones measured at 1440x2560
        color, g = "red@0.85", max(2, round(4 * k))
        for y in (240, 300, 360):
            boxes.append(f"drawbox=x=0:y={round(y * k)}:w=iw:h={g}:color={color}:t=fill")
        for x in (110, 1330):
            boxes.append(f"drawbox=x={round(x * k)}:y=0:w={g}:h=ih:color={color}:t=fill")
    strips = []
    with tempfile.TemporaryDirectory() as tmp:
        for fr in frames:
            first = max(0, fr - 2)
            p = os.path.join(tmp, f"{fr:06d}.jpg")
            vf = ",".join([f"trim=end_frame={strip}", *boxes, f"scale={tw}:{th}", f"tile={strip}x1:padding=2:color=white"])
            run(ff("-v", "error", "-y", "-ss", f"{first / fps:.4f}", "-i", f, "-threads", "2", "-vf", vf, "-frames:v", "1", p))
            if os.path.exists(p):
                strips.append(Image.open(p).convert("RGB"))
        if not strips:
            return None
        out = Image.new("RGB", (max(s.width for s in strips), sum(s.height for s in strips)), (255, 255, 255))
        y = 0
        for s in strips:
            out.paste(s, (0, y))
            y += s.height
        out.save(dst, quality=82)
    return dst


def black_start(f):
    e = run(ff("-nostats", "-t", "0.2", "-i", f, "-map", "0:v:0", "-vf", "blackdetect=d=0.04:pix_th=0.10", "-f", "null", "-")).stderr
    return bool(re.search(r"black_start:0(\.0+)?\b", e))


def simulate(f, w, h):
    """Instagram's basic delivery, simulated and scored with VMAF NEG at 1080x1920 (or 1920x1080): mean, minimum,
    5 worst seconds."""
    target = (720, 1280) if h >= w else (1280, 720)
    ref = (1080, 1920) if h >= w else (1920, 1080)
    with tempfile.TemporaryDirectory() as tmp:
        sim, log = os.path.join(tmp, "sim.mp4"), os.path.join(tmp, "vmaf.json")
        run(ff("-v", "error", "-y", "-i", f, "-map", "0:v:0", "-vf", f"scale={target[0]}:{target[1]}:flags=bicubic",
               "-threads", "2", "-c:v", "libx264", "-preset", "medium", "-b:v", "1350k", "-maxrate", "1600k", "-bufsize", "2700k",
               "-pix_fmt", "yuv420p", sim))
        model = "version=vmaf_v0.6.1neg"
        lavfi = (f"[0:v]scale={ref[0]}:{ref[1]}:flags=bicubic,setpts=PTS-STARTPTS[d];[1:v]scale={ref[0]}:{ref[1]}:flags=bicubic,setpts=PTS-STARTPTS[r];"
                 f"[d][r]libvmaf=model='{model}':n_threads=2:log_fmt=json:log_path={log}")
        run(ff("-v", "error", "-i", sim, "-threads", "2", "-i", f, "-lavfi", lavfi, "-f", "null", "-"))
        if not os.path.exists(log):
            return None
        fr = json.load(open(log))["frames"]
    sc = [x["metrics"]["vmaf"] for x in fr]
    if not sc:
        return None
    fps = len(sc) / max(1e-6, float(probe(f)["format"]["duration"]))
    per_s = {}
    for k, v in enumerate(sc):
        per_s.setdefault(int(k / fps), []).append(v)
    worst = sorted(((sum(v) / len(v), s_) for s_, v in per_s.items()))[:5]
    return sum(sc) / len(sc), min(sc), [(s_, round(m, 1)) for m, s_ in worst]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--frames", default="", help="frame numbers for the sheet (and PSNR with --ref), e.g. 347,596")
    ap.add_argument("--ref", help="previous approved version to compare against")
    ap.add_argument("--expected", type=int, help="expected number of frames")
    ap.add_argument("--strip", type=int, default=12, help="consecutive frames per strip in the sheet")
    ap.add_argument("--no-guides", action="store_true", help="no Instagram zones on a 9:16 sheet")
    ap.add_argument("--transcribe", action="store_true", help="transcribe the final mix with Scribe")
    ap.add_argument("--language", default=os.environ.get("SCRIBE_LANGUAGE"), help="ISO 639 code; default: detect")
    ap.add_argument("--sheet", help="where to write the sheet (default: next to the video, -qc.jpg)")
    ap.add_argument("--simulate", action="store_true", help="simulate Instagram's basic delivery and score it with VMAF")
    a = ap.parse_args()
    f = a.video
    s = probe(f)
    vs = [x for x in s["streams"] if x["codec_type"] == "video"]
    aus = [x for x in s["streams"] if x["codec_type"] == "audio"]
    extra = [f'{x["codec_type"]}:{x.get("codec_tag_string") or x.get("codec_name")}' for x in s["streams"] if x["codec_type"] not in ("video", "audio")]
    if not vs:
        print(f"file       {f}\nstreams    NO VIDEO STREAM ({len(aus)} audio): render again (load a preset before the settings)")
        raise SystemExit(1)
    v = vs[0]
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    fps = num / den
    nf = int(v.get("nb_frames") or 0)
    dur = float(s["format"]["duration"])
    print(f"file       {f} ({os.path.getsize(f) / 1e6:.1f} MB)")
    print(f"streams    {len(vs)} video, {len(aus)} audio" + (f", extra: {', '.join(extra)}" if extra else ", nothing extra"))
    print(f"video      {v['codec_name']} {v.get('profile', '')}, {v['width']}x{v['height']}, {fps:g} fps, {nf} frames"
          + (f" (expected {a.expected}: {'ok' if nf == a.expected else 'DIFFERENT'})" if a.expected else "")
          + f", {int(v.get('bit_rate', 0)) / 1e6:.2f} Mbps, {v.get('pix_fmt')}")
    print(f"colour     {v.get('color_primaries', '?')}/{v.get('color_transfer', '?')}/{v.get('color_space', '?')}")
    if v["height"] > v["width"] and abs(fps - 25) < 0.01:
        print("warning    25 fps in 9:16: Instagram serves it at 25, but ProMotion iPhones show it unevenly; do not convert, shoot the next ones at 29.97 (1/50)")
    at = atoms(f)
    if "moov" in at and "mdat" in at:
        print(f"faststart  {'yes (moov before mdat)' if at.index('moov') < at.index('mdat') else 'NO (moov after mdat)'}")
    if has_editlist(f):
        print("edit list  YES (elst atom): YouTube asks for MP4 without edit lists; remux with deliver.py --no-editlist")
    print(f"duration   {dur:.3f} s")
    if aus:
        lufs, peak = loudness(f)
        m = audio_md5(f)
        print(f"sound      {aus[0]['codec_name']} {aus[0].get('sample_rate')} Hz, {lufs} LUFS, true peak {peak} dBTP, MD5 {m}")
        if a.ref:
            print(f"sound ref  {'identical' if audio_md5(a.ref) == m else 'DIFFERENT'} to {os.path.basename(a.ref)}")
    print("1st frame  " + ("BLACK (the feed shows it before the video starts)" if black_start(f) else "picture"))
    fz = frozen(f)
    print("frozen     " + ("none" if not fz else "; ".join(f"{i:.2f} s ({(d or 0) * fps:.0f} frames)" for i, d in fz)))
    irr = irregular_times(f, fps)
    print("timing     " + ("regular" if not irr else f"{len(irr)} jumps: {irr[:10]}"))
    frames = [int(x) for x in a.frames.split(",") if x.strip()]
    if a.ref and frames:
        print("psnr ref   " + ", ".join(f"{fr}: {psnr(a.ref, f, fr, fps)}" for fr in frames))
    if frames:
        dst = a.sheet or os.path.splitext(f)[0] + "-qc.jpg"
        print(f"sheet      {sheet(f, frames, fps, v['width'], v['height'], a.strip, not a.no_guides, dst)}")
    if a.simulate:
        r = simulate(f, v["width"], v["height"])
        print("instagram  " + ("simulation failed (ffmpeg with libvmaf?)" if not r else
              f"VMAF NEG {r[0]:.1f} (minimum {r[1]:.1f}) on the simulated basic delivery (720p, 1.35 Mbps); worst seconds: "
              + ", ".join(f"{s_} s ({m})" for s_, m in r[2])))
    if a.transcribe:
        d, err = transcribe(f, a.language)
        if err:
            print("text       " + err)
        else:
            print("text       " + d.get("text", ""))
            print("words      " + " ".join(f"{w['text']}@{round(w['start'], 2)}" for w in words(d)))


if __name__ == "__main__":
    main()
