#!/usr/bin/env python3
"""Final loudness of a video (or a sound file) without loudnorm: one linear gain plus a limiter, measuring the true
peak until both targets hold.

    python3 loudness.py <input> <output> [--target -14] [--peak -1.5] [--aac 256]

- Reels and social: -14 LUFS, true peak up to -1.5 dBTP (the defaults). Lessons and courses: --target -16 --peak -1.
- Why not loudnorm: in one pass it is dynamic (it changes the approved mix), and in two passes it silently falls back
  to dynamic when the linear gain would push the peak over the limit. Here the gain is the same across the whole
  file and only the peaks go through the limiter; each pass is measured with ebur128 (true peak) on the final AAC,
  up to 5 passes, correcting the gain and the limiter ceiling.
- The video is copied, not re-encoded (-c:v copy). The output has faststart and no timecode track; finish the
  delivery with deliver.py.
One ffmpeg at a time, with nice and 2 threads.
"""
import argparse
import math
import os
import re
import subprocess
import sys


def measure(f):
    e = subprocess.run(["nice", "-n", "15", "ffmpeg", "-hide_banner", "-nostats", "-threads", "2", "-i", f, "-map", "0:a:0",
                        "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True, stdin=subprocess.DEVNULL).stderr
    i = re.findall(r"^\s+I:\s+(-?[\d.]+) LUFS", e, re.M)
    p = re.findall(r"^\s+Peak:\s+(-?[\d.]+) dBFS", e, re.M)
    if not i or not p:
        sys.exit(f"could not measure the sound of {f}")
    return float(i[-1]), float(p[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--target", type=float, default=-14.0, help="integrated loudness, LUFS")
    ap.add_argument("--peak", type=float, default=-1.5, help="maximum true peak, dBTP")
    ap.add_argument("--aac", type=int, default=256, help="AAC bitrate, kb/s")
    a = ap.parse_args()

    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", a.input],
                             capture_output=True, text=True).stdout
    has_video = "video" in streams
    vcodec = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", a.input],
                            capture_output=True, text=True).stdout.strip()
    if has_video and vcodec == "prores" and a.output.lower().endswith(".mp4"):
        sys.exit("ProRes does not go into an MP4 without re-encoding: write a .mov, or encode the H.264 first")
    tmp = a.output + ".writing" + os.path.splitext(a.output)[1]
    i0, p0 = measure(a.input)
    gain, ceiling = a.target - i0, 10 ** ((a.peak - 0.3) / 20)
    print(f"input: {i0} LUFS, true peak {p0} dBTP")
    for n in range(1, 6):
        cmd = ["nice", "-n", "15", "ffmpeg", "-v", "error", "-y", "-threads", "2", "-i", a.input]
        cmd += ["-map", "0:v:0", "-c:v", "copy"] if has_video else []
        cmd += ["-map", "0:a:0", "-af", f"volume={gain:.2f}dB,alimiter=limit={ceiling:.4f}:attack=2:release=60:level=false,aresample=48000",
                "-c:a", "aac", "-b:a", f"{a.aac}k", "-write_tmcd", "0", "-map_metadata", "-1", "-movflags", "+faststart", tmp]
        subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
        i, p = measure(tmp)
        print(f"pass {n}: gain {gain:+.2f} dB, ceiling {20 * math.log10(ceiling):.2f} dBFS → {i} LUFS, true peak {p} dBTP")
        if abs(i - a.target) <= 0.3 and p <= a.peak:
            break
        gain += a.target - i
        if p > a.peak:
            ceiling *= 10 ** ((a.peak - 0.2 - p) / 20)
    else:
        os.remove(tmp)
        sys.exit("did not reach the targets in 5 passes: check the mix (peaks far above the average?)")
    os.replace(tmp, a.output)
    print("ok", a.output)


if __name__ == "__main__":
    main()
