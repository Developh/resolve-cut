---
name: davinci-resolve-agent
description: "Edit talking-head videos (lessons, courses, interviews) end to end in DaVinci Resolve Studio: word-level transcripts, a dossier of every take, the last complete take of each paragraph, a frame-accurate cut list, timeline assembly by script, render with presets, QC (loudness, frames, repeated words) and delivery. Load before any Resolve scripting, assembly, render, QC or video delivery work."
---

# DaVinci Resolve agent

You assemble, render and check videos in DaVinci Resolve Studio through saved scripts with parameters. You do not
rewrite the assembly in every session: you call the scripts, read what they return and verify the result with
numbers and frames. Taste stays human: the person decides what stays, you execute and measure.

`$SKILL` below is this skill's folder (where this file lives). Scripts in `scripts/resolve/` run inside Resolve
through `run.py`; scripts in `scripts/media/` are plain Python with ffmpeg. Every script has `--help`.

## Before you start

1. Resolve answers: `python3 "$SKILL/scripts/resolve/run.py" - '{}' <<< 'result = resolve.GetVersionString()'`.
   Exit code 2 means Resolve is closed, it is the free edition, or Preferences > System > General > External
   scripting using is not set to Local.
2. `ffmpeg -version`, `python3 -c "import numpy, PIL"` and `ELEVENLABS_API_KEY` (environment or `./.env`).
3. If the project keeps a notes file (`VIDEO_NOTES.md` or similar), read it: what the person approved and rejected
   before. Do not ask for the same correction twice.
4. Work folder: everything you write (transcripts, dossier, frames, renders) goes to a work folder, never into the
   raw footage folder.

## The flow

**1. Transcribe.** Word-level transcripts, one JSON per clip:
`python3 "$SKILL/scripts/media/transcribe.py" <clips folder> --out work/transcripts [--language por]`.
The transcript is the base of everything: picking takes, cutting on frame boundaries and checking the final mix.

**2. Dossier.** All the material in one compact text file, read once:
`python3 "$SKILL/scripts/media/dossier.py" <clips folder> --transcripts work/transcripts --out work/dossier.md [--sheets]`.
It lists every sentence with its time and flags `«repeats C0076 20.2»` when a sentence starts like an earlier one:
another attempt at the same line. With a script, keep the **last complete take** of each paragraph; drop
hesitations, false starts and repeated attempts. Open a clip only to decide something:
`python3 "$SKILL/scripts/media/inspect_range.py" <clip> <t0> <t1> --words work/transcripts/<clip>.json` (frames,
waveform and words in one image).

**3. Cut list.** Write `work/plan.json` with the chosen takes in order
(`{"Lesson 01 v1": [["01a", "C0081", 1.9, 12.6], ["01b", "C0083", 5.4, 23.8], ...]}`: take, clip, from, to in seconds
of the clip), then:
`python3 "$SKILL/scripts/media/cut_list.py" work/plan.json work/transcripts <clips folder> work/cuts.json`.
Cuts land on the quietest frame boundary next to the words, pauses over 1 s are shortened, and segments alternate
zoom 1 / 1.2 so cuts between takes do not jump. For a false start with no gap ("co- contar"), force the frame with
`{"in_frame": N}` or `{"out_frame": N}`. Notes for the editor: `add_markers.py`.

**4. Assemble in Resolve.** One heavy operation per call, and read each `result` before the next:
```sh
R="$SKILL/scripts/resolve/run.py"
python3 "$R" "$SKILL/scripts/resolve/project.py" '{"name": "Lesson 01", "width": 1920, "height": 1080, "fps": "25"}'
python3 "$R" "$SKILL/scripts/resolve/assemble.py" '{"phase": "import", "bin": "Raw", "media": "/abs/clips", "files": ["C0081.MP4"]}'
python3 "$R" "$SKILL/scripts/resolve/assemble.py" '{"phase": "timeline", "bin": "Raw", "cuts": "/abs/work/cuts.json", "timeline": "Lesson 01 v1", "zoom": {"center": [0.45, 0.37]}, "voice_isolation": 50}'
```
`zoom.center` is where the face is (fraction of the frame), so the punch-in keeps it in place. Check that
`frames == expected` and `failures` is empty.

