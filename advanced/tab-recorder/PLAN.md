# tab-recorder v1.2 — control channel, real UI, chosen folder

Scope: make `advanced/tab-recorder` controllable from a terminal and a page, add a popup, and let
the user pick the output folder. The capture pipeline stays; only its observability and sink change.

## 0. Defects in the current code the design must route around

| # | Where | Defect |
|---|---|---|
| D1 | `offscreen.js:45` | `new AudioContext()` is never resumed. Autoplay policy leaves it `suspended` in a gesture-less document, so the analyser reads 0 and the re-emit may be silent. Check `ctx.state === "running"`, `await ctx.resume()`. |
| D2 | `offscreen.js:50-57` | Audio is buffered in `chunks` and turned into one Blob at `stop()`. A 2 h lecture at 64 kbps is ~57 MB; any throw before `new Blob` yields **zero bytes** — the exact v1 symptom. Write per-chunk instead. |
| D3 | `offscreen.js:57-59` | `bytes === 0` is indistinguishable from "the track was muted and the recorder emitted nothing". `MediaRecorder` produces no data for a silent/muted track, so a live recorder object can still write 0 bytes. State must be proven by sample RMS, not by `rec` existing. |
| D4 | `sw.js:84-90`, `96-101` | `start(next.id)` after the target closes/navigates has **no user gesture**, so `getMediaStreamId({targetTabId})` fails: the docs say target tabs require an `activeTab` grant, which is obtained by invoking the extension. Auto-follow silently stops recording. Replace with stop + `needs:["user-gesture"]`. |
| D5 | `sw.js:73-82` | `recordings` read-modify-write is racy and `msg.meta` is unvalidated. Write one key per recording (`recording:<name>`). |
| D6 | `manifest.json` | No `default_popup` (the UI ask), no `minimum_chrome_version`, no `host_permissions`. `hasDocument()` (`sw.js:19`) is Chrome 150+; `runtime.getContexts()` is the 116+ documented way. |
| D7 | `offscreen.js:73-82` | Anchor click ignores any folder choice and lands in the profile Downloads dir. That is why a folder setting cannot be built on `chrome.downloads` either: the SW cannot use a blob URL minted in another document, and messages cannot carry a Blob. |

Cited below (all under `developer.chrome.com/docs/extensions`): tabCapture needs invocation and
`targetTabId` needs `activeTab` (`/reference/api/tabCapture`); a SW stream ID works in an offscreen
document from Chrome 116 (`/how-to/web-platform/screen-capture`); the SW dies after 30 s idle, alarms
min 30 s, WebSocket traffic resets the timer from Chrome 116
(`/develop/concepts/service-workers/lifecycle`); offscreen documents get **only** `chrome.runtime`
and, apart from `AUDIO_PLAYBACK`, "don't set lifetime limits" (`/reference/api/offscreen`).

## 1. Control channels

| | What it makes possible | What it costs | What breaks when the SW sleeps |
|---|---|---|---|
| **Native messaging** | Extension spawns a local process on demand; no host permission; process can do anything on the machine. | Host manifest on disk **plus** `HKCU\Software\Google\Chrome\NativeMessagingHosts\<name>`; the manifest pins the extension ID, so `key` must be added to `manifest.json` and the ID frozen; 1 MB/frame; stdio JSON framing; the host is a child of the port. | Port closes → host exits. Reconnect needs an alarm (≥30 s) or a live page, so command latency after a break is up to 30 s. An *open* port does keep the SW alive (Chrome 105+). |
| **Local WebSocket bridge** (extension dials `127.0.0.1`) | Instant push both ways, unlimited message size, same port can serve HTTP for the CLI and a page, daemon outlives the browser so it can report "browser closed". | One Python file to run (shortcut / Task Scheduler). Extension must reach `ws://127.0.0.1:PORT`; whether that needs `host_permissions` is **unverified** (CSP `connect-src`, not CORS). | Nothing, if the socket lives in the offscreen document (no idle lifetime limit) — the recorder and the channel survive SW death. If it lives in the SW, Chrome 116+ keeps it alive while messages flow within 30 s. |
| **CDP attach** (`chrome.debugger`) | Full DevTools protocol on any tab; no changes to the extension. | `debugger` permission warning, an infobar on every attach, and **no audio capture domain at all** — it can script the page but not record it. | Detach on SW death (Chrome 118+ keeps the SW alive while attached). Infobar is unacceptable during a lecture. |

## 2. Recommended design

**One Python process (`tools/tabrec.py serve`) is the control plane; the extension dials it over
WebSocket from the offscreen document.** It is the only option that gives the CLI, a page and the
agent one instant, browser-independent view of state, and it puts the socket in the context that
also owns the recorder, so SW sleep stops being a design problem.

Rejected: **native messaging** — a registry key, a frozen extension ID and a spawn-per-connection
lifecycle buy nothing once a daemon exists, and it cannot report state while the browser is closed.
**CDP** — cannot capture audio, and its infobar is a lecture-room liability.

