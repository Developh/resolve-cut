"""Assemble a talking-head video (one speaker, one camera) from a cut list in JSON, in phases.

    python3 run.py assemble.py '{"phase": "import", "bin": "Raw", "media": "/abs/raw", "files": ["C0081.MP4"]}'
    python3 run.py assemble.py '{"phase": "clips", "bin": "Raw", "clips": {"C0081": {"color": "Green", "note": "take 3"}}}'
    python3 run.py assemble.py '{"phase": "timeline", "bin": "Raw", "cuts": "/abs/cuts.json", "timeline": "Lesson 01 v1",
                                 "zoom": {"center": [0.45, 0.37]}, "voice_isolation": 50, "pause": 0}'

Runs inside Resolve: through run.py, or the MCP's run_script_unsafe (P = {...}, then exec of this file). Set the
project's frame rate and resolution first, with project.py.

cuts.json (what cut_list.py writes):
    {"<timeline>": {"segments": [{"clip", "in", "out", "rec", "zoom", "take", "text"}], "frames": N,
                    "markers": [{"frame", "color", "name", "note"}]}}
"in" and "out" are frames of the camera file (in inclusive, out exclusive, counted from the file's first frame);
"rec" is the frame on the timeline, counted from its start.

Phases:
- import: P["files"] (names inside P["media"]) into the bin P["bin"]; files already in the bin are skipped. Camera
  MP4/H.264 can go many at once (22 in one call measured). ProRes 4444, or any freshly rendered ProRes, one file per
  call: several in one ImportMedia call crashed Resolve 21.1.
- clips: P["clips"] = {"C0081": {"color": "Green", "note": "..."}} sets the clip colour and Comments in the media pool.
- timeline: a new timeline with the segments on V1/A1 (picture and sound linked). Segments whose zoom is not 1 get a
  punch-in that keeps the face, at P["zoom"]["center"] (fraction of the frame), in the same place on screen; a segment
  with "pan"/"tilt" keeps that fixed framing instead (timeline pixels, positive tilt goes up). Voice Isolation on the
  whole A1 track (P["voice_isolation"], 0 turns it off), then the markers. Refuses a timeline name that already
  exists: use v2, v3. P["pause"] waits that many seconds between segments, to watch the timeline fill on screen.
"""
if __name__ == "__main__" and "resolve" not in globals():
    import sys
    print(__doc__.strip())
    sys.exit(0)

import json
import os
import time

_as_pm = resolve.GetProjectManager()
_as_proj = _as_pm.GetCurrentProject()
_as_mp = _as_proj.GetMediaPool()
_as_phase = P["phase"]
_as_out = {"phase": _as_phase, "project": _as_proj.GetName()}


def _as_bin(name):
    root = _as_mp.GetRootFolder()
    for f in root.GetSubFolderList():
        if f.GetName() == name:
            return f
    return _as_mp.AddSubFolder(root, name)


def _as_by_name(folder):
    return {os.path.splitext(c.GetName())[0]: c for c in folder.GetClipList()}


if _as_phase == "import":
    _as_folder = _as_bin(P["bin"])
    _as_have = _as_by_name(_as_folder)
    _as_new = [os.path.join(P["media"], f) for f in P["files"] if os.path.splitext(f)[0] not in _as_have]
    if _as_new:
        _as_mp.SetCurrentFolder(_as_folder)
        _as_mp.ImportMedia(_as_new)   # a list of paths: the form with dicts returns None for MP4 on 21.1
        _as_mp.SetCurrentFolder(_as_mp.GetRootFolder())
    _as_now = _as_by_name(_as_folder)
    _as_out.update(requested=len(P["files"]), imported=len(_as_new), in_bin=len(_as_now),
                   missing=[f for f in P["files"] if os.path.splitext(f)[0] not in _as_now])
    _as_pm.SaveProject()

elif _as_phase == "clips":
    _as_clips = _as_by_name(_as_bin(P["bin"]))
    _as_done, _as_failed = [], []
    for _as_name, _as_c in P["clips"].items():
        _as_item = _as_clips.get(_as_name)
        if not _as_item:
            _as_failed.append(_as_name)
            continue
        _as_ok = _as_item.SetClipColor(_as_c["color"]) if _as_c.get("color") else True
        _as_ok = (_as_item.SetMetadata({"Comments": _as_c["note"]}) if _as_c.get("note") else True) and _as_ok
        (_as_done if _as_ok else _as_failed).append(_as_name)
    _as_out.update(done=len(_as_done), failed=_as_failed)
    _as_pm.SaveProject()