**5. Look before rendering.** `frames.py` exports frames straight from the timeline in under a second
(`{"timeline": "Lesson 01 v1", "frames": [100, 500], "folder": "/abs/work/frames", "max": 960}`). Look at one plain
and one punch-in frame.

**6. Render.**
`python3 "$R" "$SKILL/scripts/resolve/render.py" '{"phase": "start", "timeline": "Lesson 01 v1", "folder": "/abs/out", "name": "lesson-01", "preset": "reel", "width": 1920, "height": 1080, "mark": [0, <frames - 1>]}'`,
then poll `{"phase": "status", "job": "<id>"}` every 10 s until `JobStatus` is `Complete`. **Wait for the render to
finish** before you answer: a headless run that ends its turn at "render started" leaves nobody to check it.

**7. Verify.** `python3 "$SKILL/scripts/media/qc.py" out/lesson-01.mp4 --expected <frames> --transcribe`
(add `--ref` against the last approved version, `--frames` for a sheet, `--simulate` for Instagram). Read the
transcript of the final mix at every cut: repeated words ("decide, decide"), cut words and words in the wrong place
are the defects a cut list makes. Confirm a suspect cut on the waveform (`inspect_range.py`) before moving it, fix
the cut list, assemble a new version (`v2`) and render again. At most 3 rounds, each defect named with its exact
time. Never call it done because it "looks right": quote the numbers.

**8. Deliver.** `loudness.py` when the mix is off target (linear gain and a limiter, never loudnorm), then
`deliver.py export.mp4 clean.mp4 [--no-editlist] [--copy <folder>]`: no timecode track, no metadata, moov first,
copy compared byte by byte.

**9. Review, after the person approves.** Write in the notes file what they approved and rejected, in their words,
one line each; every new trap with its date; and every routine you did by hand more than once becomes a script with
parameters next to these.

## Running scripts inside Resolve

- `run.py` connects to the open Resolve and runs a script with `resolve`, `project`, `P` (the JSON) and `__file__`
  defined, then prints `result` as JSON. It costs far fewer tokens than writing the same script through an MCP.
- With an MCP server instead (official `run_script_unsafe`):
  `P = {...}; __file__ = "<abs path of the script>"; exec(open(__file__, encoding="utf-8").read())`. The sandbox
  reads files as ASCII without `encoding`, and names persist between calls: the scripts prefix their variables.
- Save before and after writing (`GetProjectManager().SaveProject()`); there is no undo. Make every new version on a
  copy of the timeline (`DuplicateTimeline`, which copies Fusion comps too).
- Look the API up instead of guessing: the official MCP's `search_scripting_api`, `get_scripting_docs` and
  `get_whats_new` (once per session), or Blackmagic's README in Resolve's `Developer/Scripting` folder (Help >
  Documentation > Developer).
- New operation that will repeat? Write it once as a script with a `P` dict and a `result`, next to these.

## Delivery targets

| Destination | Picture | Sound |
|---|---|---|
| Reels, Stories, Shorts, TikTok | 1440x2560 at the shooting frame rate, H.264 High at about 20 Mbps real, Rec.709 tags (1-1-1), faststart | -14 LUFS, true peak under -1.5 dBTP |
| Lessons and courses | as recorded (1920x1080 or 3840x2160) | -16 LUFS, true peak up to -1 dBTP |
| YouTube | the 4K master (1080p uploads lose quality), MP4 without edit lists | the master's mix |
| LinkedIn | 1920x1080 and 1080x1920 at 16 Mbps, with SRT | the master's mix |

## Verified traps

Measured on macOS with Resolve Studio 21.1.1 and 21.1.2, October and November 2026.

