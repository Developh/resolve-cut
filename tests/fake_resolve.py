"""A fake DaVinci Resolve API: just enough of the project, media pool, timeline and items for the scripts in
scripts/resolve/ to run their own logic (phases, parameters, results) without Resolve. It checks the scripts'
plumbing, not Resolve's behaviour: the traps in SKILL.md were measured on the real thing."""
import json
import os

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "davinci-resolve-agent", "scripts")
calls = []


class Item:
    def __init__(self, clip, start, duration, track=("video", 1)):
        self.clip, self.start, self.duration, self.track = clip, start, duration, track
        self.props, self.enabled = {}, True

    def GetTrackTypeAndIndex(self):
        return list(self.track)

    def SetProperty(self, key, value):
        self.props[key] = value
        return True

    def GetProperty(self, key):
        return self.props.get(key)

    def GetStart(self):
        return self.start

    def GetDuration(self):
        return self.duration

    def GetLeftOffset(self):
        return 10.0

    def GetMediaPoolItem(self):
        return self.clip

    def GetClipEnabled(self):
        return self.enabled

    def SetClipEnabled(self, value):
        self.enabled = value
        return True


class Clip:
    def __init__(self, name):
        self.name, self.props = name, {}

    def GetName(self):
        return self.name

    def SetClipColor(self, color):
        return True

    def SetMetadata(self, metadata):
        return True

    def GetClipProperty(self, key):
        return self.props.get(key, "")

    def SetClipProperty(self, key, value):
        self.props[key] = value
        return True


class Folder:
    def __init__(self, name):
        self.name, self.clips, self.subfolders = name, [], []

    def GetName(self):
        return self.name

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return self.subfolders


class Timeline:
    def __init__(self, name):
        self.name, self.items, self.markers = name, [], []
        self.settings = {"timelineResolutionWidth": "1920", "timelineResolutionHeight": "1080", "timelineFrameRate": "25"}

    def GetName(self):
        return self.name

    def GetStartFrame(self):
        return 90000

    def GetEndFrame(self):
        return 90000 + sum(i.duration for i in self.items if i.track[0] == "video")

    def GetSetting(self, key):
        return self.settings[key]

    def SetTrackName(self, *args):
        return True

    def SetVoiceIsolationState(self, track, state):
        calls.append(("voice_isolation", track, state))
        return True

    def AddMarker(self, *args):
        self.markers.append(args)
        return True

    def GetItemListInTrack(self, kind, index):
        return [i for i in self.items if i.track == (kind, index)]

    def ExportFrame(self, frame, options):
        with open(options["filePath"], "w") as f:
            f.write("png")
        return {"success": True}

    def DeleteClips(self, items, ripple):
        for i in items:
            self.items.remove(i)
        return True


class MediaPool:
    def __init__(self, project):
        self.project, self.root, self.current = project, Folder("Master"), None

    def GetRootFolder(self):
        return self.root

    def AddSubFolder(self, parent, name):
        folder = Folder(name)
        parent.subfolders.append(folder)
        return folder

    def SetCurrentFolder(self, folder):
        self.current = folder
        return True

    def ImportMedia(self, paths):
        calls.append(("import", len(paths)))
        new = [Clip(os.path.basename(p)) for p in paths]
        self.current.clips += new
        return new

    def CreateEmptyTimeline(self, name):
        timeline = Timeline(name)
        self.project.timelines.append(timeline)
        return timeline

    def AppendToTimeline(self, infos):
        out = []
        for d in infos:
            assert d["endFrame"] > d["startFrame"], d
            length = d["endFrame"] - d["startFrame"]
            kinds = ["video"] if d.get("mediaType") == 1 else ["video", "audio"]
            for kind in kinds:
                item = Item(d["mediaPoolItem"], d["recordFrame"], length, (kind, d.get("trackIndex", 1)))
                self.project.current.items.append(item)
                out.append(item)
        return out


class Project:
    def __init__(self, name):
        self.name, self.timelines, self.current, self.pool = name, [], None, None
        self.settings, self.jobs, self.presets = {}, [], []

    def GetName(self):
        return self.name

    def GetMediaPool(self):
        self.pool = self.pool or MediaPool(self)
        return self.pool

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index):
        return self.timelines[index - 1]

    def SetCurrentTimeline(self, timeline):
        self.current = timeline
        return True

    def SetSetting(self, key, value):
        self.settings[key] = value
        return True

    def GetSetting(self, key):
        return self.settings.get(key)

    def GetRenderPresetList(self):
        return ["H.264 Master"] + self.presets

    def LoadRenderPreset(self, name):
        calls.append(("load_preset", name))
        return name in self.presets

    def SetCurrentRenderFormatAndCodec(self, fmt, codec):
        calls.append(("format", fmt, codec))
        return True

    def SetRenderSettings(self, settings):
        calls.append(("settings", settings))
        self.last_settings = settings
        return True

    def AddRenderJob(self):
        s = self.last_settings
        self.jobs.append({"JobId": "job1", "TargetDir": s["TargetDir"], "OutputFilename": s["CustomName"] + ".mp4"})
        return "job1"

    def StartRendering(self, jobs, interactive):
        calls.append(("start", jobs))
        return True

    def GetRenderJobStatus(self, job):
        return {"JobStatus": "Complete", "CompletionPercentage": 100}

    def GetRenderJobList(self):
        return self.jobs

    def IsRenderingInProgress(self):
        return False


class ProjectManager:
    def __init__(self):
        self.project = None

    def LoadProject(self, name):
        return self.project if self.project and self.project.name == name else None

    def CreateProject(self, name):
        self.project = Project(name)
        return self.project

    def GetCurrentProject(self):
        return self.project

    def SaveProject(self):
        return True


class Resolve:
    COMPOSITE_SCREEN = 1

    def __init__(self):
        self.pm = ProjectManager()

    def GetProjectManager(self):
        return self.pm

    def OpenPage(self, page):
        return True

    def ImportRenderPreset(self, path):
        calls.append(("import_preset", path, os.path.exists(path)))
        self.pm.project.presets.append(os.path.splitext(os.path.basename(path))[0])
        return True


resolve = Resolve()


def run(script, P):
    """Runs a script the way run.py does: resolve, project, P and __file__ defined, result read back."""
    path = os.path.join(SCRIPTS, "resolve", script)
    env = {"resolve": resolve, "project": resolve.pm.project, "P": P, "result": None, "__name__": "__resolve__", "__file__": path}
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"), env)
    print(f"{script} {P.get('phase', '')}: {json.dumps(env['result'], default=str)[:300]}")
    return env["result"]