elif _as_phase == "timeline":
    _as_plan = json.load(open(P["cuts"], encoding="utf-8"))[P["timeline"]]
    _as_clips = _as_by_name(_as_bin(P["bin"]))
    _as_missing = sorted({s["clip"] for s in _as_plan["segments"]} - set(_as_clips))
    _as_names = [_as_proj.GetTimelineByIndex(i).GetName() for i in range(1, _as_proj.GetTimelineCount() + 1)]
    if _as_missing:
        _as_out["error"] = "not imported yet: " + ", ".join(_as_missing)
    elif P["timeline"] in _as_names:
        _as_out["error"] = "a timeline with this name already exists"
    else:
        _as_mp.SetCurrentFolder(_as_mp.GetRootFolder())
        _as_pause = float(P.get("pause", 0))
        if _as_pause:
            resolve.OpenPage("edit")
        _as_tl = _as_mp.CreateEmptyTimeline(P["timeline"])
        _as_proj.SetCurrentTimeline(_as_tl)
        _as_t0 = _as_tl.GetStartFrame()
        _as_w = int(_as_tl.GetSetting("timelineResolutionWidth"))
        _as_h = int(_as_tl.GetSetting("timelineResolutionHeight"))
        _as_cx, _as_cy = P.get("zoom", {}).get("center", [0.5, 0.5])
        _as_placed, _as_failures = 0, []
        for s in _as_plan["segments"]:
            _as_got = _as_mp.AppendToTimeline([{"mediaPoolItem": _as_clips[s["clip"]], "startFrame": s["in"], "endFrame": s["out"],
                                                "recordFrame": _as_t0 + s["rec"], "trackIndex": 1}]) or []
            _as_video = [i for i in _as_got if i.GetTrackTypeAndIndex()[0] == "video"]
            if not _as_video:
                _as_failures.append(f'{s["clip"]}@{s["rec"]}')
                continue
            _as_placed += 1
            if _as_pause:
                time.sleep(_as_pause)
            _as_z = float(s.get("zoom", 1))
            _as_v = _as_video[0]
            if "pan" in s or "tilt" in s:
                # fixed framing for this segment (e.g. matched on the background), in timeline pixels
                _as_v.SetProperty("ZoomX", _as_z); _as_v.SetProperty("ZoomY", _as_z)
                _as_v.SetProperty("Pan", float(s.get("pan", 0))); _as_v.SetProperty("Tilt", float(s.get("tilt", 0)))
            elif _as_z != 1:
                # zoom around the frame centre, then translate so the face (cx, cy) stays where it was on screen
                _as_v.SetProperty("ZoomX", _as_z); _as_v.SetProperty("ZoomY", _as_z)
                _as_v.SetProperty("Pan", round((0.5 - _as_cx) * (_as_z - 1) * _as_w, 1))
                _as_v.SetProperty("Tilt", round((_as_cy - 0.5) * (_as_z - 1) * _as_h, 1))
        _as_tl.SetTrackName("video", 1, "Camera")
        _as_tl.SetTrackName("audio", 1, "Voice")
        _as_voice = int(P.get("voice_isolation", 0))
        _as_iso = _as_tl.SetVoiceIsolationState(1, {"isEnabled": _as_voice > 0, "amount": _as_voice}) if _as_voice else None
        _as_marks = 0
        for m in _as_plan.get("markers", []):
            _as_marks += 1 if _as_tl.AddMarker(m["frame"], m["color"], m["name"], m.get("note", ""), m.get("duration", 1)) else 0
        _as_out.update(timeline=_as_tl.GetName(), segments=len(_as_plan["segments"]), placed=_as_placed, failures=_as_failures,
                       v1=len(_as_tl.GetItemListInTrack("video", 1) or []), a1=len(_as_tl.GetItemListInTrack("audio", 1) or []),
                       frames=_as_tl.GetEndFrame() - _as_t0, expected=_as_plan["frames"], voice_isolation=_as_iso, markers=_as_marks)
        _as_pm.SaveProject()

else:
    _as_out["error"] = f"unknown phase {_as_phase!r}: use import, clips or timeline"

result = _as_out