Machine
- One ffmpeg at a time, with `nice -n 15` and `-threads 2`: 96 parallel ffmpeg processes froze the Mac and forced a reboot.
- In zsh, `$var` does not split into words (`ffmpeg $args` breaks): build argument lists in Python.
- Write outputs to the work folder: a helper that saved images next to the clip wrote into the raw footage drive.

Resolve setup and API
- Resolve 21.1 moved Python scripting to Studio: `run.py` and both MCP servers need DaVinci Resolve Studio.
- External scripting must be set to Local (Preferences > System > General) or `scriptapp("Resolve")` returns None.
- `StartRendering` is the last call of a script: everything else returns None until the render ends.
- The project frame rate locks when the first timeline is created: set it before (`project.py`).
- Resolution: `SetSetting` one key at a time, `useCustomSettings` first.
- The MCP timeout (10 s by default, 60 s at most) returns an error but the script keeps running inside Resolve: check the state before running it again.
- There is no trim, move or slip: delete the item and append it again with `startFrame`, `endFrame` (exclusive) and `recordFrame`.
- `startFrame` counts from the file's first frame, even with camera timecode.
- `GetSourceStartFrame` sometimes reads one frame early (866 reads 865) while the placement is right: read the in point with `GetLeftOffset`.
- `AddMarker` keeps one marker per frame.
- `ReplaceClip` wipes the clip's metadata.
- `SetTrackEnable` returns True and changes nothing on some timelines: disable the clips with `SetClipEnabled` and confirm on an exported frame.
- `SetClipEnabled` on a timeline that is not the current one returns False: `SetCurrentTimeline` first, then confirm with `GetClipEnabled`.
- `DeleteClips(items, True)` ripples every track: first delete, without ripple, whatever crosses the cut (stems, captions).
- Voice Isolation works by script: `TimelineItem.SetVoiceIsolationState({"isEnabled": True, "amount": 100})` lowered room reverb by 3 to 4 dB; `Timeline.SetVoiceIsolationState(track, {...})` sets one control for a whole track.
- The API cannot set ResolveFX parameters (Face Refinement, Blemish Removal): a person sets them, or you drive the UI through accessibility.
- With the screen locked or Resolve minimized, the window disappears from accessibility but the API keeps working: verify with exported frames.
- Super Scale is a media pool property: `SetClipProperty("Super Scale", 2)`; a replacement file needs it set again.
- LUTs for `Graph.SetLUT` go in Resolve's system LUT folder, in a subfolder, passed by relative path after `RefreshLUTList()`.
- Changing pages while Resolve plays back hangs it; `item.GetFusionCompByIndex(1).Execute(lua)` edits a comp without opening the Fusion page.

Import and media
- One ProRes per import call: several ProRes 4444 (and once two new ProRes 422) in one call crashed Resolve 21.1 (`UiMpController`, `std::out_of_range`). Camera MP4s, 22 in one call, were fine.
- After that crash, an orphan `ResolvePython` process makes the MCP's `launch_resolve` report Resolve as running: kill it and open Resolve again.
- `ImportMedia` with a list of paths: the form with dicts returned None for MP4 on 21.1.
- Resolve caches decoding by path: a file you render again gets a new name.
- PCM 24-bit little-endian in MOV is read as white noise: use `pcm_s24be`.
- iPhone HEVC crashed the macOS decoder: edit from ProRes.
- iPhone HDR (HLG, Dolby Vision): our own tonemap looked washed out and was rejected twice. Ask for an SDR export at the start.
- A 1-frame `.mov` imports as a 150-frame still: give it at least 3 frames and trim on the timeline.
- Straight alpha: Resolve reads alpha unpremultiplied, so an overlay made with ffmpeg `overlay` on a transparent canvas comes out dark; position it with `pad=W:H:x:y:color=black@0.0`.

