# lecture-notes

Record an online lecture, transcribe it locally, and get notes where every claim
carries the minute it was said.

No bot joins the call. No audio is uploaded. Four steps, three commands, one
hand-built graph.

## What it actually does

```
record_loopback.py   ->  lecture.wav       (WASAPI loopback, follows the output device)
transcribe.py        ->  transcript.json   (faster-whisper, small int8, timestamped)
graph.json           ->  (you, reading)    topics, rules, cases, each with an offset
render_notes.py      ->  notes.md          index + rule list + cases + citations
```

Measured on a 4-core i7-6820HQ laptop: **two hours of audio transcribed in 51
minutes** (2.33x realtime), 1 084 segments, whole file covered.

## Install

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`ffmpeg` must be on `PATH` (`winget install Gyan.FFmpeg`). The transcription
engine is [faster-whisper](https://github.com/SYSTRAN/faster-whisper); this repo
pins the versions that work on a CPU-only Windows machine.

As an omp / Claude Code agent skill, copy or link this folder into your skills
directory:

```powershell
mklink /J "%USERPROFILE%\.agents\skills\lecture-notes" "%CD%"
```

## Use

```powershell
# 1. record (start before the lecture begins; Ctrl-C to stop)
.\.venv\Scripts\python.exe tools\record_loopback.py -o lectures\2026-11-10-contract-law\2026-11-10-contract-law.wav

# 2. transcribe
.\.venv\Scripts\python.exe tools\transcribe.py lectures\2026-11-10-contract-law\2026-11-10-contract-law.wav

# 3. write graph.json by hand, following templates/graph.example.json

# 4. render
.\.venv\Scripts\python.exe tools\render_notes.py lectures\2026-11-10-contract-law\graph.json
```

`SKILL.md` is the agent-facing version of the same instructions.

## The graph is the artifact

`notes.md` is generated. Correct the graph and re-render; never edit the note.
Every rule node carries the second it was said, so a claim can be checked
against the recording instead of trusted.

Cases carry the facts and holding **as the lecturer taught them**, not as a
textbook states them, because the exam tests what was taught.

Statute and case names are the recogniser's weak point. Anything that did not
appear verbatim in the transcript belongs in `unverified`, and that list is
printed at the bottom of the note.

## What this deliberately does not do

- **No bot, no cloud.** A bot needs host admission and a Google Workspace API
  that was deprecated in October 2026; uploading lecture audio is a decision the
  user should make explicitly, not a default.
- **No per-tab audio.** WASAPI loopback records the output mix, so anything
  playing in another tab lands in the file. A `chrome.tabCapture` extension was
  built and produced zero bytes; it is not shipped.
- **No slide capture.** Three methods were tried against Meet's presentation
  window: CDP on the surface (session dies), `PrintWindow` on a covered Chromium
  window (blank), and window grab (only while visible, and cropped to the ribbon
  when the window is small). Ask for the deck instead.
- **No diarization.** Loopback gives one mixed stream. See `advanced/`.

## Layout

```
SKILL.md                  agent instructions
advanced/README.md        optional: speaker labels, faster engine
tools/record_loopback.py  WASAPI loopback recorder, follows the output device
tools/render_notes.py     graph.json -> notes.md
templates/graph.example.json  placeholder graph, no real lecture content
templates/graph.schema.md     every field, what it means, why it exists
requirements.txt          pinned; unpinned versions break on this platform
```

## License

MIT.
