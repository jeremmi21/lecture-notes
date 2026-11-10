# Advanced options

Neither of these is required. Both were evaluated on paper and neither was
measured on the machine this repo was written for.

## Speaker labels

The pipeline records the output mix, so a transcript has no idea who spoke. The
participation marks and student questions are lost in one undifferentiated
stream.

[Desert Ant Labs **Who**](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/main/docs/models/who.md)
is an on-device diarization model: 32 MB int8, per-speaker turns with
timestamps, no length limit. Published error rate is 12.6 % on headset meetings,
7.7 % with one or two speakers — which is the shape of a lecture.

There is no Python binding. The usable route on Windows is Node:

```bash
npm i @desert-ant-labs/who
```

```js
import { Who } from "@desert-ant-labs/who/native";
const who = await Who.load();
const result = await who.diarize("lecture.wav");
result.turns.forEach(t => console.log(t.speaker, t.start, t.end));
```

Then join the turns against `transcript.json` segments by time overlap, and add
`speaker` to each segment. That is the whole integration: one script that reads
two JSON files and writes a third.

**Cost:** the audio must still exist. This repo deletes the WAV once the
transcript is verified, so diarization has to run before deletion.

**Worth it for:** a seminar with several speakers. **Not worth it for:** one
lecturer talking for two hours.

## Faster engine

[Desert Ant Labs **Voz**](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/main/docs/models/voz.md)
is NVIDIA Parakeet TDT 0.6B v3 repackaged: 337 MB, 6.43 % word error against
Whisper large-v3-turbo's 7.00 %, word timestamps to 80 ms, and a `vocabulary`
list that fixes exactly the failure this pipeline hits — proper names.

```python
voz.transcribe(url, vocabulary=["Acme Corp", "Smith v Jones", "Section 12"])
```

**Why it isn't the default:**

- Every published speed is a Neural Engine number. On Windows it needs the
  Swift SDK plus ONNX Runtime + DirectML, and a machine whose GPU is already
  refused by CTranslate2 will not be faster by magic.
- Under Node it runs on the CPU with `onnxruntime-node`, which the docs describe
  as slower than a browser on the same machine.
- The licence is source-available, free for most apps, commercial at scale.

**Before adopting it,** measure `realtimeFactor` on your own hardware with your
own lecture audio. The existing pipeline does two hours in 51 minutes; a
replacement has to beat that on this CPU, not on an M5.

## Cheaper than both

Pass the genre's names to the recogniser you already have:

```python
segments, _ = model.transcribe(samples, beam_size=5, hotwords="Acme Corp Smith v Jones")
```

One line, no new toolchain. It does not add words that were not spoken, and it
turns a mangled rendering of a party name back into the name you supplied.
Try this first.
