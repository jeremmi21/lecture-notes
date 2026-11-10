"""Match slide frames to lecture time, and attach them to graph topics.

    python tools/sync_slides.py lectures/<id>

Needs three things that were all written by the capture tools:

    <lecture>.wav.meta.json   started_at, written by record_loopback.py
    slides/started.txt        ISO time, written by winshot.py
    slides/pres-NNNNN.jpg     frame N is N seconds after started.txt
    graph.json                topics with start/end in seconds

Writes slides.index.json beside the graph and prints a table. Nothing is
inferred: if a marker is missing, this refuses rather than guessing an offset.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

FRAME = re.compile(r"^pres-(\d+)\.jpg$", re.IGNORECASE)


def iso(text: str) -> datetime:
    return datetime.fromisoformat(text.strip())


def mmss(seconds: float) -> str:
    s = int(max(0, seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    lecture = Path(sys.argv[1])
    graph_path = lecture / "graph.json"
    slides = lecture / "slides"

    meta_files = list(lecture.glob("*.wav.meta.json"))
    if not meta_files:
        print(f"no *.wav.meta.json in {lecture} - the recorder writes it at start", file=sys.stderr)
        return 1
    meta = json.loads(meta_files[0].read_text(encoding="utf-8"))

    marker = slides / "started.txt"
    if not marker.exists():
        print(f"no {marker} - winshot.py writes it when a slide loop starts", file=sys.stderr)
        return 1

    audio_start = iso(meta["started_at"])
    slide_start = iso(marker.read_text(encoding="utf-8"))
    skew = (slide_start - audio_start).total_seconds()

    frames = {int(m.group(1)): f for f in slides.iterdir() if (m := FRAME.match(f.name))}
    if not frames:
        print(f"no pres-<seconds>.jpg frames in {slides}", file=sys.stderr)
        return 1

    topics = []
    if graph_path.exists():
        g = json.loads(graph_path.read_text(encoding="utf-8"))
        topics = [n for n in g["nodes"] if n["type"] == "topic"]

    index = []
    for t in topics:
        inside = [s for s in frames if t["start"] <= skew + s < t["end"]]
        index.append({
            "topic": t["id"],
            "label": t["label"],
            "start": t["start"],
            "end": t["end"],
            "frames": sorted(inside),
            "first_frame_offset": round(skew + min(inside), 1) if inside else None,
        })

    out = lecture / "slides.index.json"
    out.write_text(json.dumps({
        "audio_started_at": meta["started_at"],
        "slides_started_at": slide_start.isoformat(timespec="seconds"),
        "skew_s": round(skew, 1),
        "frame_count": len(frames),
        "topics": index,
    }, indent=1), encoding="utf-8")

    print(f"audio started  {meta['started_at']}")
    print(f"slides started {slide_start.isoformat(timespec='seconds')}  "
          f"({skew:+.1f}s relative to the audio)")
    print(f"{len(frames)} frames over {mmss(max(frames) - min(frames))}\n")
    for row in index:
        span = f"{mmss(row['start'])}-{mmss(row['end'])}"
        n = len(row["frames"])
        print(f"  {span}  {n:>3} frames  {row['label'][:52]}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
