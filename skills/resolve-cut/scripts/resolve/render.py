"""Render a timeline with a preset in two calls: "start" and "status".

    python3 run.py render.py '{"phase": "start", "timeline": "Lesson 01 v1", "folder": "/abs/out", "name": "lesson-01",
                               "preset": "reel", "width": 1920, "height": 1080, "mark": [0, 2752]}'
    python3 run.py render.py '{"phase": "start", "timeline": "Lesson 01 v1", "folder": "/abs/out", "name": "voice-only",
                               "format": "mov", "codec": "ProRes422HQ", "width": 3840, "height": 2160, "audio": false,
                               "mark": [0, 2752], "disable": [2]}'
    python3 run.py render.py '{"phase": "status", "job": "<id returned by start>"}'

Runs inside Resolve: through run.py, or the MCP's run_script_unsafe (P = {...}, then exec of this file; set
__file__ to this file's path first, or pass "presets" with the folder of the XML presets).

- start: opens the timeline on the Edit page, applies the settings, adds the job and starts it. StartRendering is the
  last call to Resolve in the script: everything after it returns None until the render ends. Poll with "status"
  every few seconds until JobStatus is Complete, then check the file with qc.py.
- mark: [first, last] frame counted from the start of the timeline, both included (a 2753-frame timeline is
  [0, 2752]). Always pass it: sound tails make the timeline longer than the picture, and with SelectAllFrames
  StartRendering sometimes returns False.
- preset: "reel" (MP4 H.264 1440x2560, quality ceiling 27300 kb/s, High profile, AAC, Rec.709 tags, faststart) or
  "master4k" (MOV ProRes 422 HQ 3840x2160, 24-bit PCM). Both carry "Force sizing to highest quality", which is not a
  SetRenderSettings key but travels inside a preset. The preset is imported from presets/ when Resolve does not have
  it (Resolve names an imported preset after its file). width/height and the other keys override the preset. The
  render always uses the timeline's frame rate, never the preset's.
- quality: H.264 ceiling in kb/s, not an average: 27300 gave about 20.7 Mbps at 1440x2560.
- disable: video tracks whose clips are switched off for this render only (export the talking head "without
  graphics"). SetClipEnabled only works on the open timeline, which is why "start" opens it. The disabled clips are
  written to <folder>/<name>.disabled.json, and "status" switches them back on when the job is complete.
- Always confirm with ffprobe (qc.py) that the file has a video stream: an H.264 job added right after an
  audio-only job once came out without video. Loading a preset before SetRenderSettings avoids it.
"""
if __name__ == "__main__" and "resolve" not in globals():
    import sys
    print(__doc__.strip())
    sys.exit(0)

import json as _rn_json
import os as _rn_os

# Resolve names an imported preset after its file, so preset name = file name without .xml
_RN_PRESETS = {"reel": "reel-1440x2560-h264", "master4k": "master-3840x2160-prores422hq"}


def _rn_presets_dir():
    if P.get("presets"):
        return P["presets"]
    if "__file__" in globals():
        return _rn_os.path.join(_rn_os.path.dirname(_rn_os.path.abspath(__file__)), "presets")
    return None


def _rn_timeline(name):
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t.GetName() == name:
            return t


