# tab-recorder (experimental)

Records **one tab's** audio while leaving other tabs audible. This is what the
main pipeline cannot do: WASAPI loopback records the output mix, so a video
playing in another tab lands in the lecture file.

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
