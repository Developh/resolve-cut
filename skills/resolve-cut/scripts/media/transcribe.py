#!/usr/bin/env python3
"""Word-level transcripts with ElevenLabs Scribe, one JSON per media file.

    python3 transcribe.py <files or folders...> --out <folder> [--language por] [--model scribe_v2] [--force]

- Writes <out>/<file name without extension>.json with Scribe's response: "text" and "words" (text, start, end,
  type), in seconds of the file. dossier.py, cut_list.py, add_markers.py and inspect_range.py read these files.
- Needs ELEVENLABS_API_KEY, from the environment or from a .env file in the current folder.
- --language: ISO 639 code (por, eng, spa...). Without it, Scribe detects the language.
- Files that already have a transcript are skipped, unless --force.
- The sound goes to Scribe as 16 kHz mono FLAC, extracted with ffmpeg (one at a time, nice, 2 threads). The key is
  passed to curl through stdin, so it never shows up in the process list.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

MEDIA = (".mp4", ".mov", ".m4v", ".mxf", ".mkv", ".wav", ".mp3", ".m4a", ".flac", ".aif", ".aiff")
URL = "https://api.elevenlabs.io/v1/speech-to-text"


def load_dotenv(path=".env"):
    """KEY=value lines from ./.env fill variables the environment does not already have."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        name, _, value = line.strip().partition("=")
        name, value = name.strip(), value.strip().strip("\"'")
        if name and not name.startswith("#") and value:
            os.environ.setdefault(name, value)


load_dotenv()


def api_key():
    return os.environ.get("ELEVENLABS_API_KEY")


def extract(media, flac, start=None, duration=None):
    """Sound of `media` (or of [start, start + duration] seconds) as 16 kHz mono FLAC."""
    cut = (["-ss", f"{start:.3f}", "-t", f"{duration:.3f}"] if start is not None else [])
    r = subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-y", "-filter_threads", "2", "-filter_complex_threads", "2",
                        "-threads", "2", *cut, "-i", media, "-threads", "2", "-vn", "-ac", "1", "-ar", "16000", flac],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.returncode == 0 and os.path.exists(flac)


def scribe(flac, language=None, model="scribe_v2", events=False):
    """Sends a sound file to Scribe. Returns (response dict, None) or (None, error message)."""
    key = api_key()
    if not key:
        return None, "no ELEVENLABS_API_KEY (environment or ./.env)"
    form = ["-F", f"model_id={model}", "-F", "timestamps_granularity=word", "-F", f"tag_audio_events={'true' if events else 'false'}"]
    if language:
        form += ["-F", f"language_code={language}"]
    r = subprocess.run(["curl", "-s", "-X", "POST", URL, "-K", "-", *form, "-F", f"file=@{flac}"],
                       input=f'header = "xi-api-key: {key}"\n', capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return None, (r.stdout or r.stderr)[:300] or "no response"
    if "words" not in d:
        return None, json.dumps(d.get("detail", d))[:300]
    return d, None


def transcribe(media, language=None, model="scribe_v2", events=False, start=None, duration=None):
    """Transcribes a file (or a range of it). Word times are in seconds of the range."""
    with tempfile.TemporaryDirectory() as tmp:
        flac = os.path.join(tmp, "audio.flac")
        if not extract(media, flac, start, duration):
            return None, "ffmpeg could not extract the sound"
        return scribe(flac, language, model, events)


def words(d):
    return [w for w in d.get("words", []) if w.get("type") == "word"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="media files or folders")
    ap.add_argument("--out", required=True, help="folder for the JSON transcripts")
    ap.add_argument("--language", default=os.environ.get("SCRIBE_LANGUAGE"), help="ISO 639 code; default: detect")
    ap.add_argument("--model", default="scribe_v2")
    ap.add_argument("--events", action="store_true", help="tag audio events (laughter, claps)")
    ap.add_argument("--force", action="store_true", help="transcribe again files that already have a JSON")
    a = ap.parse_args()
    files = []
    for x in a.inputs:
        files += sorted(f for f in glob.glob(os.path.join(x, "*")) if f.lower().endswith(MEDIA)) if os.path.isdir(x) else [x]
    os.makedirs(a.out, exist_ok=True)
    failed = 0
    for f in files:
        dst = os.path.join(a.out, os.path.splitext(os.path.basename(f))[0] + ".json")
        if os.path.exists(dst) and not a.force:
            print(f"skip   {dst} (exists)")
            continue
        d, err = transcribe(f, a.language, a.model, a.events)
        if err:
            failed += 1
            print(f"FAILED {f}: {err}")
            continue
        with open(dst, "w", encoding="utf-8") as h:
            json.dump(d, h, ensure_ascii=False)
        print(f"ok     {dst} ({len(words(d))} words)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