if P["phase"] == "start":
    _rn_t = _rn_timeline(P["timeline"])
    if not _rn_t:
        result = {"error": f"no timeline named {P['timeline']!r}"}
    else:
        project.SetCurrentTimeline(_rn_t)
        resolve.OpenPage("edit")
        _rn_first = _rn_t.GetStartFrame()
        _rn_off = []
        for k in P.get("disable", []):
            for it in _rn_t.GetItemListInTrack("video", k) or []:
                if it.GetClipEnabled() and it.SetClipEnabled(False):
                    _rn_off.append([k, it.GetStart()])
        _rn_os.makedirs(P["folder"], exist_ok=True)
        _rn_state = _rn_os.path.join(P["folder"], P["name"] + ".disabled.json")
        with open(_rn_state, "w") as _rn_f:
            _rn_json.dump({"timeline": P["timeline"], "disabled": _rn_off}, _rn_f)
        _rn_preset, _rn_preset_error = None, None
        if P.get("preset"):
            _rn_preset = _RN_PRESETS[P["preset"]]
            if _rn_preset not in (project.GetRenderPresetList() or []):
                _rn_xml = _rn_os.path.join(_rn_presets_dir() or "", _rn_preset + ".xml")
                if _rn_os.path.exists(_rn_xml):
                    resolve.ImportRenderPreset(_rn_xml)
                else:
                    _rn_preset_error = f"preset file not found: {_rn_xml} (pass P['presets'] or set __file__)"
            _rn_preset = _rn_preset if project.LoadRenderPreset(_rn_preset) else None
        if not _rn_preset or P.get("format"):
            project.SetCurrentRenderFormatAndCodec(P.get("format", "mp4"), P.get("codec", "H264"))
        _rn_set = {"SelectAllFrames": False, "TargetDir": P["folder"], "CustomName": P["name"], "ExportVideo": True,
                   # presets store a fixed RecordFPS: without this, a 29.97 timeline would come out converted
                   "FrameRate": float(_rn_t.GetSetting("timelineFrameRate"))}
        if "audio" in P or not _rn_preset:
            _rn_set["ExportAudio"] = P.get("audio", True)
        if P.get("mark"):
            _rn_set.update({"MarkIn": _rn_first + P["mark"][0], "MarkOut": _rn_first + P["mark"][1]})
        if P.get("width"):
            _rn_set.update({"FormatWidth": P["width"], "FormatHeight": P["height"]})
        if P.get("quality") and P.get("codec", "H264").startswith("H26"):
            _rn_set["VideoQuality"] = P["quality"]
        if not _rn_preset and P.get("audio", True) and P.get("format", "mp4") == "mp4":
            _rn_set.update({"AudioCodec": "aac", "AudioSampleRate": 48000})
        _rn_ok = project.SetRenderSettings(_rn_set)
        _rn_job = project.AddRenderJob()
        resolve.GetProjectManager().SaveProject()
        result = {"preset": _rn_preset, "settings_applied": _rn_ok, "job": _rn_job, "disabled": _rn_off,
                  "file": _rn_os.path.join(P["folder"], P["name"])}
        if _rn_preset_error:
            result["preset_error"] = _rn_preset_error
        if _rn_ok and _rn_job:
            result["started"] = project.StartRendering([_rn_job], False)   # last call to Resolve

elif P["phase"] == "status":
    _rn_st = project.GetRenderJobStatus(P["job"]) or {}
    result = {"status": _rn_st, "rendering": project.IsRenderingInProgress()}
    if _rn_st.get("JobStatus") == "Complete":
        _rn_job = next((j for j in project.GetRenderJobList() if j.get("JobId") == P["job"]), {})
        _rn_state = _rn_os.path.join(_rn_job.get("TargetDir", ""), _rn_os.path.splitext(_rn_job.get("OutputFilename", ""))[0] + ".disabled.json")
        if _rn_os.path.exists(_rn_state):
            with open(_rn_state) as _rn_f:
                _rn_d = _rn_json.load(_rn_f)
            _rn_t = _rn_timeline(_rn_d["timeline"])
            project.SetCurrentTimeline(_rn_t)
            _rn_on = []
            for k, first in _rn_d["disabled"]:
                for it in _rn_t.GetItemListInTrack("video", k) or []:
                    if it.GetStart() == first:
                        it.SetClipEnabled(True)
                        _rn_on.append([k, first, it.GetClipEnabled()])
            _rn_os.remove(_rn_state)
            resolve.GetProjectManager().SaveProject()
            result["enabled_again"] = _rn_on
        result["file"] = _rn_os.path.join(_rn_job.get("TargetDir", ""), _rn_job.get("OutputFilename", ""))

else:
    result = {"error": f"unknown phase {P['phase']!r}: use start or status"}
