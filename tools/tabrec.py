"""Control plane for the tab-recorder extension.

    python tools/tabrec.py serve          # daemon on 127.0.0.1:8765
    python tools/tabrec.py status [--json]
    python tools/tabrec.py start [--tab ID]
    python tools/tabrec.py stop
    python tools/tabrec.py watch          # NDJSON, one line per state change

The extension holds one Server-Sent Events stream for commands and posts its
state back, so there is no WebSocket parsing and no dependency beyond the
standard library. Bind to loopback only.

The daemon is stateless between runs: it rebuilds from the extension's hello,
so restarting it mid-lecture loses nothing that matters. The recorder keeps
running because the sink is local.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8765
EMPTY_STATE = {
    "ext": "disconnected",
    "extVersion": None,
    "lastSeen": None,
    "recording": False,
    "tab": None,
    "startedAt": None,
    "elapsedMs": 0,
    "bytes": 0,
    "level": 0.0,
    "folder": {"name": None, "permission": "unknown"},
    "file": None,
    "needs": [],
    "lastError": None,
}


class Hub:
    """Shared state: last state from the extension, plus one queue per SSE client."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = dict(EMPTY_STATE)
        self.version = 0
        self.live = False
        self.listeners: list[queue.Queue] = []

    def update(self, patch: dict, *, mark_live: bool = True) -> dict:
        with self.lock:
            if mark_live:
                self.state["ext"] = "connected"
                self.state["lastSeen"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.state.update(patch)
            self.state["elapsedMs"] = (
                max(0, int((time.time() - self.started_epoch()) * 1000))
                if self.state.get("startedAt") else 0
            )
            self.version += 1
            snapshot = dict(self.state)
            listeners = list(self.listeners)
        for q in listeners:
            q.put(snapshot)
        return snapshot

    def started_epoch(self) -> float:
        raw = self.state.get("startedAt")
        if not raw:
            return time.time()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return time.time()

    def timeout(self) -> None:
        with self.lock:
            self.state["ext"] = "disconnected"
            self.state["recording"] = False
            self.version += 1

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.state)


class Handler(BaseHTTPRequestHandler):
    server_version = "tabrec/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def hub(self) -> Hub:
        return self.server.hub  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:  # quiet
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _local_only(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self._json(403, {"ok": False, "error": {"code": "E_HOST", "message": "loopback only"}})
            return False
        return True

    def do_GET(self) -> None:
        if not self._local_only():
            return
        if self.path.startswith("/state"):
            state = self.hub.snapshot()
            if (
                state.get("ext") == "connected"
                and state.get("lastSeen")
                and (time.time() - self._seen_epoch()) > 10
            ):
                self.hub.timeout()
            return self._json(200, self.hub.snapshot())
        if self.path.startswith("/events"):
            return self._stream()
        if self.path == "/":
            page = b"<!doctype html><meta charset=utf-8><title>tabrec</title><pre id=o>connecting</pre>" \
                   b"<script>const e=new EventSource('/events');e.onmessage=m=>{document.getElementById('o')" \
                   b".textContent=JSON.stringify(JSON.parse(m.data),null,1)}</script>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        self._json(404, {"ok": False, "error": {"code": "E_NOT_FOUND"}})

    def _seen_epoch(self) -> float:
        raw = self.hub.snapshot().get("lastSeen") or ""
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    def _stream(self) -> None:
        q: queue.Queue = queue.Queue()
        with self.hub.lock:
            self.hub.listeners.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b": hello\n\n")
            self.wfile.write(f"data: {json.dumps(self.hub.snapshot())}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    state = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(state)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with self.hub.lock:
                if q in self.hub.listeners:
                    self.hub.listeners.remove(q)

    def do_POST(self) -> None:
        if not self._local_only():
            return
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        if "application/json" not in ctype:
            return self._json(415, {"ok": False, "error": {"code": "E_CONTENT_TYPE"}})
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"ok": False, "error": {"code": "E_JSON"}})

        if self.path == "/ext/state":
            # The extension reporting means it consumed any queued command.
            self.hub.state.pop("pending", None)
            state = self.hub.update(payload)
            return self._json(200, {"ok": True, "version": self.hub.version, "state": state})

        if self.path == "/cmd":
            cmd = payload.get("cmd")
            if cmd not in ("start", "stop", "pick-folder"):
                return self._json(400, {"ok": False, "error": {"code": "E_UNKNOWN_CMD"}})
            state = self.hub.snapshot()
            if state["ext"] != "connected":
                return self._json(409, {"ok": False, "error": {
                    "code": "E_NO_EXT", "message": "extension not connected - open the browser"}})
            if cmd == "start" and state["recording"]:
                return self._json(409, {"ok": False, "error": {"code": "E_ALREADY_RECORDING"}})
            if cmd == "stop" and not state["recording"]:
                return self._json(409, {"ok": False, "error": {"code": "E_NOT_RECORDING"}})
            self.hub.update({"pending": {"cmd": cmd, "args": payload.get("args") or {}}})
            return self._json(200, {"ok": True, "queued": cmd})

        self._json(404, {"ok": False, "error": {"code": "E_NOT_FOUND"}})


