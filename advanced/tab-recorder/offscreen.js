// Offscreen document: holds the tab stream and the MediaRecorder.
// Service workers cannot call getUserMedia, so the work lives here.

let rec = null;
let stream = null;
let ctx = null;
let chunks = [];
let current = "";
let startedAt = 0;

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.target !== "offscreen") return;
  if (msg.type === "start") {
    start(msg.streamId, msg.filename, msg.startedAt)
      .then(() => reply({ ok: true }))
      .catch((e) => reply({ ok: false, error: String(e) }));
    return true;
  }
  if (msg.type === "stop") {
    stop().then((r) => reply(r));
    return true;
  }
});

async function start(streamId, filename, startedIso) {
  await stop();
  stream = await navigator.mediaDevices.getUserMedia({
    audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
    video: false,
  });
  // Capturing a tab reroutes its audio, so play it back or the user goes deaf.
  ctx = new AudioContext();
  ctx.createMediaStreamSource(stream).connect(ctx.destination);

  chunks = [];
  current = filename;
  startedAt = startedIso ? Date.parse(startedIso) : Date.now();
  rec = new MediaRecorder(stream, {
    mimeType: "audio/webm;codecs=opus",
    audioBitsPerSecond: 64000,
  });
  rec.ondataavailable = (e) => {
    if (e.data && e.data.size) chunks.push(e.data);
  };
  rec.start(1000);
}

async function stop() {
  if (!rec) return { ok: true, bytes: 0 };
  const name = current;
  const ended = new Promise((res) => (rec.onstop = res));
  rec.stop();
  await ended;
  if (stream) stream.getTracks().forEach((t) => t.stop());
  if (ctx) {
    await ctx.close();
    ctx = null;
  }
  const blob = new Blob(chunks, { type: "audio/webm" });
  const bytes = blob.size;
  chunks = [];
  rec = null;
  stream = null;
  if (!bytes) return { ok: true, bytes: 0 };

  // Download from this document, not from the service worker: a blob URL made
  // here is rejected when handed to chrome.downloads in another context.
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoking early cancels an in-flight download.
  setTimeout(() => URL.revokeObjectURL(url), 60000);

  // Wall-clock start, so slide frames can be matched to transcript offsets.
  const meta = {
    filename: name,
    bytes,
    started_at: new Date(startedAt).toISOString(),
    ended_at: new Date().toISOString(),
  };
  await chrome.runtime.sendMessage({ type: "saved", meta }).catch(() => {});
  return { ok: true, bytes };
}