```
manifest.json     + default_popup, + minimum_chrome_version "116", permissions unchanged
sw.js             thin relay: gesture, getMediaStreamId, badge, alarm self-heal
offscreen.js      live context: WS client + state machine + MediaRecorder + analyser + FSA writer
popup.html/.js    UI: state, level, start/stop, folder pick, folder re-grant
tools/tabrec.py   daemon (`serve`) + CLI (`status|start|stop|watch`), stdlib + websockets 15.0.1
```

State is authoritative in the offscreen document, mirrored to `chrome.storage.session` (cleared on
browser restart — correct, a recording cannot outlive the browser), and pushed to the daemon, which
is stateless and rebuilds from `hello`, so restarting it is harmless.
`chrome.alarms.create({periodInMinutes: 0.5})` + `runtime.onStartup` call `ensureOffscreen()` so a
closed offscreen document returns within 30 s; the SW is otherwise not kept awake.

## 3. UI

`action.default_popup` replaces `action.onClicked` (opening the popup *is* the invocation that
`tabCapture` needs — needs test, with `getMediaStreamId` called in the popup as the fallback).

First 500 ms: the popup paints synchronously from a cached `chrome.storage.session` snapshot
(`recording`, `startedAt`, `bytes`, `level`, `folder`), so it is never wrong; only the meter is
marked `stale` until the first live sample (~100 ms). Until the snapshot resolves the dot is grey
and **both Start and Stop are disabled** — defaulting to "idle" would offer Start mid-recording.

| Row | Shows | Proof it is real |
|---|---|---|
| Header | grey `checking` → green `idle` / red `recording 00:12:41` | text from state, not a timer guess |
| Meter | dBFS bar + peak hold, 4 Hz | RMS from `AnalyserNode` on the re-emit graph (`offscreen.js:45`) |
| Sink | `lectures/tab-….webm · 6.1 MB · writing` | `bytesWritten` grows every 1 s (D2 fixed) |
| Tab | title + URL of the captured tab | `chrome.tabs.get(target)` |
| Folder | `lectures · granted` or `… · expired` + **Reconnect** | `handle.queryPermission()` |
| Buttons | Start / Stop / Pick folder | disabled while `state === unknown` |

Silent-but-recording renders as `recording · no signal` (meter flat), which is a different, honest
message from `recording`. Badge stays `REC`/`ERR`/`OK` as a second, glanceable channel.

## 4. Folder selection

`showDirectoryPicker({id:"tabrec-recordings", mode:"readwrite"})` in the **popup** (the only
context with a user gesture), then store the `FileSystemDirectoryHandle` in IndexedDB
(`tabrec` DB, store `handles`, key `dir`) in the extension origin — shared by popup and offscreen.
The offscreen document reads the handle from IndexedDB and, on each `dataavailable`, writes to an
open `createWritable()` stream; `close()` on stop. No `downloads` permission, arbitrary folder,
memory bounded.

