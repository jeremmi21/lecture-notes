# tab-recorder (experimental)

Records **one tab's** audio while leaving other tabs audible. This is what the
main pipeline cannot do: WASAPI loopback records the output mix, so a video
playing in another tab lands in the lecture file.

## Status: unverified, and the audit says why

A code audit ranked the defects that could each produce v1's zero bytes. The
verdict was "undecidable without a browser", with the strongest reason being
that v1.1 left the capture half byte-identical to v1 while only changing the
sink — so the part that actually failed is still unproven.

Fixed after the audit:

| Defect | Fix |
|---|---|
| Audio-only tab capture may be rejected on the `getUserMedia` path | try audio-only, fall back to passing the same tab constraint for video |
| `stop()` could hang forever, leaving the badge on `REC` and the tab muted | `onerror` plus a 3 s race |
| No way to tell "recording" from "no audio is arriving" | `needs: ["no-audio"]` after 3 s with zero frames |
| A lost offscreen document was reported as a zero-byte recording | badge `LOST` vs `EMPTY` |
| `hasDocument` may be newer than the stated minimum version | `createDocument` tolerates "single offscreen document" |

Still open, both certain and both listed in `PLAN.md`:

- **A6.** The whole recording is held in RAM until `stop()`. An extension reload
  or browser crash yields nothing rather than a truncated file. Fix is writing
  each chunk to a `FileSystemWritableFileStream`.
- **A4.** Anchor-click downloads are rate-limited per origin without user
  activation, so the second recording of a session may be silently blocked while
  the badge still reads `OK`. Fix is reading back `chrome.downloads` state.

## Status: unverified

Version 1.0 was loaded into Brave with `tabCapture`, `offscreen`, `downloads`
and `tabs` granted, its service worker ran, and it wrote **zero bytes**. It has
never produced a file on any machine.

Version 1.1 changes the two things most likely to have caused that:

1. **Download from the offscreen document, not the service worker.** v1 created
   a blob URL in the offscreen document and handed the string to
   `chrome.downloads.download` in the service worker. Blob URLs are scoped to
   the document that made them, and downloads from a worker are unreliable.
   v1.1 clicks an anchor inside the offscreen document instead, and drops the
   `downloads` permission entirely.
2. **Failures are visible.** v1 logged to the console, which nobody opens during
   a lecture. v1.1 moves the badge: `...` while starting, `REC` while recording,
   `ERR` when start throws, `OK` or `0` when stop returns a byte count.

Neither change has been confirmed in a browser. Treat it as an experiment until
a file appears.

## Control it from a terminal

```powershell
python tools/tabrec.py serve            # daemon on 127.0.0.1:8765
python tools/tabrec.py status [--json]
python tools/tabrec.py start [--tab ID]
python tools/tabrec.py stop
python tools/tabrec.py watch            # NDJSON, one line per state change
```

The extension holds one Server-Sent Events stream to the daemon for commands and
posts its state back, so there is no dependency beyond the standard library.
Exit codes: 0 ok, 3 daemon down, 4 extension disconnected, 5 command rejected.

The daemon is stateless: restart it mid-lecture and it rebuilds from the
extension's next update. The recorder keeps running because the sink is local.

**One hard limit:** `tabCapture` needs a user gesture on the target tab, so the
CLI cannot start an arbitrary tab. Click the toolbar icon (or press the
`chrome.commands` key) to make the gesture; the CLI can then stop, query and
take over the sink.

Design notes, including seven defects found in the recorder itself, are in
`PLAN.md`.

## Install

1. `brave://extensions` (or `chrome://extensions`)
2. Developer mode on
3. **Load unpacked** → this folder
4. Open the lecture tab, click the toolbar icon. Badge must read **REC**.

## Verify it in 60 seconds

1. Open any tab playing audio.
2. Click the icon → badge `REC`.
3. Wait 10 seconds, click again → badge `OK` and `tab-<stamp>.webm` in Downloads.

`0` or `ERR` means it did not work; that is the answer to "does it work", and it
costs a minute instead of a lecture.

## Why not just use this instead of loopback

- It is unfinished. Loopback has produced 1 h 59 m of verified audio; this has
  produced nothing.
- Tab capture only sees the tab. In a Meet call the lecturer's shared slides
  often render in a separate presentation window, which is a different target.
- It cannot follow a device change the way the recorder does.

Use it when tab isolation matters more than reliability, and verify before the
lecture starts.
