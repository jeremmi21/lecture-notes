"""Render notes.md from a lecture graph.

    python tools/render_notes.py lectures/<id>/graph.json

Keeps the notes a view of the graph, so fixing a rule fixes the note. No model
call: anything not in the graph is not in the notes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def main() -> int:
    path = Path(sys.argv[1])
    g = json.loads(path.read_text(encoding="utf-8"))

    nodes = {n["id"]: n for n in g["nodes"]}
    topics = [n for n in g["nodes"] if n["type"] == "topic"]
    cases = {n["id"]: n for n in g["nodes"] if n["type"] == "case"}
    by_rule: dict[str, list[str]] = {}
    for e in g["edges"]:
        if e["type"] == "illustrates":
            by_rule.setdefault(e["to"], []).append(e["from"])

    lect = g["lecture"]
    out: list[str] = []
    out.append(f"# {lect['course']} — {lect['date']}\n")
    out.append(f"{lect['duration_s'] // 60} minutes. {len(topics)} topics, "
               f"{sum(1 for n in g['nodes'] if n['type'] == 'rule')} rules, "
               f"{len(cases)} cases. Times are recording offsets.\n")

    if g.get("contaminated"):
        out.append("**Skip:** " + "; ".join(
            f"{mmss(c['start'])}–{mmss(c['end'])} {c['note']}" for c in g["contaminated"]) + "\n")
    if g.get("excluded"):
        out.append("**Excluded:** " + "; ".join(
            f"{mmss(e['start'])}–{mmss(e['end'])} {e['note']}" for e in g["excluded"]) + "\n")

    out.append("## Index\n")
    out.append("| Topic | Span | Rules | Cases |")
    out.append("|---|---|---|---|")
    for t in topics:
        rules = [n for n in g["nodes"] if n.get("topic") == t["id"]]
        cs = sorted({c for r in rules for c in by_rule.get(r["id"], [])})
        names = ", ".join(cases[c]["label"] for c in cs) or "—"
        out.append(f"| {t['label']} | {mmss(t['start'])}–{mmss(t['end'])} | {len(rules)} | {names} |")
    out.append("")

    for t in topics:
        out.append(f"## {t['label']}  `{mmss(t['start'])}`\n")
        for n in sorted((x for x in g["nodes"] if x.get("topic") == t["id"]),
                        key=lambda x: x["start"]):
            out.append(f"- **{n['label']}**  `{mmss(n['start'])}`")
            for c in by_rule.get(n["id"], []):
                case = cases[c]
                out.append(f"  - *{case['label']}* — {case['facts']} **Held:** {case['holding']}")
        out.append("")

    if g.get("unverified"):
        out.append("## Check before citing\n")
        out.append("These were spoken but did not appear verbatim in the transcript; "
                   "the automatic speech recogniser is unreliable on proper names.\n")
        for u in g["unverified"]:
            out.append(f"- {u}  `[ASR-unverified]`")
        out.append("")

    target = path.with_name("notes.md")
    target.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {target}  {len(out)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
