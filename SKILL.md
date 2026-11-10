---
name: lecture-notes
description: Record a Google Meet or online lecture locally, transcribe it, and build a cited knowledge graph plus notes. Use when the user says record my lecture/class/meet, turn a lecture recording into notes, or asks for a study graph from a recording. No bot, no cloud.
---

# Lecture notes

Records what the machine plays, transcribes it locally, and builds notes where
every claim carries the minute it was said. Nothing leaves the machine and no
bot joins the call.

## When to use

- "Record my lecture / class / Meet call."
- "Turn this recording into notes / a study graph."
- "I have a transcript, make notes from it."

## Workflow

Four steps. Each one has a command and a check; do not skip the check.

### 1. Record (only if there is no audio file yet)

```powershell
.\.venv\Scripts\python.exe tools\record_loopback.py -o lectures\<date>-<course>\<date>-<course>.wav
```

The recorder follows the default output device (headphones plugged in, Bluetooth
connected) and pads idle gaps so file time equals elapsed recording time.

**Name the file after the lecture, never `audio.wav`.** The transcriber
derives its output name from the file stem, so two lectures called `audio.wav`
overwrite each other.

Check after 30 seconds: the printed dBFS must sit between -35 and -8 while
someone speaks. A number stuck at -120 means nothing is reaching the file —
check the Windows volume slider, then the mute inside the call. The recorder
prints the same warning on its own line after 30 s of digital silence.

Do not mute the Windows output device; mute inside the call. Some drivers cut
the loopback stream when the device is muted.

### 2. Transcribe

```powershell
.\.venv\Scripts\python.exe tools\transcribe.py lectures\<date>-<course>\<date>-<course>.wav
```

Expect roughly 25 minutes per hour of audio on a 4-core laptop. It prints
nothing until it finishes; the JSON appears at the end, not progressively.

Check: `segments` count > 0, `segments[-1].end` within a minute of the audio
duration, and the first segment reading like the opening of the lecture. If the
last timestamp falls short by minutes, the recording lost its tail or the
device changed mid-file.

### 3. Build the graph

Read the transcript in full and write `<lecture>/graph.json` following
`templates/graph.example.json` (field reference in `templates/graph.schema.md`). Do not sample sections.

- One `topic` per section of the lecture, with `start`/`end` offsets in seconds.
- One `rule` per statement the lecturer made, verbatim in spirit, with the
  offset where it was said.
- One `case` per authority cited, with `facts` and `holding` as taught.
- Edges only where they earn their place: `illustrates`, `except`,
  `qualified_by`, `contrasts_with`.
- `contaminated`: unrelated audio inside the recording (a video playing in
  another tab, a phone call). Give it a range.
- `excluded`: housekeeping that is not lecture content.
- `unverified`: statute or case names that did not appear verbatim in the
  transcript. The recogniser mangles proper names and a timestamp makes a wrong
  name look authoritative.

### 4. Render notes

```powershell
.\.venv\Scripts\python.exe tools\render_notes.py lectures\<date>-<course>\graph.json
```

Writes `notes.md` beside the graph. The note is a view: correct the graph and
re-render, never hand-edit the note.

## Output contract

```
lectures/<date>-<course>/
  <date>-<course>.wav   optional, delete once transcript.json is verified
  transcript.json       canonical, timestamped segments
  transcript.md         same, [mm:ss] per segment
  graph.json            topics, rules, cases, edges
  notes.md              rendered from graph.json
```

## Rules

- Never invent a rule, case, or holding that is not in the transcript. If the
  lecturer said it, cite the minute; if not, it does not exist.
- Never claim the audio was transcribed without checking the segment count and
  the last timestamp.
- Practice questions are written from rules, not generated from audio, and are
  added only when the user asks.
- Slides are not captured. Screen capture of a shared deck produces cropped
  frames and no time mapping. Ask for the `.pptx` or the LMS copy instead.
- Do not install a second transcription stack to redo a finished job.

## Failure modes already paid for

| Symptom | Cause | Fix |
|---|---|---|
| 8 minutes of silence in a valid WAV | device changed (Bluetooth) | recorder follows the endpoint now; check the dBFS line |
| transcript timestamps drift early | WASAPI stops frames when idle | recorder pads to wall clock; check the `drift` line at close |
| second lecture overwrote the first | both files named `audio.wav` | name files after the lecture |
| `faster_whisper` will not import | `ctranslate2` wheel links CUDA DLLs | see `requirements.txt` pins |
| names wrong in the transcript | 244M model, no vocabulary hint | mark them in `unverified`, or use hotwords |

## Optional upgrades

See `advanced/README.md` for speaker labels and a faster engine. Neither is
required, neither is part of the workflow above, and neither was measured on
the hardware this pipeline was built for.
