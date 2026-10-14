# Word alignment server

An independent Docker project for a **2-core CPU / 8 GB RAM server**. This
directory can become its own Git repository. It does not import files from
Speechma or the original `forced-alignment` experiments.

Given an audio path and its transcript, the API returns one subtitle cue per
word. It uses the multilingual MMS model through the lightweight CTranslate2
int8 backend, with one persistent model, two inference threads, ten-second
windows, and streaming decoding. One request runs at a time; four additional
requests can wait in arrival order. Batch size defaults to one.

**Status:** code prepared and source-reviewed; the Docker image has not been
built, and the queue/batch changes have not been tested. No server performance
claim is made until you run it on your machine.

## Build and run

Run everything below from this directory, preferably on the target server:

```sh
docker build -t forced-alignment:local .
mkdir -p audio
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
It publishes port **8000 on the host's loopback interface** and mounts `audio/`
read-only at `/data/audio`. To change only the published host port:

```sh
ALIGNMENT_PUBLISHED_PORT=9000 docker compose up -d --no-build
```

Or run the built image without Compose:

```sh
docker run -d --name alignment --init --restart unless-stopped \
  --cpus 2 --memory 6g --memory-swap 6g \
  -p 127.0.0.1:8000:8000 \
  -v "$PWD/audio:/data/audio:ro" \
  forced-alignment:local
```

The image runs as UID/GID **10001**. Mounted audio files and their directories
must be readable/traversable by that user. Run only one service container for
this two-core configuration; extra replicas duplicate the model and queue.

## API

`GET /health` returns HTTP 200 after the model is loaded:

```json
{"status":"ready","active_requests":0,"queued_requests":0}
```

Docker uses this endpoint for its health check without running inference.

Copy your audio into `audio/`, then send `POST /align`:

```sh
curl --fail-with-body http://127.0.0.1:8000/align \
  -H 'Content-Type: application/json' \
  --data '{"audio_path":"/data/audio/speech.mp3","transcript":"Hello world.","language":"eng"}'
```

Use the exact transcript spoken in your audio. `language` is an ISO 639-3 code;
`eng` means English. `audio_path` is the **path inside the container**, not the
host filesystem path or a URL. The API reads existing files; it is not an
upload endpoint. A colocated application can share the same audio mount, or
another container can call `http://alignment:8000/align` on the Compose network.

Successful response:

```json
{
  "words": [{"text":"Hello","start":0.1,"end":0.4}],
  "srt": "1\n00:00:00,100 --> 00:00:00,400\nHello\n\n"
}
```

The example timing is illustrative. Save the returned `srt` value to your
chosen `.srt` file. HTTP requests themselves do not write audio or SRT files.
For a transcript file, this Python client example avoids manual JSON escaping:

```python
import json
from pathlib import Path
from urllib.request import Request, urlopen

body = {
    "audio_path": "/data/audio/speech.mp3",
    "transcript": Path("transcript.txt").read_text(encoding="utf-8"),
    "language": "eng",
}
request = Request(
    "http://127.0.0.1:8000/align",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
)
with urlopen(request, timeout=1800) as response:
    result = json.load(response)
with Path("words.srt").open("x", encoding="utf-8") as output:
    output.write(result["srt"])
```

Error responses: 400 for invalid input, 503 if the waiting queue is full, 504
if a request waits too long, and 500 if alignment fails. Queue timeout defaults
to 600 seconds; it does not limit active processing. Client/proxy timeouts must
cover **queue wait plus processing**. Waiting requests keep their HTTP
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
| `ALIGNMENT_MODEL_PATH` | `/app/.cache/mms-300m-ct2-int8` | Optional replacement converted model directory |

For two active requests using one thread each, set workers to `2` and CPU
threads to `1`. Compare this against the default before adopting it. Batch
sizes `2` and `4` are experiments that consume more RAM; they are not guaranteed
speedups or guaranteed to preserve every timestamp. Threads are an inference
setting; the Docker CPU limit constrains the whole container.

## Benchmark on the server

Stop the service before benchmarking so its model and CPU activity do not
distort measurements. Put `speech.mp3` and `transcript.txt` in `audio/`. The
benchmark requires a writable mount because it saves SRTs and measurements.
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
`/health`. Configure a shared audio volume mounted at `/data/audio`. Supply the
CPU/memory limits in the platform as well; a Dockerfile alone does not impose
resource limits. No model download is needed when the built image starts.

For a registry workflow, tag the built image with your registry/repository/tag
and push it using your normal Docker credentials. Deploy that tag with the
same port, volume, environment, and resource settings above. Image builds must
target the deployment server's architecture.

The underlying model and aligner declare CC-BY-NC 4.0; packaging them in this
image does not change their licensing. The pinned upstream source is
[fast-forced-aligner](https://github.com/michsethowusu/fast-forced-aligner/tree/84cc35846489f5b1567840bbd6e0759204685536).