def serve(port: int) -> int:
    hub = Hub()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.hub = hub  # type: ignore[attr-defined]
    httpd.daemon_threads = True
    print(f"tabrec listening on http://127.0.0.1:{port}  (state: /state, stream: /events)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def call(port: int, method: str, path: str, payload: dict | None = None, timeout: float = 5.0) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except (urllib.error.URLError, ConnectionError):
        return 0, {"ok": False, "error": {"code": "E_DAEMON_DOWN", "message": "run: tabrec serve"}}


def main() -> int:
    ap = argparse.ArgumentParser(description="Control the tab-recorder extension")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    p_status = sub.add_parser("status")
    p_status.add_argument("--json", action="store_true")
    p_start = sub.add_parser("start")
    p_start.add_argument("--tab", type=int)
    sub.add_parser("stop")
    sub.add_parser("watch")
    args = ap.parse_args()

    if args.cmd == "serve":
        return serve(args.port)

    if args.cmd == "watch":
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/events", timeout=None) as r:
                for line in r:
                    text = line.decode().strip()
                    if text.startswith("data: "):
                        print(text[6:], flush=True)
        except (urllib.error.URLError, ConnectionError):
            print("daemon down - run: tabrec serve", file=sys.stderr)
            return 3
        return 0

    if args.cmd == "status":
        code, payload = call(args.port, "GET", "/state")
        if code == 0:
            print(payload.get("error", {}).get("message", "daemon down"), file=sys.stderr)
            return 3
        if args.json:
            print(json.dumps(payload, indent=1))
        else:
            if payload.get("ext") != "connected":
                print(f"extension   disconnected  (last seen {payload.get('lastSeen') or 'never'})")
                return 4
            enc = "recording" if payload.get("recording") else "idle"
            print(f"extension   connected")
            print(f"state       {enc}  {payload.get('elapsedMs', 0) // 1000}s  "
                  f"{payload.get('bytes', 0) / 1e6:.1f} MB  level {payload.get('level', 0):.2f}")
            print(f"folder      {payload['folder'].get('name')} ({payload['folder'].get('permission')})")
            if payload.get("file"):
                print(f"file        {payload['file'].get('name')}")
            if payload.get("needs"):
                print(f"needs       {', '.join(payload['needs'])}")
            if payload.get("lastError"):
                print(f"error       {payload['lastError']}")
        return 0

    body = {"cmd": args.cmd, "args": {"tabId": args.tab} if getattr(args, "tab", None) else {}}
    code, payload = call(args.port, "POST", "/cmd", body)
    if code == 0:
        print(payload.get("error", {}).get("message", "daemon down"), file=sys.stderr)
        return 3
    if not payload.get("ok"):
        err = payload.get("error", {})
        print(f"{err.get('code')}: {err.get('message', '')}", file=sys.stderr)
        return 4 if err.get("code") == "E_NO_EXT" else 5
    print(f"queued {args.cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
