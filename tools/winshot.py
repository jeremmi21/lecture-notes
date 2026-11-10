"""Grab a window's contents by title, even when it is behind another window.

    python tools/winshot.py --list
    python tools/winshot.py --title "Presentation window" -o slides/pres.jpg
    python tools/winshot.py --title "Presentation window" --interval 10 --duration 3600

PrintWindow asks the window to render itself, so the result does not depend on
what is on top of it. That is the whole point: a desktop grab captures YouTube.
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 0x2


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def windows() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.strip():
                    found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(proc(cb), 0)
    return found


def find(title: str) -> int | None:
    for hwnd, name in windows():
        if title.lower() in name.lower():
            return hwnd
    return None


def grab(hwnd: int) -> Image.Image | None:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None

    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None
    mfc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    previous = gdi32.SelectObject(mfc, bmp)
    ok = user32.PrintWindow(hwnd, mfc, PW_RENDERFULLCONTENT)

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mfc, bmp, 0, h, buf, ctypes.byref(info), 0)

    gdi32.SelectObject(mfc, previous)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mfc)
    user32.ReleaseDC(hwnd, hdc)

    if not got or not ok:
        return None
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--title", default="Presentation window")
    ap.add_argument("-o", "--out", type=Path, default=Path("slides/pres.jpg"))
    ap.add_argument("--interval", type=float, default=0, help="seconds; 0 = one shot")
    ap.add_argument("--duration", type=float, default=0, help="seconds; 0 = until Ctrl-C")
    args = ap.parse_args()

    if args.list:
        for hwnd, name in windows():
            print(hwnd, name)
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # Frames are named by elapsed seconds; this anchors them to the wall clock so
    # they can be matched to transcript timestamps.
    args.out.with_name("started.txt").write_text(
        datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    saved = 0
    while True:
        hwnd = find(args.title)
        if hwnd is None:
            print(f"no window matching {args.title!r}", file=sys.stderr)
            if not args.interval:
                return 1
        else:
            img = grab(hwnd)
            if img is not None:
                target = args.out if not args.interval else \
                    args.out.with_name(f"{args.out.stem}-{int(time.monotonic() - started):05d}.jpg")
                img.convert("RGB").save(target, quality=80)
                saved += 1
                print(f"{target}  {img.width}x{img.height}", flush=True)
        if not args.interval:
            return 0 if saved else 1
        if args.duration and time.monotonic() - started >= args.duration:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
