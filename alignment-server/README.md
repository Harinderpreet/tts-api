# Word alignment server

An independent Docker project for a **2-core CPU / 8 GB RAM server**. This
directory can become its own Git repository. It does not import files from
Speechma or the original `forced-alignment` experiments.

Upload an audio file and its transcript to receive word-level timestamps and
one subtitle cue per word. It uses the multilingual MMS model through the lightweight CTranslate2
int8 backend, with one persistent model, two inference threads, ten-second
windows, and streaming decoding. One request runs at a time; four additional
requests can wait in arrival order. Batch size defaults to one.

**Status:** the upload API changes are prepared but have not been tested,
built into an image, or deployed. Rebuild and redeploy to replace the previous
JSON path-based API. No server performance claim is made until measured.

## Build and run

Run everything below from this directory, preferably on the target server:

```sh
docker build -t forced-alignment:local .
docker compose up -d --no-build
```

The first build needs internet access. It compiles the pinned aligner's native
CTC extension, downloads the pinned model revision, converts it to int8, and
includes the converted model/tokenizer in the final image. Subsequent starts
are offline. No model cache or virtual environment needs to be uploaded to Git.
PyTorch, Transformers, Git, and the compiler stay in build stages; the final
image contains the lightweight runtime, FFmpeg, and converted weights.
The original PyTorch fallback (`--no-lightweight` in the standalone CLI) is
not included in this image; use its default lightweight backend.

The model conversion stage needs more RAM and disk than normal startup. If
the build is too heavy for the deployment server, build on a larger machine
for the server's CPU architecture and push that image to your registry. A Mac
build is not automatically the right architecture for an x86 Linux server.

Compose limits the container to two CPUs and 6 GiB memory, leaving roughly
2 GiB for the operating system and other services. It disables additional swap
allowance for this container. These are runtime limits, not build limits.
It publishes port **8000 on the host's loopback interface**. No shared audio
directory or volume is needed for API uploads. To change only the published host port:

```sh
ALIGNMENT_PUBLISHED_PORT=9000 docker compose up -d --no-build
```

Or run the built image without Compose:

```sh
docker run -d --name alignment --init --restart unless-stopped \
  --cpus 2 --memory 6g --memory-swap 6g \
  -p 127.0.0.1:8000:8000 \
  forced-alignment:local
```

The image runs as UID/GID **10001** and uses its writable temporary directory
for uploads. Run only one service container for
this two-core configuration; extra replicas duplicate the model and queue.

## API

`GET /health` returns HTTP 200 after the model is loaded:

```json
{"status":"ready","audio_upload":true,"active_requests":0,"queued_requests":0}
```

Docker uses this endpoint for its health check without running inference.

Send `POST /align` as multipart form data:

| Field | Required | Value |
| --- | --- | --- |
| `audio` | Yes | Audio file uploaded from the client |
| `transcript` | Yes | Spoken transcript as text or a UTF-8 text file |
| `language` | No | ISO 639-3 language code; defaults to `eng` (English) |

```sh
curl --fail-with-body --max-time 1800 https://testingspeech.crikk.com/align \
  --form 'audio=@speech.mp3' \
  --form 'transcript=<transcript.txt' \
  --form 'language=eng' \
  --output alignment.json
```

Both files are on the client running curl; curl uploads them to the server.
For inline text, use `--form-string 'transcript=Hello world.'` instead of the
transcript-file field. Use the exact transcript spoken in your audio.
Let curl set Content-Type and its multipart boundary automatically.
For local access, use `http://127.0.0.1:8000/align`; another container on the
Compose network can use `http://alignment:8000/align`.
JSON requests containing `audio_path` are no longer accepted.

Successful response:

```json
{
  "words": [{"text":"Hello","start":0.1,"end":0.4}],
  "srt": "1\n00:00:00,100 --> 00:00:00,400\nHello\n\n"
}
```

The example timing is illustrative; `start` and `end` are seconds from the
beginning of the audio. Save the returned `srt` value from `alignment.json`:

```python
import json
from pathlib import Path
result = json.loads(Path("alignment.json").read_text(encoding="utf-8"))
with Path("words.srt").open("x", encoding="utf-8") as output:
    output.write(result["srt"])
```

Audio streams to temporary disk storage and is deleted after success or
failure. The server does not retain audio or SRT files. The entire multipart
request is limited to 100 MiB by default; transcript text is limited to 2 MiB.
At most five requests may be uploading, waiting, or processing with the default
settings. An upload times out after 60 seconds without incoming data.

Error responses: 400 for invalid input, 408 for an upload timeout, 411 for
missing Content-Length or unsupported chunked transfer, 413 for oversized
uploads, 415 for non-multipart requests, 503 if upload/alignment capacity is
full, 504 if a request waits too long, and 500 if alignment fails. Queue timeout defaults
to 600 seconds; it does not limit active processing. Client/proxy timeouts must
cover **upload plus queue wait plus processing**. Waiting requests keep their HTTP
connections open. Queued/in-progress requests are not durable across restarts.

