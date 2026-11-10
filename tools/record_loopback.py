#!/usr/bin/env python
"""Record the Windows output mix to WAV via WASAPI loopback.

Captures what the machine plays - a Google Meet lecture - with no bot, no
microphone and no cloud service. Writes 16-bit PCM, and follows the default
output device when it changes (headphones plugged in, Bluetooth connected),
because a stream pinned to the old endpoint records silence.

    python tools/record_loopback.py                  # audio/rec-<stamp>.wav
    python tools/record_loopback.py --duration 600   # stop after 10 min
    python tools/record_loopback.py --list

Ctrl-C closes the file cleanly.

The stream is a callback, not a blocking read: WASAPI loopback returns
silence when the endpoint is idle and blocks forever if the audio engine
suspends, which would hang a blocking reader at the end of a call.

shortcut: a device with a different rate is resampled with linear
interpolation, no anti-alias filter. Fine for speech; upgrade to a proper
resampler if music ever matters.
shortcut: a hard kill (not Ctrl-C) leaves the WAV header unwritten, so the
file is unreadable. Upgrade to segmented parts if unattended recordings start
to matter.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio

BLOCK = 1024
SILENCE_RMS = 1e-4
POLL = 1.0


def resolve_loopback(audio: pyaudio.PyAudio, index: int | None) -> dict | None:
    """The default endpoint's loopback, or None if Windows is mid-switch.

    Returning None matters: falling back to the first loopback device is how a
    Bluetooth transition silently reopens the speakers endpoint.
    """
    if index is None:
        try:
            return audio.get_default_wasapi_loopback()
        except Exception:
            return None
    for i in range(audio.get_device_count()):
        d = audio.get_device_info_by_index(i)
        if d.get("isLoopbackDevice") and d["index"] == index:
            return d
    raise SystemExit(f"no loopback device with index {index}")


def list_devices(audio: pyaudio.PyAudio) -> None:
    for i in range(audio.get_device_count()):
        d = audio.get_device_info_by_index(i)
        if d.get("isLoopbackDevice"):
            print(f"[{d['index']:>3}] {d['name']}  {d['defaultSampleRate']:.0f} Hz  "
                  f"{d['maxInputChannels']} ch")


def fit(a: np.ndarray, src_ch: int, src_rate: int, base_ch: int, base_rate: int) -> np.ndarray:
    """Reshape one int16 block to the file's fixed channel count and rate."""
    if a.size == 0:
        return a
    frames = a.size // src_ch
    if frames == 0:
        return np.empty(0, dtype=np.int16)
    m = a[:frames * src_ch].reshape(frames, src_ch).astype(np.int16)
    if src_ch != base_ch:
        m = np.repeat(m, base_ch, axis=1) if base_ch > src_ch else m[:, :base_ch]
    if src_rate != base_rate and frames > 1:
        n = max(1, int(round(frames * base_rate / src_rate)))
        idx = np.linspace(0, frames - 1, n)
        m = m[idx.astype(np.int64)]
    return m.reshape(-1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", type=Path, help="output .wav (default audio/rec-<stamp>.wav)")
    ap.add_argument("--duration", type=float, default=0, help="seconds; 0 = until Ctrl-C")
    ap.add_argument("--device-index", type=int, help="loopback device index (see --list); "
                                                    "omitted = follow the default output")
    ap.add_argument("--list", action="store_true", help="list loopback devices and exit")
    args = ap.parse_args()

    audio = pyaudio.PyAudio()
    if args.list:
        list_devices(audio)
        audio.terminate()
        return 0

    dev = resolve_loopback(audio, args.device_index)
    base_rate = int(dev["defaultSampleRate"])
    base_ch = max(1, int(dev["maxInputChannels"]))
    out = args.out or Path("audio") / f"rec-{datetime.now():%Y%m%d-%H%M%S}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)

    w = wave.open(str(out), "wb")
    w.setnchannels(base_ch)
    w.setsampwidth(2)
    w.setframerate(base_rate)

    lock = threading.Lock()
    level = [0.0]
    loudest = [0.0]
    written = [0]

    def make_cb(srate: int, sch: int):
        def on_audio(in_data, frame_count, time_info, status):
            a = fit(np.frombuffer(in_data, dtype=np.int16), sch, srate, base_ch, base_rate)
            if a.size:
                with lock:
                    w.writeframes(a.tobytes())
                    written[0] += a.size // base_ch
                rms = float(np.sqrt((a.astype(np.float32) / 32768.0) ** 2).mean())
                level[0] = rms
                if rms > loudest[0]:
                    loudest[0] = rms
            return (None, pyaudio.paContinue)
        return on_audio

    def start(d: dict) -> tuple:
        r, c = int(d["defaultSampleRate"]), max(1, int(d["maxInputChannels"]))
        s = audio.open(format=pyaudio.paInt16, channels=c, rate=r, input=True,
                       input_device_index=d["index"], frames_per_buffer=BLOCK,
                       stream_callback=make_cb(r, c))
        s.start_stream()
        return s, r, c

    stream, srate, sch = start(dev)
    print(f"recording {dev['name']} @ {srate} Hz {sch} ch -> file {base_rate} Hz {base_ch} ch -> {out}")
    print("Ctrl-C to stop. Keep the Windows volume above zero; mute inside Meet instead.")

    started = time.monotonic()
    silent_from = [0.0]
    silent_warned = [False]
    try:
        while args.duration == 0 or time.monotonic() - started < args.duration:
            time.sleep(POLL)
            elapsed = time.monotonic() - started
            if args.device_index is None:
                cur = resolve_loopback(audio, None)
                if cur is not None and cur["index"] != dev["index"]:
                    # Stop outside the lock: stop_stream waits for the callback,
                    # which needs the lock to write. Holding it here deadlocks.
                    old, stream = stream, None
                    old.stop_stream()
                    old.close()
                    dev = cur
                    stream, srate, sch = start(dev)
                    print(f"\n  output device changed -> {dev['name']} @ {srate} Hz {sch} ch",
                          flush=True)
            deficit = int(elapsed * base_rate) - written[0]
            if deficit > base_rate // 4:
                # The endpoint stops delivering frames when nothing renders;
                # pad so file time stays equal to lecture time.
                with lock:
                    w.writeframes(b"\x00\x00" * (deficit * base_ch))
                    written[0] += deficit
                level[0] = 0.0
            db = 20 * np.log10(level[0]) if level[0] > 0 else -120.0
            print(f"\r  {int(elapsed)//60:02d}:{int(elapsed)%60:02d}  {db:6.1f} dBFS",
                  end="", flush=True)
            if level[0] < SILENCE_RMS:
                if silent_from[0] == 0.0:
                    silent_from[0] = elapsed
                elif elapsed - silent_from[0] > 30 and not silent_warned[0]:
                    silent_warned[0] = True
                    print("\n  30s of silence - check the Windows volume slider and the "
                          "Meet mute; the file is still being written.", file=sys.stderr, flush=True)
            else:
                silent_from[0] = 0.0
                silent_warned[0] = False
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()
        w.close()

    secs = time.monotonic() - started
    drift = written[0] / base_rate - secs
    peak_db = 20 * np.log10(loudest[0]) if loudest[0] else -120.0
    print(f"\nwrote {out}  {secs/60:.1f} min  {out.stat().st_size/1e6:.0f} MB  "
          f"peak {peak_db:.1f} dBFS  drift {drift:+.2f}s")
    if abs(drift) > 1.0:
        print(f"file time is {drift:+.1f}s off wall clock - timestamps after the "
              f"offending gap will be wrong.", file=sys.stderr)
    if loudest[0] < SILENCE_RMS:
        print("file is silent - nothing was playing, or the driver dropped the loopback.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
