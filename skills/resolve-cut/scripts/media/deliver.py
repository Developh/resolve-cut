#!/usr/bin/env python3
"""Deliver a video exported from Resolve: drop the timecode track (tmcd) and the metadata, put moov first, check the
result and copy it to its destination, comparing byte by byte.

    python3 deliver.py <export.mp4> <clean.mp4> [--no-editlist] [--copy "<folder or file>"]

- No re-encoding: ffmpeg -map 0:v:0 -map 0:a:0 -c copy -write_tmcd 0 -map_metadata -1 -movflags +faststart.
- --no-editlist (YouTube asks for MP4 without edit lists): adds -use_editlist 0; the sound can run up to about 21 ms
  early (the AAC priming delay is no longer compensated), less than a frame.
- Checks: only video and sound, the same frame count and colour tags as the export, moov before mdat.
- --copy: copies the clean file to a folder (or file) and compares the copy with cmp.
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys


def streams(f):
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", f], capture_output=True, text=True).stdout)["streams"]


def moov_first(f):
    size, order = os.path.getsize(f), []
    with open(f, "rb") as h:
        pos = 0
        while pos + 8 <= size and len(order) < 20:
            h.seek(pos)
            n, t = struct.unpack(">I4s", h.read(8))
            if n == 1:
                n = struct.unpack(">Q", h.read(8))[0]
            elif n == 0:
                n = size - pos
            order.append(t)
            pos += n
    return b"moov" in order and b"mdat" in order and order.index(b"moov") < order.index(b"mdat")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", help="the file Resolve rendered")
    ap.add_argument("clean", help="the delivery file to write")
    ap.add_argument("--copy", help="folder or file to copy the clean file to")
    ap.add_argument("--no-editlist", action="store_true", help="MP4 without edit lists (YouTube)")
    a = ap.parse_args()
    subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-y", "-filter_threads", "2", "-filter_complex_threads", "2",
                    "-threads", "2", "-i", a.export, "-map", "0:v:0", "-map", "0:a:0",
                    "-c", "copy", "-write_tmcd", "0", "-map_metadata", "-1", *(["-use_editlist", "0"] if a.no_editlist else []),
                    "-movflags", "+faststart", a.clean], check=True, stdin=subprocess.DEVNULL)
    src, new = streams(a.export), streams(a.clean)
    v0 = next(s for s in src if s["codec_type"] == "video")
    v1 = next(s for s in new if s["codec_type"] == "video")
    kinds = sorted(s["codec_type"] for s in new)
    errors = []
    if kinds != ["audio", "video"]:
        errors.append(f"streams: {kinds}")
    if v0.get("nb_frames") != v1.get("nb_frames"):
        errors.append(f"frames {v0.get('nb_frames')} → {v1.get('nb_frames')}")
    for k in ("color_primaries", "color_transfer", "color_space"):
        if v0.get(k) != v1.get(k):
            errors.append(f"{k}: {v0.get(k)} → {v1.get(k)}")
    if not moov_first(a.clean):
        errors.append("moov after mdat")
    if errors:
        sys.exit("ERROR: " + "; ".join(errors))
    print(f"clean   {a.clean}: video and sound, {v1.get('nb_frames')} frames, {v1.get('color_primaries')}, moov first")
    if a.copy:
        dst = os.path.join(a.copy, os.path.basename(a.clean)) if os.path.isdir(a.copy) else a.copy
        shutil.copyfile(a.clean, dst)
        if subprocess.run(["cmp", "-s", a.clean, dst]).returncode != 0:
            sys.exit(f"ERROR: the copy at {dst} is not identical")
        print(f"copied  {dst} (identical byte by byte)")


if __name__ == "__main__":
    main()