This is an internal service with no built-in authentication. Keep it on a
private Docker network or use the loopback publishing shown above; a public
domain needs your application's authentication boundary in front of it.

## Settings

Environment variables configure the HTTP server. CLI flags override them.
For Compose, edit the corresponding `environment` values in `compose.yaml`.
For a Docker-image deployment platform, set these as runtime environment values:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ALIGNMENT_HOST` | `0.0.0.0` in Docker | Listen on container interfaces |
| `ALIGNMENT_PORT` | `8000` | Internal listening port |
| `ALIGNMENT_WORKERS` | `1` | Active requests sharing the model |
| `ALIGNMENT_CPU_THREADS` | `2` | Inference threads per worker |
| `ALIGNMENT_WINDOW_SECONDS` | `10` | Central window length: 5, 10, or 30 |
| `ALIGNMENT_BATCH_SIZE` | `1` | Windows per model call: 1, 2, or 4 |
| `ALIGNMENT_MAX_QUEUED` | `4` | Waiting requests; 0 rejects immediately when busy |
| `ALIGNMENT_QUEUE_TIMEOUT` | `600` | Maximum seconds waiting for a worker |
| `ALIGNMENT_MAX_UPLOAD_MB` | `100` | Maximum entire multipart request size in MiB |
| `ALIGNMENT_MODEL_PATH` | `/app/.cache/mms-300m-ct2-int8` | Optional replacement converted model directory |

For two active requests using one thread each, set workers to `2` and CPU
threads to `1`. Compare this against the default before adopting it. Batch
sizes `2` and `4` are experiments that consume more RAM; they are not guaranteed
speedups or guaranteed to preserve every timestamp. Threads are an inference
setting; the Docker CPU limit constrains the whole container.

## Benchmark on the server

Stop the service before benchmarking so its model and CPU activity do not
distort measurements. Put `speech.mp3` and `transcript.txt` in `audio/`. The
offline benchmark requires a writable mount because it saves SRTs and measurements.
This mount is only for the benchmark; API uploads do not need it.
Give UID 10001 write access to the sample directory, or run the benchmark
container using the current host user's UID/GID as shown below.

```sh
docker compose stop

docker run --rm --init --user "$(id -u):$(id -g)" \
  --cpus 2 --memory 6g --memory-swap 6g \
  -v "$PWD/audio:/data/audio" \
  forced-alignment:local python benchmark.py \
  --sample /data/audio --name w1-t2-b1 \
  --workers 1 --threads 2 --batch-size 1 --rounds 1 2 --idle 10
```

Repeat with a different name and settings, one run at a time:

| Name | Workers | Threads | Batch |
| --- | ---: | ---: | ---: |
| `w1-t2-b1` | 1 | 2 | 1 |
| `w2-t1-b1` | 2 | 1 | 1 |
| `w1-t2-b2` | 1 | 2 | 2 |
| `w1-t2-b4` | 1 | 2 | 4 |

For subsequent runs, add:

```text
--reference /data/audio/optimizations/w1-t2-b1/words.1.1.srt
```

Each run makes one request, then submits two callers simultaneously. With one
worker, one caller waits. Results under `audio/optimizations/<name>/` include
per-request queue wait, processing and total time; CPU seconds and average CPU
cores used; process RSS and its timeline; and SRT/word-timing comparisons.
CPU and RSS values exclude FFmpeg child processes. Imports/model loading are
separate from request timing. The benchmark currently uses English (`eng`).
Use a new name when repeating a configuration to preserve existing outputs.

Optional source checks (not run during preparation or image build):

```sh
docker run --rm forced-alignment:local python -m unittest discover -s tests -v
```

## Separate Git repository and image deployment

Copy this entire directory outside the existing repository, then initialize
your new Git repo there. No files from the surrounding workspace are required.
The ignore files exclude credentials, model caches, audio, outputs, and virtual
environments. Commit the Python sources, `docker/`, `tests/`, `requirements.txt`,
`Dockerfile`, `compose.yaml`, and this README.

For a platform that builds from Git, select this repository, use `Dockerfile`
at its root with build context `.`, internal port `8000`, and health path
`/health`. No audio volume is required; keep the container's temporary directory writable. Supply the
CPU/memory limits in the platform as well; a Dockerfile alone does not impose
resource limits. No model download is needed when the built image starts.

For a registry workflow, tag the built image with your registry/repository/tag
and push it using your normal Docker credentials. Deploy that tag with the
same port, environment, and resource settings above. Image builds must
target the deployment server's architecture.

The underlying model and aligner declare CC-BY-NC 4.0; packaging them in this
image does not change their licensing. The pinned upstream source is
[fast-forced-aligner](https://github.com/michsethowusu/fast-forced-aligner/tree/84cc35846489f5b1567840bbd6e0759204685536).
