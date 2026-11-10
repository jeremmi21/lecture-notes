# graph.json

The graph is the artifact. `notes.md` is rendered from it, so a correction made
here survives every re-render.

Every `start` and `end` is a number of **seconds from the beginning of the
recording**, not a clock time and not a formatted string.

## Top level

| Key | Type | Meaning |
|---|---|---|
| `lecture` | object | Metadata. Rendered as the note's title block |
| `nodes` | array | Topics, rules and cases |
| `edges` | array | How nodes relate |
| `unverified` | array of strings | Names that did not appear verbatim in the transcript |
| `contaminated` | array of `{start, end, note}` | Audio inside the recording that is not lecture content |
| `excluded` | array of `{start, end, note}` | Content that is lecture-adjacent but not material: housekeeping, dates, admin |

`contaminated` and `excluded` are printed under the title as **Skip** and
**Excluded**, so a reader knows what was deliberately left out.

## lecture

| Key | Meaning |
|---|---|
| `id` | Stable slug, `course-YYYY-MM-DD` |
| `course` | Human name, used as the note title |
| `date` | `YYYY-MM-DD` |
| `duration_s` | Length of the recording in seconds |
| `source` | Filename the transcript came from |
| `model` | What transcribed it, so an accuracy question has an answer |
| `notes` | Anything uncertain about this recording |

## nodes

Every node needs `id`, `type` and `label`. Ids are referenced by `topic` and by
`edges`, so keep them short and unique (`t.*` topic, `r.*` rule, `c.*` case).

**`topic`** — `start`, `end`. One per section of the lecture, in order.

**`rule`** — `topic`, `start`. One statement the lecturer made, one sentence,
what they actually taught rather than what a textbook says. This is the layer
the note is made of.

**`case`** — `start`, plus `cited_as`, `facts`, `holding`. `cited_as` is how it
was spoken, which is often not how it is written and is the first thing worth
verifying.

## edges

| `type` | Meaning |
|---|---|
| `illustrates` | From a case (or example) to the rule it demonstrates |
| `except` | The source carves an exception out of the target |
| `qualified_by` | The source is limited or extended by the target |
| `contrasts_with` | The two are routinely confused and the lecture separates them |

`illustrates` is the only type the renderer reads: it attaches a case to every
rule it supports. The others are carried for the reader and for any later tool.

## Why the split exists

A transcript is one long stream with a timestamp every few seconds. A graph says
which part of it is a rule, which part is an authority, and what limits what.
The note is then a rendering choice rather than the source of truth — and every
claim in it can be checked against a minute of the recording.
