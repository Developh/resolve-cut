"""Swap the media of shots on a timeline without losing the cut or the framing.

    python3 run.py swap_media.py '{"timeline": "Lesson 01 v3", "track": 1,
                                   "swaps": [{"old": "talk-retouch2.mov", "new": "talk-retouch3.mov"}]}'

Runs inside Resolve: through run.py, or the MCP's run_script_unsafe (P = {...}, then exec of this file).

For each shot on the track whose media pool clip is named "old": deletes it and places the "new" clip on the same
frame, with the same duration, the same source in point and the same transform properties (pan, tilt, zoom,
rotation, crop, opacity, composite mode). The source in point is read with GetLeftOffset: GetSourceStartFrame
sometimes reads one frame early. Super Scale (a media pool property) is copied from the old clip to the new one.
- The new clip must already be in the media pool (import ProRes one file per call). It is found by name in any bin.
- The Color page grade does not come along (nodes belong to the shot). To change the file and keep the grade, use
  ReplaceClip on the media pool item instead, which changes the file in every timeline that uses it (and wipes the
  clip's metadata).
- Work on a copy of the timeline (DuplicateTimeline: "v3" becomes "v4"). The result lists every swapped shot.
"""
if __name__ == "__main__" and "resolve" not in globals():
    import sys
    print(__doc__.strip())
    sys.exit(0)

_SW_PROPS = ["Pan", "Tilt", "ZoomX", "ZoomY", "RotationAngle", "AnchorPointX", "AnchorPointY", "Pitch", "Yaw",
             "FlipX", "FlipY", "CropLeft", "CropRight", "CropTop", "CropBottom", "CropSoftness", "Opacity", "CompositeMode"]
_SW_SUPER_SCALE = ["Super Scale", "SuperScale Sharpness", "SuperScale Noise Reduction"]


def _sw_clips(folder, out):
    for c in folder.GetClipList() or []:
        out.setdefault(c.GetName(), c)
    for sub in folder.GetSubFolderList() or []:
        _sw_clips(sub, out)
    return out


_sw_tls = {project.GetTimelineByIndex(i).GetName(): project.GetTimelineByIndex(i) for i in range(1, project.GetTimelineCount() + 1)}
_sw_tl = _sw_tls.get(P["timeline"])
if not _sw_tl:
    result = {"error": f"no timeline named {P['timeline']!r}"}
else:
    project.SetCurrentTimeline(_sw_tl)
    _sw_mp = project.GetMediaPool()
    _sw_pool = _sw_clips(_sw_mp.GetRootFolder(), {})
    _sw_track = P.get("track", 1)
    _sw_res, _sw_missing = [], [s["new"] for s in P["swaps"] if s["new"] not in _sw_pool]
    if _sw_missing:
        result = {"error": "new clips not in the media pool", "missing": _sw_missing}
    else:
        _sw_shots = []
        for it in _sw_tl.GetItemListInTrack("video", _sw_track) or []:
            m = it.GetMediaPoolItem()
            name = m.GetName() if m else None
            swap = next((s for s in P["swaps"] if s["old"] == name), None)
            if not swap:
                continue
            props = {k: it.GetProperty(k) for k in _SW_PROPS}
            _sw_shots.append({"item": it, "new": swap["new"], "rec": it.GetStart(), "dur": it.GetDuration(),
                              "in": int(round(it.GetLeftOffset())), "props": {k: v for k, v in props.items() if v is not None},
                              "super_scale": {k: m.GetClipProperty(k) for k in _SW_SUPER_SCALE}})
        for p in _sw_shots:   # Super Scale from the old clip to the new one
            new = _sw_pool[p["new"]]
            for k, v in p["super_scale"].items():
                if v not in (None, "") and str(new.GetClipProperty(k)) != str(v):
                    new.SetClipProperty(k, v)
        _sw_deleted = _sw_tl.DeleteClips([p["item"] for p in _sw_shots], False) if _sw_shots else True
        for p in _sw_shots:
            its = _sw_mp.AppendToTimeline([{"mediaPoolItem": _sw_pool[p["new"]], "startFrame": p["in"],
                                            "endFrame": p["in"] + p["dur"], "trackIndex": _sw_track,
                                            "recordFrame": p["rec"], "mediaType": 1}])
            it = its[0] if its else None
            failed = [k for k, v in p["props"].items() if it.GetProperty(k) != v and not it.SetProperty(k, v)] if it else ["not placed"]
            _sw_res.append({"rec": p["rec"], "dur": it.GetDuration() if it else None,
                            "in": int(round(it.GetLeftOffset())) if it else None,
                            "expected": [p["dur"], p["in"]], "new": p["new"], "failed_properties": failed})
        resolve.GetProjectManager().SaveProject()
        result = {"deleted": _sw_deleted, "swapped": _sw_res}
