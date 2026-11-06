"""Export frames of a timeline without rendering (Timeline.ExportFrame, Resolve 21.1.2+), to check framing, colour,
punch-ins and graphics in seconds instead of rendering a section.

    python3 run.py frames.py '{"timeline": "Lesson 01 v1", "frames": [100, 500], "folder": "/abs/frames", "max": 960}'

- Runs inside Resolve: through run.py, or the MCP's run_script_unsafe (P = {...}, then exec of this file).
- frames: counted from the start of the timeline (0 = first frame), like render.py's "mark".
- folder: where the PNGs go (<timeline name>-<frame>.png); created if missing.
- max: longest side in pixels (0 = timeline size). 960 to 1280 is enough to look at, and faster.
- The frame comes out as the render would make it: every enabled track, graphics included. To see one track alone,
  disable the clips of the others with SetClipEnabled first (SetTrackEnable does not always take) and enable them
  again afterwards.
"""
if __name__ == "__main__" and "resolve" not in globals():
    import sys
    print(__doc__.strip())
    sys.exit(0)

import os as _fr_os

_fr_tl = None
for _fr_i in range(1, project.GetTimelineCount() + 1):
    if project.GetTimelineByIndex(_fr_i).GetName() == P["timeline"]:
        _fr_tl = project.GetTimelineByIndex(_fr_i)
if not _fr_tl:
    result = {"error": f"no timeline named {P['timeline']!r}"}
else:
    _fr_os.makedirs(P["folder"], exist_ok=True)
    _fr_name = P["timeline"].replace(" ", "-")
    result = {}
    for _fr_n in P["frames"]:
        _fr_path = _fr_os.path.join(P["folder"], f"{_fr_name}-{int(_fr_n):05d}.png")
        _fr_r = _fr_tl.ExportFrame(int(_fr_n), {"outputType": "file", "filePath": _fr_path, "maxDimension": int(P.get("max", 0))}) or {}
        result[str(_fr_n)] = _fr_path if _fr_r.get("success") and _fr_os.path.exists(_fr_path) else f"failed: {_fr_r.get('error')}"