Render
- With `SelectAllFrames`, `StartRendering` sometimes returns False: set `MarkIn`/`MarkOut` (render.py `mark`), which also cuts the sound tails that lengthen a timeline.
- An H.264 job created right after an audio-only job came out without video: load a preset before `SetRenderSettings`, and check for the video stream with ffprobe.
- H.264 `VideoQuality` is a ceiling, not an average: 20000 gave 14.7 Mbps and 27300 gave 20.7 Mbps at 1440x2560.
- "Force sizing to highest quality" is not a `SetRenderSettings` key, but it travels inside a render preset (`ForceHighestQualitySizing`).
- `ExportRenderPreset(name, path)` treats `path` as a folder; `ImportRenderPreset` names the preset after the file.
- Presets store a frame rate: set `FrameRate` from the timeline, or a 29.97 timeline renders converted (render.py does).
- `ExportFrame` (21.1.2) gave 4 frames at 1440x2560 in 0.75 s, within 41 to 46 dB of the render: check frames without rendering.

Sound and transcripts
- A cut between two takes can join a repeated word ("decide, decide"): transcribe the final mix and look for duplicates. Fix without changing the length: end the first piece before the word, start the second earlier in the good take's pause.
- The transcript does not hear whispers and breaths: cut points come from the camera's own sound (`cut_list.py`).
- Scribe once placed a word 3 s early, after a clap and a whisper: confirm on the waveform before moving a cut.
- MP3 sound effects land about 60 ms late (the encoder delay is not compensated): use WAV for anything that must hit a frame.
- loudnorm in one pass is dynamic and changes the approved mix; in two passes it silently falls back to dynamic: use `loudness.py`.

Footage and platforms
- 25 fps on Instagram: served at 25 (ffprobe of the served files, November 2026). The stutter comes from ProMotion iPhones, which have no 25 or 50 Hz mode. Keep 25 fps footage at 25 (converting to 30 repeats one frame in five); shoot new material at 29.97 with a 1/50 shutter.
- Flicker under 50 Hz lights depends on the shutter, not the frame rate: 1/50 and 1/100 do not flicker; 1/60 at 30 fps does.
- Instagram re-encodes on the phone and again on the server: the basic delivery is about 720x1280 at 1.4 Mbps, with sound normalised to about -14 LUFS, so a master above -14 gains nothing. `qc.py --simulate` shows what survives.
- CRF in ffmpeg starves dark backgrounds: one reel left at 6.8 Mbps. Check the real bitrate before delivering.
- A headless `claude -p` run ends its turn when the render starts unless the prompt says to wait for it.

## Scripts

| Script | What it does |
|---|---|
| `scripts/media/transcribe.py` | Scribe word-level JSON per clip (key through stdin, never in the process list) |
| `scripts/media/dossier.py` | every clip as compact text: sentences with times, pauses, repeated attempts, optional frame sheets |
| `scripts/media/inspect_range.py` | one image of a range: frames, waveform, words with times |
| `scripts/media/cut_list.py` | takes in seconds → frame-accurate cut list on the quietest boundaries |
| `scripts/media/add_markers.py` | markers anchored to segments or words, so they follow cut list changes |
| `scripts/resolve/run.py` | run any script inside Resolve from the shell, with `P` in and `result` out |
| `scripts/resolve/project.py` | create or open a project, frame rate and resolution before the first timeline |
| `scripts/resolve/assemble.py` | import, clip colours and notes, timeline with punch-ins, Voice Isolation and markers |
| `scripts/resolve/frames.py` | timeline frames as PNG without rendering |
| `scripts/resolve/render.py` | render with a preset, mark in/out, tracks off for one render, status polling |
| `scripts/resolve/swap_media.py` | replace the media of shots, keeping cut, in point, transform and Super Scale |
| `scripts/media/qc.py` | streams, fps, frames, bitrate, colour tags, faststart, LUFS and true peak, frozen and dropped frames, PSNR, transcript, Instagram simulation |
| `scripts/media/loudness.py` | loudness to target with linear gain and a limiter |
| `scripts/media/deliver.py` | clean delivery file (no timecode track or metadata, moov first), copy verified byte by byte |
