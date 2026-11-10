// Service worker: one target tab at a time, and it moves to the next tab
// when the target closes or navigates somewhere else.

const MEET = /^https:\/\/meet\.google\.com\//;

async function getTarget() {
  const { target } = await chrome.storage.session.get("target");
  return target ?? null;
}

async function badge(text, colour) {
  await chrome.action.setBadgeText({ text });
  if (colour) await chrome.action.setBadgeBackgroundColor({ color: colour });
}

async function ensureOffscreen() {
  if (chrome.offscreen.hasDocument && (await chrome.offscreen.hasDocument())) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["USER_MEDIA"],
    justification: "Record one tab's audio to a file",
  });
}

async function start(tabId) {
  await badge("...", "#888888");
  try {
    await ensureOffscreen();
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
    const startedAt = new Date().toISOString();
    const stamp = startedAt.replace(/[:.]/g, "-").slice(0, 19);
    const res = await chrome.runtime.sendMessage({
      target: "offscreen",
      type: "start",
      streamId,
      startedAt,
      filename: `tab-${stamp}.webm`,
    });
    if (!res || !res.ok) throw new Error((res && res.error) || "offscreen refused to start");
    await chrome.storage.session.set({ target: tabId, startedAt });
    await badge("REC", "#c0392b");
  } catch (e) {
    // Make the failure visible: without this the badge just never appears.
    console.error("start failed", e);
    await badge("ERR", "#7f1d1d");
    await chrome.storage.session.set({ target: null });
    throw e;
  }
}

async function stop() {
  const id = await getTarget();
  if (id === null) return;
  await chrome.storage.session.set({ target: null });
  const res = await chrome.runtime.sendMessage({ target: "offscreen", type: "stop" }).catch(() => null);
  await badge(res && res.bytes ? "OK" : "0", res && res.bytes ? "#166534" : "#7f1d1d");
  setTimeout(() => badge(""), 8000);
}

async function nextMeetTab() {
  const tabs = await chrome.tabs.query({ url: "https://meet.google.com/*" });
  return tabs.find((t) => t.id !== undefined) || null;
}

chrome.action.onClicked.addListener(async (tab) => {
  if ((await getTarget()) !== null) return void stop();
  try {
    await start(tab.id);
  } catch {
    /* badge already says ERR */
  }
});

chrome.tabs.onRemoved.addListener(async (id) => {
  if (id !== (await getTarget())) return;
  await stop();
  const next = await nextMeetTab();
  if (next) await start(next.id).catch(() => {});
});

chrome.tabs.onUpdated.addListener(async (id, info) => {
  if (id !== (await getTarget())) return;
  if (!info.url || MEET.test(info.url)) return;
  await stop();
  const next = await nextMeetTab();
  if (next) await start(next.id).catch(() => {});
});

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  // The offscreen document cannot call tabCapture itself, so the daemon's
  // "start" command routes through here. NOTE: this needs a user gesture on
  // the target tab; without one Chrome rejects the call, which is why the CLI
  // cannot start an arbitrary tab.
  if (msg && msg.type === "need-stream") {
    chrome.tabCapture
      .getMediaStreamId({ targetTabId: msg.tabId })
      .then((streamId) => {
        const startedAt = new Date().toISOString();
        const stamp = startedAt.replace(/[:.]/g, "-").slice(0, 19);
        reply({ ok: true, streamId, startedAt, filename: `tab-${stamp}.webm` });
      })
      .catch((e) => reply({ ok: false, error: String(e) }));
    return true;
  }
  if (!msg || msg.type !== "saved") return;
  console.log("saved", msg.meta);
  chrome.storage.local.get("recordings").then(({ recordings = [] }) => {
    recordings.push(msg.meta);
    return chrome.storage.local.set({ recordings });
  });
  reply({ ok: true });
  return true;
});
