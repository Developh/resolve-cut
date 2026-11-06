"""Create (or open) a Resolve project and set its frame rate and resolution before the first timeline.

    python3 run.py project.py '{"name": "Lesson 01", "width": 1920, "height": 1080, "fps": "25"}'

- Runs inside Resolve: through run.py, or the MCP's run_script_unsafe (P = {...}, then exec of this file).
- The project frame rate locks when the first timeline is created, so it is only set while the project has no
  timelines. The result shows what Resolve reads back: check it before building anything.
- Settings go one key at a time with SetSetting, useCustomSettings first.
- Keep the camera's frame rate: material shot at 25 stays at 25 (converting to 30 repeats one frame in five).
- Saves the project.
"""
if __name__ == "__main__" and "resolve" not in globals():
    import sys
    print(__doc__.strip())
    sys.exit(0)

_pj_pm = resolve.GetProjectManager()
_pj = _pj_pm.LoadProject(P["name"]) or _pj_pm.CreateProject(P["name"])
if not _pj:
    result = {"error": f"could not open or create the project {P['name']!r}"}
else:
    _pj_out = {"project": _pj.GetName(), "timelines": _pj.GetTimelineCount()}
    if _pj.GetTimelineCount() == 0:
        _pj_out["fps"] = _pj.SetSetting("timelineFrameRate", str(P["fps"]))
    else:
        _pj_out["fps"] = "not changed: the project already has timelines"
    _pj_out["custom"] = _pj.SetSetting("useCustomSettings", "1")
    _pj_out["width"] = _pj.SetSetting("timelineResolutionWidth", str(P["width"]))
    _pj_out["height"] = _pj.SetSetting("timelineResolutionHeight", str(P["height"]))
    _pj_out["read_back"] = {k: _pj.GetSetting(k) for k in ("timelineFrameRate", "timelineResolutionWidth", "timelineResolutionHeight")}
    _pj_pm.SaveProject()
    result = _pj_out
