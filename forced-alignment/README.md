# Word-level SRT generation

Align an existing transcript to an audio file using
[fast-forced-aligner](https://github.com/michsethowusu/fast-forced-aligner).
Each output SRT cue contains one word, with its original casing and punctuation.
The transcript should match what is spoken in the audio.

The main configuration for a **two-core, 8 GB server** is CPU CTranslate2 int8
with **10-second windows, two threads, one active request, streaming audio,
and batch size one**. Both the CLI and
persistent service use these settings from `alignment_config.py`. The service
keeps one model loaded and queues up to four additional requests in arrival
order. Queue capacity and wait timeout are configurable.

## Install

Run these commands yourself in your chosen Python environment:

```sh
python3 -m pip install -r forced-alignment/requirements.txt
```

FFmpeg must also be installed and available on PATH. On macOS with Homebrew,
if FFmpeg is missing:

```sh
brew install ffmpeg
```

The converted model already exists in this workspace. On a new machine, prepare
it once in your chosen Python environment before running the default backend:

```sh
python3 -m ctc_forced_aligner.convert_to_ct2 \
  --model MahmoudAshraf/mms-300m-1130-forced-aligner \
  --output_dir forced-alignment/.cache/mms-300m-ct2-int8 \
  --quantization int8
```

Conversion may download source weights. Normal alignment uses the local cache;
a missing converted model produces an error. `--alignment-model` overrides its
location. The default cache path resolves relative to this script directory,
independently of your working directory.

## Run

From the repository root, supply transcript text directly:

```sh
forced-alignment/.venv/bin/python forced-alignment/generate_srt.py "/path/to/audio.mp3" \
  --transcript "Hello world. This is my transcript." \
  --language eng \
  --output "/path/to/words.srt"
```

Or supply a UTF-8 transcript file:

```sh
forced-alignment/.venv/bin/python forced-alignment/generate_srt.py "/path/to/audio.mp3" \
  --transcript-file "/path/to/transcript.txt" \
  --language eng
```

Choose the ISO 639-3 code for your audio; `eng` in these examples means English.
If `--output` is omitted, the SRT is saved beside the audio with the same stem.
Existing output files are never overwritten; choose a new output path to rerun.

These examples use the installed workspace environment; substitute your own
Python executable if needed. No backend or performance flags are necessary.

For Python callers, `generate_word_srt(audio_path, transcript, language,
output_path=None, alignment_model=None, batch_size=1, lightweight=True,
window_seconds=None, cpu_threads=None, streaming=None)` returns the saved `Path`.
Unspecified performance options resolve to 10 seconds, two threads and streaming.
`write_word_srt` handles subtitle serialization.

The original package backend remains available with `--no-lightweight` (Python:
`lightweight=False`). Its unspecified settings resolve to 30 seconds, backend
threading and buffered decoding. Add `--batch-size 4` to reproduce the original
PyTorch batch setting. For a buffered lightweight comparison, use
`--no-streaming --window-seconds 30 --cpu-threads 0`.

## Behavior and limitations

- Uses the cached multilingual MMS model through the lightweight CPU int8
  backend, without importing PyTorch or Transformers during alignment.
- Processes one 10-second central window at a time with two seconds of context
  on each side, then aligns the entire transcript. Two inference threads serve
  one active request by default. Streaming FFmpeg decoding uses one thread;
  the inference thread setting is not a hard CPU quota for the whole process.
- Produces timestamps from the supplied transcript; it does not transcribe audio.
- Rejects empty transcripts, missing files, and invalid/overlapping word timings
  instead of silently writing misleading subtitles.
- Word splitting follows the package's whitespace-based behavior. The package
  forces character splitting for `jpn`/`chi`, which this word-only script rejects.
- The upstream README lists the default alignment model as CC-BY-NC 4.0
  (non-commercial). Check model suitability before using this in a product.

## Deploy and benchmark on the two-core server

The queue and streaming batch changes are implemented but **have not been run
or tested locally**. The earlier benchmark results below describe the previous
Mac configuration, not verified server performance.

Transfer the Python files in `forced-alignment/`, `requirements.txt`, and the
**entire** `.cache/mms-300m-ct2-int8/` directory, including tokenizer files. The
cache is Git-ignored, so a repository clone alone does not include it. Create a
new virtual environment on Linux; do not copy the Mac `.venv`. The dependency
file pins the same aligner commit used locally and CTranslate2 4.8.3.

With Python 3.11, Git, FFmpeg, and a C++ build toolchain installed, run these
commands from the repository root on your server:

```sh
python3.11 -m venv forced-alignment/.venv
forced-alignment/.venv/bin/python -m pip install -r forced-alignment/requirements.txt
```

If you cannot transfer the converted cache, use the model conversion command
in the installation section with this environment's Python. Keep the model
on local disk. Outputs can use the remaining disk space; retention of your
audio/SRT files is controlled by your application.

Set `ALIGNMENT_PORT` to an available local port of your choice, then start
**one** service process:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
forced-alignment/.venv/bin/python forced-alignment/alignment_server.py \
  --port "${ALIGNMENT_PORT:?Set ALIGNMENT_PORT to your chosen local port}" \
  --workers 1 --cpu-threads 2 --window-seconds 10 --batch-size 1 \
  --max-queued 4 --queue-timeout 600
```

Keep that command under your normal process manager. Do not run multiple
copies: each copy loads another model and gets a separate queue. The service
listens on loopback so your application on the same server can call it. It
accepts the same body as before:

```json
{
  "audio_path": "/absolute/server/path/audio.mp3",
  "transcript": "Hello world.",
  "language": "eng"
}
```

Send it to `POST http://127.0.0.1:<your-port>/align`. The synchronous response is
`{"words": [...], "srt": "..."}`. Waiting requests keep their HTTP connection
open and load no audio/model tensors until admitted. The first four waiting
requests queue; additional requests get HTTP 503. A request waiting more than
600 seconds gets HTTP 504 and is removed without starting alignment. This
timeout applies only to waiting, not to active processing. Set client/proxy
timeouts to cover **queue wait plus processing**. The queue is in memory and
does not survive a service restart. Set `--max-queued 0` for immediate rejection
when busy. Changing CLI settings requires a restart of this process.

To compare the four configurations below on the same hardware, first stop
the HTTP alignment service and avoid other CPU-heavy work. The benchmark
loads its own model and calls the same service code without starting an HTTP
server. Copy `output/ten-minute-2026-10-14/speech.mp3` and `transcript.txt`, or
point `--sample` at your own directory containing those two filenames.

```sh
ALIGNMENT_SAMPLE=forced-alignment/output/ten-minute-2026-10-14

# One request at a time, two threads. Each run includes one caller, then two
# simultaneous callers (the second waits when workers=1).
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
forced-alignment/.venv/bin/python forced-alignment/benchmark_optimizations.py \
  --sample "$ALIGNMENT_SAMPLE" --name server-w1-t2-b1 \
  --workers 1 --threads 2 --batch-size 1 --rounds 1 2 --idle 10

# Two active requests, one thread each. Compare against the first run's SRT.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
forced-alignment/.venv/bin/python forced-alignment/benchmark_optimizations.py \
  --sample "$ALIGNMENT_SAMPLE" --name server-w2-t1-b1 \
  --workers 2 --threads 1 --batch-size 1 --rounds 1 2 --idle 10 \
  --reference "$ALIGNMENT_SAMPLE/optimizations/server-w1-t2-b1/words.1.1.srt"

# One worker, two threads, two windows per model call.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
forced-alignment/.venv/bin/python forced-alignment/benchmark_optimizations.py \
  --sample "$ALIGNMENT_SAMPLE" --name server-w1-t2-b2 \
  --workers 1 --threads 2 --batch-size 2 --rounds 1 2 --idle 10 \
  --reference "$ALIGNMENT_SAMPLE/optimizations/server-w1-t2-b1/words.1.1.srt"

# Four windows per model call. This can increase peak RAM substantially.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
forced-alignment/.venv/bin/python forced-alignment/benchmark_optimizations.py \
  --sample "$ALIGNMENT_SAMPLE" --name server-w1-t2-b4 \
  --workers 1 --threads 2 --batch-size 4 --rounds 1 2 --idle 10 \
  --reference "$ALIGNMENT_SAMPLE/optimizations/server-w1-t2-b1/words.1.1.srt"
```

Run these sequentially, not together. Choose a new `--name` to repeat a run;
existing results are never overwritten. Every run writes `report.json`,
`memory.csv`, `events.json`, and SRT files under `sample/optimizations/name/`.
Reports include each caller's queue wait, processing time, total response time,
round wall time until all callers complete, average CPU cores used, peak/average
RSS, and word-timing differences from the reference. Average CPU cores used
is process CPU seconds divided by wall seconds: approximately 2 means two cores
were busy on average. CPU and RAM accounting excludes FFmpeg child processes.
Imports and model loading are measured separately from request times.

Choose the configuration using those measurements; batches two/four are
experiments, not proven speedups or guaranteed identical timestamps. Watch
whole-server memory too, including your main application. The default stays
at batch one until your server results justify changing it.

Focused checks are provided for you to run separately:

```sh
PYTHONPATH=forced-alignment forced-alignment/.venv/bin/python -m unittest \
  test_alignment_queue test_streaming_alignment test_light_ct2 -v
```

## Historical verified sample

The package is installed in `.venv` inside this directory. A complete run on
October 14, 2026 generated `output/sample-2026-10-14/speech.mp3` from the local
Speechma API and aligned its saved `transcript.txt` into `words.srt`.
The transcript has 1,781 characters and 305 words. The MP3 is 118.152 seconds
long and decodes without errors. All 305 SRT cues match the transcript words
exactly, with ordered, non-overlapping timestamps inside the audio duration.
These are structural checks, not a manual assessment of every word boundary.

From the repository root, use `forced-alignment/.venv/bin/python` in place of
`python3` to run with the installed dependencies. The first model download
stalled with Xet; setting `HF_HUB_DISABLE_XET=1` allowed the standard HTTP
download to complete. The model is now cached locally.

## CTranslate2 int8 comparison

CTranslate2 4.8.3 is installed in the same environment. The cached model was
converted once into `.cache/mms-300m-ct2-int8` inside this directory. Conversion
is excluded from the measurements below. The CPU reports `int8_float32` as its
actual compute type for the requested int8 model.

Measurements for the same 118.152-second audio and 305-word transcript, each
in a fresh Python process with Hugging Face offline mode enabled:

| Backend | Batch size | Total runtime | Generation excluding imports/model loading | Peak process RAM |
| --- | ---: | ---: | ---: | ---: |
| PyTorch float32 (previous result) | 4 | 16.13 s | 10.97 s | 5.10 GiB |
| CTranslate2 int8 | 4 | 22.79 s | 19.20 s | 5.03 GiB |
| CTranslate2 int8 | 1 | 20.61 s | 16.86 s | 4.08 GiB |

These are single-run observations using each backend's default CPU threading,
not averages or universal memory requirements. Peak RAM uses macOS
`resource.getrusage(RUSAGE_SELF).ru_maxrss` and includes dependency imports and
model loading. Installation, conversion, and downloads are excluded.

Int8 with batch size one reduced peak RAM by about 20%, while generation took
about 54% longer than the previous PyTorch run. Both int8 batch sizes produced
identical SRT files. Compared with the PyTorch SRT:

- All 305 words match the transcript exactly; timestamps are valid and do not overlap.
- Mean absolute boundary difference: 1.51 ms; 95th percentile: 20 ms.
- Both boundaries are within 50 ms for 304 of 305 words.
- Largest difference: 120 ms at the start of the first word, `Every`.

This measures agreement with the PyTorch output, not absolute accuracy against
manually annotated audio. Raw results are saved in `output/sample-2026-10-14/`
as `benchmark.int8.json`, `benchmark.int8.batch1.json`, and `comparison.int8.json`.

To reproduce this historical standard int8 setting, run from the repository
root and choose an output path that does not exist:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
forced-alignment/.venv/bin/python forced-alignment/generate_srt.py "/path/to/audio.mp3" \
  --transcript-file "/path/to/transcript.txt" \
  --language eng \
  --alignment-model forced-alignment/.cache/mms-300m-ct2-int8 \
  --no-lightweight \
  --batch-size 1 \
  --output "/path/to/words-int8.srt"
```

To recreate the converted backend in another environment:

```sh
python -m pip install ctranslate2==4.8.3
python -m ctc_forced_aligner.convert_to_ct2 \
  --model MahmoudAshraf/mms-300m-1130-forced-aligner \
  --output_dir forced-alignment/.cache/mms-300m-ct2-int8 \
  --quantization int8
```

## Two concurrent requests sharing the model

`benchmark_concurrent.py` ran two copies of the same 118.152-second sample in
one Python process, sharing one CTranslate2 int8 model with two inference
workers (`inter_threads=2`). Each request kept a batch size of one, a 30-second
window, and two seconds of context on each side. A monitor observed two active
inference batches simultaneously, confirming actual model-level concurrency.

| Measurement | Result |
| --- | ---: |
| Request 1, excluding shared setup | 24.14 s |
| Request 2, excluding shared setup | 24.04 s |
| Time until both requests finished, excluding shared setup | 24.14 s |
| Total including imports and model loading | 27.80 s |
| Combined peak Python process RAM | 5.74 GiB |

The previous single-request int8 run used 4.08 GiB and took 16.86 seconds
excluding setup. The concurrent process used about 1.67 GiB more peak RAM;
its memory did not double. This is one local CPU measurement, not a guarantee
of capacity on an 8 GB production server. Both outputs contain all 305 words
and are byte-for-byte identical to the single-request int8 SRT.

Results are saved in `output/sample-2026-10-14/benchmark.concurrent.json`,
with `words.concurrent.1.srt` and `words.concurrent.2.srt`. The benchmark uses
exclusive output creation to preserve existing results.

## Lightweight runtime comparison

The CPU NumPy/CTranslate2 path is now the default. The measurements in this
section used its original 30-second buffered configuration. The lighter
path uses the same int8 model, PCM decoding, 30-second windows, two-second
context and batch size as the standard int8 comparison.

`light_ct2.py` handles decoding, model inference and frame-to-word mapping.
`ctc_primitives.py` loads the installed package's text/romanization helpers and
compiled CTC kernel under an isolated namespace, avoiding the package initializer
that imports torch/transformers. This compatibility adapter is restricted to
fast-forced-aligner 0.3.0; review it before upgrading. No installed files were
modified. The dependency installation still contains torch/transformers for
conversion and the original path, but the lightweight runtime imports neither.

Fresh single-request comparison (one offline process per run):

| Runtime | Total time | Processing excluding imports/model loading | Peak process RAM |
| --- | ---: | ---: | ---: |
| Standard int8, fresh rerun | 21.03 s | 16.81 s | 3.66 GiB |
| Lightweight int8 | 18.03 s | 16.23 s | 3.20 GiB |

The fresh comparison shows about 12.5% lower peak RAM. The older standard int8
run peaked at 4.08 GiB, illustrating run-to-run variability. These are single
runs, not averaged benchmarks. The lightweight peak after imports was about
37 MiB, after model loading about 396 MiB, and after processing 3.20 GiB;
most peak memory therefore remains associated with processing, not imports.

SRT comparison against standard int8:

- All 305 transcript words match, with valid, ordered, non-overlapping timings.
- 304 words have identical start/end timestamps.
- Only the first word, `Every`, starts differently: standard 0.120 seconds,
  lightweight 0.240 seconds. Its end remains 0.460 seconds.
- Mean absolute difference across all boundaries is 0.197 ms; maximum 120 ms.
- This is timestamp agreement, not accuracy against manually annotated audio.

Three focused compatibility tests passed, covering window padding/trimming and
stride at short/exact/partial windows, CTC blank padding with repeated/empty
tokens, and rejection of inconsistent paths. NumPy log-softmax is checked
against upstream torch values to an absolute tolerance of 1e-6. The complete
audio run separately validates the real model path and absence of heavy imports.

Two concurrent requests shared one lightweight model with two inference workers:

| Runtime | Both requests complete, excluding setup | Total time | Combined peak RAM |
| --- | ---: | ---: | ---: |
| Standard int8 (previous benchmark) | 24.14 s | 27.80 s | 5.74 GiB |
| Lightweight int8 | 27.11 s | 28.97 s | 5.41 GiB |

Two simultaneous active inference batches were observed. Both concurrent SRTs
are byte-identical to the single-request lightweight output. The lighter runtime
provides modest RAM savings; it does not establish better concurrent throughput.

Artifacts in `output/sample-2026-10-14/`:

- `words.lightweight.comparison.srt`
- `benchmark.lightweight.comparison.json`
- `benchmark.standard.comparison.json`
- `benchmark.concurrent.lightweight.json`
- `words.concurrent.lightweight.1.srt`, `words.concurrent.lightweight.2.srt`

The CLI still loads a model per invocation. `LightCT2Aligner` can be instantiated
once and reused for multiple `.align(...)` calls (as in the concurrent benchmark),
but no persistent API service has been added or started.

## Smaller model candidates (researched, not benchmarked)

| Model | Parameters | Language | Integration implications |
| --- | ---: | --- | --- |
| [Meta Wav2Vec2 Base 960h](https://huggingface.co/facebook/wav2vec2-base-960h) | 94.4M | English | Closest architecture to this pipeline; the installed CT2 converter assumes feature-extractor LayerNorm while this checkpoint uses GroupNorm, so CT2 conversion needs adaptation or a different runtime. |
| [NVIDIA Conformer CTC Small](https://huggingface.co/nvidia/stt_en_conformer_ctc_small) | About 13M | English | Requires a NeMo-compatible model loader, audio frontend, tokenizer and CTC alignment integration; not a model-path substitution. |
| [NVIDIA QuartzNet 15x5](https://catalog.ngc.nvidia.com/orgs/nvidia/nemo/models/stt_en_quartznet15x5) | 18.9M | English | Convolutional CTC alternative; requires a different model/frontend integration. |

Smaller parameter counts do not establish peak RAM or alignment accuracy.
These candidates have not been downloaded or tested here, and none replaces
the current model's multilingual coverage as-is.

## CUPE multilingual benchmark

The 30,087,256-parameter MSWC38 checkpoint from
[Tabahi/CUPE-2i](https://huggingface.co/Tabahi/CUPE-2i) is installed and cached as
`.cache/cupe-mswc38/ckpt/multi_mswc38_ug20_e59_val_GER=0.5611.ckpt`.
This is the small multilingual model, explicitly selected instead of BFA's
English-only or large universal default. BFA 1.1.5 runs it in PyTorch float32 on
CPU. Only the existing English sample was tested; this does not validate other
languages. Installation/download time is excluded from all measurements.

`cupe_alignment.py` provides a reusable `CUPEAligner`. It decodes the same
118.152-second MP3 to mono 16 kHz PCM, processes every audio sample and the full
305-word transcript, and does not read the reference SRT. It batches 64 of CUPE's
120 ms windows (80 ms stride) at a time, retaining logits for full-transcript
alignment. It raises the segment limit to cover the complete recording rather
than truncating it at BFA's default. It preserves upstream phoneme/word boundary
selection and restores original transcript casing/punctuation in the SRT.

The adapter also fixes a long-input decoder issue locally: upstream BFA uses
`-1000` for impossible Viterbi states. Valid accumulated log probabilities can
fall below that value, allowing impossible paths to win. The first uncorrected
run returned only 39 words. Using negative infinity for impossible states
restored all 305 words and all 1,195 phoneme target indices in order. Installed
package files are unchanged; the adapter is version-guarded to BFA 1.1.5.

Two concurrent requests share one loaded model and have separate decoder and
counter state. Native eSpeak phonemization is serialized using a lock; model
inference is not serialized. Two overlapping model calls were observed. The
existing eSpeak 1.48 library was used successfully through phonemizer 3.4.0;
installing eSpeak NG encountered a Homebrew conflict with existing eSpeak, so
the existing installation was retained. No API service was started or changed.

Reproduce the cached benchmark from the repository root, choosing new result
names because existing files are not overwritten:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
PHONEMIZER_ESPEAK_LIBRARY=/opt/homebrew/opt/espeak/lib/libespeak.dylib \
MPLCONFIGDIR=/tmp/cupe-matplotlib \
forced-alignment/.venv/bin/python forced-alignment/benchmark_cupe.py \
  --requests 1 --name cupe.rerun.single
```

Use `--requests 2 --name cupe.rerun.concurrent` for concurrent requests. Paths to
the sample/checkpoint are fixed in this benchmark; the reusable adapter accepts
an audio path and transcript. `test_cupe_alignment.py` checks the decoder issue
with a synthetic low-probability path and verifies window-batch output ordering.

Peak RAM is the Python process high-water mark (`ru_maxrss`), including library
imports and model loading, measured in fresh processes. It excludes the brief
FFmpeg child process, consistently with the previous benchmarks. Results are
single observations on this Mac with default backend CPU threading, not averages
or an 8 GB production capacity guarantee. Full-recording decoding still has
memory costs that grow with audio and transcript length.

Fresh comparison on the same sample (one run per configuration):

| Runtime | Requests | Processing, excluding setup | Total, including imports/cached load | Peak Python RAM |
| --- | ---: | ---: | ---: | ---: |
| Current lightweight CT2 int8 | 1 | 18.91 s | 20.84 s | 2.86 GiB |
| CUPE MSWC38 float32 | 1 | 49.75 s | 52.45 s | 1.26 GiB |
| Current lightweight CT2 int8 | 2 concurrent | 24.10 s until both complete | 25.96 s | 4.74 GiB combined |
| CUPE MSWC38 float32 | 2 concurrent | 78.57 s until both complete | 80.57 s | 1.99 GiB combined |

CUPE reduced peak RAM by 56.0% for one request and 58.0% for two concurrent
requests, while processing took 2.63x and 3.26x as long, respectively. Individual
CUPE concurrent requests took 78.21 and 78.57 seconds. The baseline fresh SRTs
match the earlier lightweight SRT byte-for-byte, despite timing/RAM variation.

CUPE word-boundary agreement with the current lightweight SRT:

- All 305 words are present, in order, with positive, non-overlapping durations
  inside the recording. All three CUPE SRTs (single and both concurrent) are
  byte-for-byte identical.
- All 305 words differ in at least one boundary. Mean absolute boundary
  difference is 113.96 ms, median 73 ms, 95th percentile 536 ms, maximum 707 ms.
- Both boundaries are within 100 ms for 136/305 words and within 200 ms for
  237/305 words. The largest difference is `They` (word 268): its start changes
  from 103.340 s to 104.047 s; its end changes from 104.060 s to 104.111 s.
- All 1,195 phoneme indices are present in order, with zero estimated phonemes.
  Nevertheless, BFA flagged the segment as a bad alignment: 923/1,195 phonemes
  had confidence below 0.5. This is the model's internal confidence, not a
  measured error rate or a score comparable to MMS confidence.
- There is no manually annotated timing ground truth. Differences from the old
  SRT establish disagreement, not which model is more accurate. This run does
  not establish that CUPE is a quality-equivalent replacement.

Both focused adapter regression tests passed. Output and evidence files in
`output/sample-2026-10-14/`:

- `words.cupe.single.1.srt`, `words.cupe.concurrent.1.srt`, `words.cupe.concurrent.2.srt`
- `timings.cupe.single.csv`: all 305 word-by-word start/end differences
- `comparison.cupe.json`: combined summary, quality checks, input hashes
- `benchmark.cupe.single.json`, `benchmark.cupe.concurrent.json`
- `benchmark.current.cupecomparison.json`, `benchmark.current.concurrent.cupecomparison.json`
- `alignment.cupe.single.1.json`, `alignment.cupe.concurrent.1.json`,
  `alignment.cupe.concurrent.2.json`: raw BFA phoneme/word results

## Persistent int8 service and configurable processing

`alignment_service.py` now retains one `LightCT2Aligner` across requests and
uses one worker with two inference threads by default. Up to four additional
callers wait in a bounded FIFO queue. Each active request owns its
audio, emissions, and alignment data. The service does not launch Python or
reload weights for each request. The benchmark calls this same service object.

`alignment_server.py` is a separate loopback-only HTTP manager for that service.
It is not wired into Speechma's TTS routes and is not started automatically.
Start it explicitly with a chosen available port:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
forced-alignment/.venv/bin/python forced-alignment/alignment_server.py \
  --port <available-local-port>
```

`POST /align` accepts exactly `audio_path`, `transcript`, and `language` (ISO
639-3, such as `eng`). The audio path is a file on the service machine. It returns
`{"words": [...], "srt": "..."}` without writing files. Invalid requests return
400; a full waiting queue returns 503 and a queue timeout returns 504. The service
binds to `127.0.0.1` and rejects browser-origin requests; it is a local backend,
not a public authenticated upload API. The existing Speechma service is untouched.

Streaming audio decoding is the service default. `streaming_audio.py` reads
FFmpeg PCM incrementally and keeps only the current window batch plus overlapping
context. Emissions remain available for aligning the entire transcript together.
The final emissions array includes the extra CTC column from the start, avoiding
an additional full-array padding copy. This bounds decoded-audio memory, but
emissions and the native CTC alignment still grow with recording/transcript length.

The service defaults to one worker, two CPU threads, and 10-second central
windows for the two-core server. The historical comparisons below used a Mac
with more cores. Use `--window-seconds 30` for the original window/timing behavior, or 5
for a smaller working set with additional processing overhead.

The one-shot CLI now uses the same recommended settings by default:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
forced-alignment/.venv/bin/python forced-alignment/generate_srt.py audio.mp3 \
  --transcript-file transcript.txt --language eng --output new-words.srt
```

Supported central windows are 30, 10, and 5 seconds, always with two seconds of
audio context on each side. For a sufficiently long recording, each model call
therefore sees 34, 14, or 9 seconds respectively. The entire transcript is still
aligned and returned. The CLI, reusable aligner and service all default to
10-second windows and two threads. `--buffered` selects the old audio decoder
in the HTTP server for comparison; the CLI equivalent is `--no-streaming`.

`benchmark_optimizations.py` profiles the persistent service. Every configuration
starts in a fresh process, then executes one request and a concurrent pair with
the model kept loaded. It samples current resident memory approximately every
50 ms, including five seconds of idle time after each round, and also records
the OS lifetime high-water mark. `memory.csv` contains the timeline, `events.json`
marks request phases, and `report.json` contains duration, sampled peak/mean RSS,
time above thresholds, idle RSS, and SRT comparisons. Sampling can miss brief
spikes; the report records maximum sampling gaps. The FFmpeg child process is
excluded from process RSS, consistently with the earlier measurements.

`test_streaming_alignment.py` verifies identical decoded windows and logits
across 18 short/exact/partial-boundary cases, rejects empty/truncated PCM, and
checks model reuse, busy rejection, and slot release after errors. The existing
upstream-parity checks remain in `test_light_ct2.py`. `check_alignment_http.py`
validates the actual HTTP handler using an OS-assigned temporary local port and
stops that test server afterward.

### Optimization comparison on the saved sample

All rows use the same current MMS int8 model, 118.152-second English recording,
and 305-word transcript. One fresh process per configuration runs a single
request followed by two concurrent requests sharing its loaded model. Times
exclude imports/model loading and include SRT serialization. RAM below is
current RSS sampled every 50 ms; process high-water marks are also in the JSON.

| Setting | One request: time / peak RAM | Two concurrent: both complete / combined peak RAM | Word timing change versus current SRT |
| --- | --- | --- | --- |
| Existing buffered path, 30 s, default CPU threads | 17.80 s / 3.07 GiB | 24.32 s / 4.50 GiB | Identical |
| Streaming, 30 s, default CPU threads | 16.57 s / 3.34 GiB | 23.89 s / 4.83 GiB | Identical |
| Streaming, 30 s, 1 CPU thread per worker | 50.20 s / 3.14 GiB | 55.50 s / 4.30 GiB | Identical |
| Streaming, 30 s, 2 CPU threads per worker | 28.02 s / 3.15 GiB | 34.26 s / 4.00 GiB | Identical |
| Streaming, 30 s, 4 CPU threads per worker | 16.70 s / 3.33 GiB | 25.69 s / 4.28 GiB | Identical |
| Streaming, 10 s, 4 CPU threads per worker | 18.64 s / 1.61 GiB | 22.34 s / 2.67 GiB | 28 words changed; maximum 20 ms |
| Streaming, 5 s, 4 CPU threads per worker | 23.39 s / 1.20 GiB | 30.34 s / 1.90 GiB | 46 words changed; maximum 20 ms |

The default-thread and explicit-four-thread runs illustrate run-to-run variation;
these are single observations, not averaged rankings of tiny differences.
One/two CPU threads were substantially slower. Streaming alone did not establish
a peak-RAM improvement on this short clip. Shorter windows produced the main RAM
reduction. The persistent service saves repeated model loading (about 1.8 s here)
and shares weights; the table's concurrent baseline already shares its model, so
its RAM savings must not be attributed to newly adding persistence.

Every run returned all 305 words with valid, non-overlapping SRT timestamps inside
the audio duration. Single/concurrent SRTs were identical within each tested
setting. The 10-second result's mean absolute boundary difference was 0.918 ms;
the 5-second result's was 1.541 ms. These are agreement measurements with the
existing SRT, not accuracy against human timing annotations.

The new timeline answers the peak-duration question. In the fresh single-request
baseline, RSS exceeded 3 GiB for approximately 2.08 s and 2 GiB for 12.53 s during
17.80 s of processing; it was about 2.42 GiB after five idle seconds. The first
concurrent baseline reached 4.50 GiB briefly, but its repeated pair reached
4.54 GiB with a longer spike. Peak duration varies and cannot be inferred from
the earlier high-water-only measurements. At 10-second windows the first pair
held about 2.67 GiB during the following idle period: request completion does not
mean all working memory immediately returns to the OS.

Reports/SRTs/timelines are under `output/sample-2026-10-14/optimizations/` in
`baseline-30s`, `stream-30s-t0`, `stream-30s-t1`, `stream-30s-t2`, `stream-30s-t4`,
`stream-10s-t4`, and `stream-5s-t4`. `recommended-10s` repeats five requests
(one, then two pairs) with ten-second idle observations. Summary CSV/JSON and the
memory comparison plot are generated by `summarize_optimizations.py`.

The recommended 10-second configuration was repeated in a fresh persistent
process: one request took 19.00 s and peaked at 1.61 GiB; consecutive concurrent
pairs took 22.74 s / 2.67 GiB and 24.06 s / 2.73 GiB. Resident RAM after the final
ten-second idle period was 2.68 GiB. All five SRTs matched the first 10-second
result exactly. This confirms repeat behavior for this sample, not a universal
memory ceiling for longer or different recordings.

Historical validation before the two-core queue/batching changes: all six
focused parity/service tests passed (including
the 18 streaming boundary subcases). The actual HTTP endpoint passed a malformed
request check (400), then one real request and two concurrent real requests;
all returned the same complete SRT as the selected 10-second benchmark while
reusing one model. The temporary test server was stopped. See `http-check.json`.
Those results do not validate the later queue/batching changes. The current
code has not been tested, deployed, or connected to the existing Speechma API;
see the server deployment and benchmark commands above.