Fresh browser start: the handle is still in IndexedDB, the permission is not — "access lasts until
you close the last tab of the origin"; persistence needs the Chrome 122+ three-way prompt ("Allow on
every visit") or an installed app
(<https://developer.chrome.com/blog/persistent-permissions-for-the-file-system-access-api>).
So `queryPermission({mode:"readwrite"})` returns `"prompt"`, `createWritable()` throws
`NotAllowedError`, the offscreen document cannot call `requestPermission()` (no transient
activation), and `start` returns `E_FOLDER_PERMISSION`: the popup shows **Reconnect**, the CLI
reports `needs:["folder-permission"]` and cannot fix it. That is the one unavoidable human click.
Until a folder is granted the v1.1 anchor click (`offscreen.js:73-82`) still writes to Downloads;
it is kept as that branch only.

## 5. CLI — `tools/tabrec.py`

```
python tools/tabrec.py serve  [--port 8765]   # daemon: WS /ext, WS /events, GET /state, POST /cmd, GET / (page)
python tools/tabrec.py status  [--json]
python tools/tabrec.py start   [--tab <id>]   # default: active tab
python tools/tabrec.py stop
python tools/tabrec.py watch                  # reads WS /events, prints NDJSON per change
```

`GET /state` and every reply body:

```json
{"ext":"connected|disconnected","extVersion":"1.2","lastSeen":"2026-11-10T14:40:12Z",
 "recording":true,"tab":{"id":123,"title":"…","url":"https://meet.google.com/…"},
 "startedAt":"2026-11-10T14:40:12Z","elapsedMs":12345,
 "bytes":983040,"level":0.07,"peak":0.31,
 "folder":{"name":"lectures","permission":"granted|prompt|denied"},
 "file":{"name":"tab-2026-11-10T14-40-12.webm","bytesWritten":983040},
 "needs":[],"lastError":null}
```

`POST /cmd` `{"cmd":"start","args":{"tabId":123}}` → `{"ok":true,"state":{…}}` or
`{"ok":false,"error":{"code":"E_NEEDS_GESTURE","message":"click the toolbar icon on that tab once"}}`.
Codes: `E_NO_EXT`, `E_NEEDS_GESTURE`, `E_FOLDER_PERMISSION`, `E_ALREADY_RECORDING`,
`E_NOT_RECORDING`, `E_TAB_GONE`, `E_CAPTURE`. Exit codes: 0 ok, 2 usage, 3 daemon down,
4 extension disconnected, 5 rejected (code on stderr).

Wire protocol: extension→daemon `{"t":"hello","state":{…}}`, `{"t":"state","state":{…}}` (on change,
1 Hz while recording), `{"t":"reply","id":7,"ok":true,"data":{…}}`; daemon→extension
`{"t":"cmd","id":7,"cmd":"start","args":{…}}`, `{"t":"ping"}`. `/events` clients receive the same
`{"t":"state"}` frames — that is what `watch` and the page read.

Browser closed: `serve` stays up, `/state` reports `ext:"disconnected"` + `lastSeen`, `start` exits
4 with `E_NO_EXT`. The CLI cannot launch the browser and does not try.

Trust boundary: bind `127.0.0.1` only, require `Content-Type: application/json` on `POST` (forces a
preflight, so no cross-origin page can drive it), reject a `Host` that is not `127.0.0.1`/`localhost`
(DNS rebinding). No token: the page is served by the daemon itself, so it is same-origin.

## 6. Build order

1. **Channel, one sitting.** `tools/tabrec.py serve` (WS `/ext` + `GET /state`) and ~25 lines in
   `offscreen.js` that connect, send `hello` and re-push `state`; `sw.js` gains `ensureOffscreen()`
   on `onStartup`/alarm. `tabrec status` prints `ext:"connected"` — the one unknown that can sink
   the design: can an offscreen document hold `ws://127.0.0.1`.
2. State snapshot + 1 Hz push + `tabrec watch`. No commands yet.
3. `start`/`stop` through the daemon with the error codes; keep the existing capture path; fix D1
   and add the analyser. **This is where "does v1.1 record at all" gets answered** (see 7.3).
4. Popup: paint-from-cache, meter, Start/Stop, badge unchanged. Delete `action.onClicked`.
5. Folder: IDB handle, chunked FSA writes (D2), permission state, anchor fallback, `Reconnect`.
6. Cleanup: D4 (drop auto-follow), D5, `minimum_chrome_version`, `runtime.getContexts`, README
   status rewrite, `websockets==15.0.1` in `requirements.txt`.

## 7. Verification, each under a minute

1. **Channel:** `tabrec serve` in one shell, reload the extension → `tabrec status` shows
   `connected` in <5 s. Fails ⇒ `host_permissions` question answered, add `"http://127.0.0.1/*"`.
2. **Survives sleep:** leave it 3 min untouched, `tabrec status` still `connected`; `tabrec stop`
   with nothing recording returns `E_NOT_RECORDING` in <1 s (not 30 s).
3. **Capture (the v1 question):** tab playing audio, Start, `tabrec watch` → `level > 0.01` within
   2 s and `bytes` rising ≈8 KB/s. `recording:true` with `level:0` ⇒ D1/D3, not the sink.
4. **Folder:** pick a folder, record 10 s, stop, `ls` → one `.webm`; `ffprobe -show_entries
   format=duration` ≈ 10.
5. **Restart:** close and reopen the browser → `status` shows `needs:["folder-permission"]`,
   `start` exits 5; click Reconnect; `start` succeeds.
6. **Browser closed:** quit the browser → `start` exits 4, `status` shows `lastSeen`.
7. **Real audio:** play the file; a flat waveform means the re-emit graph was wrong, not the file.

## 8. Risks and what stays unverified here

- **The CLI cannot create a user gesture.** `start` only works for a tab the extension was invoked
  on during the current page load; `chrome.commands` (one keystroke, no popup) is the mitigation, and
  a CLI-only start of an arbitrary tab is impossible by design of `tabCapture`. Needs test: whether
  the popup's invocation lets the SW call `getMediaStreamId` (fallback: call it in the popup).
- Unverified on this machine (Chrome 157 / Brave 157 installed): WS to `127.0.0.1` without host
  permission; an unpacked extension getting the three-way persistent FSA prompt; whether
  `getFile().size` reflects in-progress writes; that a USER_MEDIA offscreen document is never
  idle-killed over 2 h; that an anchor click downloads without a gesture (D7 fallback); Shields.
- MediaRecorder writes WebM without a duration header; a 2 h file needs a remux before the pipeline
  consumes it (`ffmpeg -i x.webm -c copy x.m4a`) — that belongs in the pipeline, not the extension.
- The daemon's 1 Hz push is convenience, not durability: if the daemon dies mid-lecture the
  extension keeps recording (sink is local), and `status` afterwards reads `chrome.storage.session`
  only until the browser closes.
- Not attempted: diarization, slide sync, remote (non-localhost) web control, two simultaneous
  captures. Tab capture still misses a Meet presentation opened as a separate window.
