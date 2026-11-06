"""cut_list.py, add_markers.py and dossier.py on synthetic transcripts, with ffmpeg and ffprobe replaced by fakes:
takes split at long pauses, forced in points, fixed framing, alternating punch-in, markers by segment and by word,
repeated attempts in the dossier.

    python3 tests/test_media_scripts.py        # needs numpy
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "davinci-resolve-agent", "scripts", "media"))


def word(text, start, end):
    return {"text": text, "start": start, "end": end, "type": "word"}


def main():
    os.chdir(tempfile.mkdtemp(prefix="dra-test-"))
    os.makedirs("transcripts")
    os.makedirs("media")
    for name in ("C0081.MP4", "C0083.mov"):
        open(os.path.join("media", name), "w").close()
    json.dump({"words": [word("Hello", 1.0, 1.4), {"text": " ", "type": "spacing", "start": 1.4, "end": 1.5}, word("there.", 1.5, 2.0),
                         word("Today", 4.0, 4.3), word("we", 4.35, 4.5), word("start", 4.55, 5.0)]}, open("transcripts/C0081.json", "w"))
    json.dump({"words": [word("Today", 0.5, 0.9), word("we", 0.95, 1.1), word("start.", 1.15, 1.6), word("Again", 2.4, 2.8)]},
              open("transcripts/C0083.json", "w"))
    plan = {"Lesson 01 v1": [["01a", "C0081", 0.9, 99], ["01b", "C0083", 0.4, 99, {"in_frame": 10, "post": 0.3}],
                             ["01c", "C0081", 3.9, 99, {"zoom": 1.1, "pan": 4, "tilt": 2}]]}
    json.dump(plan, open("plan.json", "w"))

    import cut_list
    cut_list.frames = lambda clip: 250
    cut_list.energy = lambda clip, lo, hi: [(f, -60.0 + (f % 7)) for f in range(int(lo * cut_list.FPS) + 1, int(hi * cut_list.FPS) + 1)]
    sys.argv = ["cut_list.py", "plan.json", "transcripts", "media", "cuts.json", "--fps", "25"]
    cut_list.main()
    t = json.load(open("cuts.json"))["Lesson 01 v1"]
    segs = t["segments"]
    assert [s["take"] for s in segs] == ["01a", "01a", "01b", "01c"], "the 2 s pause inside 01a must split it"
    assert segs[2]["in"] == 10, "in_frame forces the in point"
    assert segs[1]["zoom"] == 1.2 and segs[2]["zoom"] == 1.0 and segs[3]["zoom"] == 1.1 and segs[3]["pan"] == 4
    assert t["frames"] == sum(s["out"] - s["in"] for s in segs) and segs[1]["rec"] == segs[0]["out"] - segs[0]["in"]
    assert all(s["out"] > s["in"] for s in segs)
    assert cut_list.media("C0083").endswith("C0083.mov"), "media files are found by name, any extension"
    assert abs(cut_list.parse_fps("29.97") - 30000 / 1001) < 1e-9 and cut_list.parse_fps("25") == 25.0

    json.dump({"Lesson 01 v1": [{"color": "Blue", "name": "intro", "seg": 0, "plus": 3},
                                {"color": "Red", "name": "word", "clip": "C0083", "word": "again", "after": 2.0}]}, open("markers.json", "w"))
    import add_markers
    sys.argv = ["add_markers.py", "cuts.json", "markers.json", "transcripts", "--fps", "25"]
    add_markers.main()
    m = json.load(open("cuts.json"))["Lesson 01 v1"]["markers"]
    assert m[0]["frame"] == 3 and m[1]["frame"] == segs[2]["rec"] + round(2.4 * 25) - 10, m

    import dossier
    dossier.probe = lambda f: dict(dur=10.0, w=1920, h=1080, fps=25.0, sound=True)
    sys.argv = ["dossier.py", "media", "--transcripts", "transcripts", "--out", "work/dossier.md"]
    dossier.main()
    text = open("work/dossier.md", encoding="utf-8").read()
    assert "(pause 2.0 s)" in text and "«repeats C0081 4.0»" in text, text
    print("ok: media scripts")


if __name__ == "__main__":
    main()
