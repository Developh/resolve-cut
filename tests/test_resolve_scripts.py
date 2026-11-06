"""The scripts in scripts/resolve/ against the fake Resolve API: project, import, clips, timeline with punch-ins and
markers, frames, render start and status (tracks disabled and enabled again), swap media.

    python3 tests/test_resolve_scripts.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_resolve as fr  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="dra-test-")
    r = fr.run("project.py", {"name": "Demo", "width": 1920, "height": 1080, "fps": "25"})
    assert r["read_back"]["timelineFrameRate"] == "25", r

    for name in ("C0081.MP4", "C0083.MP4"):
        r = fr.run("assemble.py", {"phase": "import", "bin": "Raw", "media": "/raw", "files": [name]})
        assert r["imported"] == 1 and r["missing"] == [], r
    r = fr.run("assemble.py", {"phase": "import", "bin": "Raw", "media": "/raw", "files": ["C0081.MP4"]})
    assert r["imported"] == 0, "a clip already in the bin must not be imported again"
    r = fr.run("assemble.py", {"phase": "clips", "bin": "Raw", "clips": {"C0081": {"color": "Green", "note": "take 3"}, "C9999": {}}})
    assert r["failed"] == ["C9999"], r

    cuts = {"Lesson 01 v1": {
        "segments": [{"clip": "C0081", "in": 115, "out": 300, "rec": 0, "zoom": 1.0, "take": "01a", "text": "a"},
                     {"clip": "C0083", "in": 135, "out": 590, "rec": 185, "zoom": 1.2, "take": "01b", "text": "b"},
                     {"clip": "C0083", "in": 600, "out": 700, "rec": 640, "zoom": 1.1, "pan": 5, "tilt": -3, "take": "01c", "text": "c"}],
        "frames": 740, "markers": [{"frame": 10, "color": "Blue", "name": "note", "note": "check"}]}}
    cuts_path = os.path.join(tmp, "cuts.json")
    json.dump(cuts, open(cuts_path, "w"))
    r = fr.run("assemble.py", {"phase": "timeline", "bin": "Raw", "cuts": cuts_path, "timeline": "Lesson 01 v1",
                               "zoom": {"center": [0.45, 0.37]}, "voice_isolation": 50})
    assert r["placed"] == 3 and r["failures"] == [] and r["frames"] == r["expected"] == 740 and r["markers"] == 1, r
    timeline = fr.resolve.pm.project.current
    video = timeline.GetItemListInTrack("video", 1)
    assert video[0].props == {}, "zoom 1 gets no transform"
    assert video[1].props["Pan"] == round((0.5 - 0.45) * 0.2 * 1920, 1) and video[1].props["Tilt"] == round((0.37 - 0.5) * 0.2 * 1080, 1)
    assert video[2].props["Pan"] == 5.0 and video[2].props["Tilt"] == -3.0, "a fixed framing wins over the punch-in"
    r = fr.run("assemble.py", {"phase": "timeline", "bin": "Raw", "cuts": cuts_path, "timeline": "Lesson 01 v1"})
    assert "error" in r, "an existing timeline name must be refused"

    r = fr.run("frames.py", {"timeline": "Lesson 01 v1", "frames": [100, 500], "folder": os.path.join(tmp, "frames"), "max": 960})
    assert all(not v.startswith("failed") for v in r.values()), r

    r = fr.run("render.py", {"phase": "start", "timeline": "Lesson 01 v1", "folder": os.path.join(tmp, "out"), "name": "lesson-01",
                             "preset": "reel", "width": 1920, "height": 1080, "mark": [0, 739], "disable": [1]})
    assert r["preset"] == "reel-1440x2560-h264" and r["started"] and "preset_error" not in r, r
    imported = [c for c in fr.calls if c[0] == "import_preset"]
    assert imported and imported[-1][2], "the preset XML must be found next to render.py"
    settings = [c for c in fr.calls if c[0] == "settings"][-1][1]
    assert settings["MarkIn"] == 90000 and settings["MarkOut"] == 90739 and settings["FrameRate"] == 25.0, settings
    assert all(not i.enabled for i in video), "disable switches the track's clips off for the render"
    r = fr.run("render.py", {"phase": "status", "job": "job1"})
    assert len(r["enabled_again"]) == 3 and all(x[2] for x in r["enabled_again"]), r
    assert all(i.enabled for i in timeline.GetItemListInTrack("video", 1))
    r = fr.run("render.py", {"phase": "start", "timeline": "Nope", "folder": tmp, "name": "x"})
    assert "error" in r

    fr.resolve.pm.project.pool.root.subfolders[0].clips.append(fr.Clip("C0083-v2.mov"))
    r = fr.run("swap_media.py", {"timeline": "Lesson 01 v1", "track": 1, "swaps": [{"old": "C0083.MP4", "new": "C0083-v2.mov"}]})
    assert len(r["swapped"]) == 2 and all(not s["failed_properties"] for s in r["swapped"]), r
    print("ok: resolve scripts")


if __name__ == "__main__":
    main()
