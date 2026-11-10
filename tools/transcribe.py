"""Transcribe one recording to timestamped JSON.

    python tools/transcribe.py lecture.wav -o lecture.transcript.json

The contract with the rest of the pipeline is the JSON shape:
{"segments": [{"start": float, "end": float, "text": str}, ...]}

Uses faster-whisper on the CPU. Decoding is done by ffmpeg, so any container
ffmpeg reads works; the model always sees 16 kHz mono PCM.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


def decode(path: Path, rate: int = 16000) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le",
         "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(rate), "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--model", default="small")
    ap.add_argument("--beam-size", type=int, default=5)
    ap.add_argument("--threads", type=int, default=0, help="0 = all logical cores")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    out = args.out or args.audio.with_suffix(".transcript.json")
    started = time.monotonic()

    samples = decode(args.audio)
    if samples.size == 0:
        print("no audio decoded", file=sys.stderr)
        return 1

    threads = args.threads or 0
    model = WhisperModel(args.model, device="cpu", compute_type="int8",
                         cpu_threads=threads or 0)

    segments, info = model.transcribe(
        samples, beam_size=args.beam_size, vad_filter=True, language=None,
    )
    rows = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments]

    payload = {
        "source": args.audio.name,
        "model": args.model,
        "language": info.language,
        "duration": round(samples.size / 16000.0, 2),
        "segments": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    elapsed = time.monotonic() - started
    covered = rows[-1]["end"] if rows else 0.0
    print(f"{out}  {len(rows)} segments  covered {covered:.0f}s of {payload['duration']:.0f}s  "
          f"{payload['duration'] / elapsed:.2f}x realtime")

    if payload["duration"] - covered > 60:
        print(f"warning: last segment ends {payload['duration'] - covered:.0f}s before the "
              f"end of the audio - the tail may be missing.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
