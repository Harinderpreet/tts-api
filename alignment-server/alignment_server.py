"""HTTP manager for a persistent AlignmentService (start explicitly).

POST /align: {audio_path, transcript, language} -> {words, srt}.
Paths refer to audio on the same machine. No output files are written by HTTP.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal

from alignment_service import AlignmentService, ServiceBusyError, QueueTimeoutError
from alignment_config import (
    DEFAULT_MODEL_PATH, DEFAULT_WINDOW_SECONDS, DEFAULT_CPU_THREADS, DEFAULT_WORKERS,
    DEFAULT_BATCH_SIZE, DEFAULT_MAX_QUEUED, DEFAULT_QUEUE_TIMEOUT_SECONDS,
)


def create_server(service, port, host="127.0.0.1"):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, result):
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/align":
                self.reply(404, {"error": "Not found"})
                return
            # This internal API is intended for server callers, not browsers.
            if self.headers.get("Origin"):
                self.reply(403, {"error": "Browser requests are not supported"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2 * 1024 * 1024:
                    raise ValueError("Expected a JSON body smaller than 2 MiB")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or set(body) != {"audio_path", "transcript", "language"}:
                    raise ValueError("Provide audio_path, transcript and language")
                result = service.align(**body)
            except QueueTimeoutError as error:
                self.reply(504, {"error": str(error)})
            except ServiceBusyError as error:
                self.reply(503, {"error": str(error)})
            except (ValueError, FileNotFoundError, UnicodeError) as error:
                self.reply(400, {"error": str(error)})
            except Exception:
                self.reply(500, {"error": "Alignment failed"})
            else:
                self.reply(200, result)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"status": "ready", **service.queue.snapshot()})
            else:
                self.reply(404, {"error": "Not found"})

        def log_message(self, *args):
            pass  # Do not log transcripts or local file paths.

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--host", default=os.environ.get("ALIGNMENT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=os.environ.get("ALIGNMENT_PORT", "8000"))
    parser.add_argument("--workers", type=int, default=os.environ.get("ALIGNMENT_WORKERS", str(DEFAULT_WORKERS)))
    parser.add_argument("--cpu-threads", type=int, default=os.environ.get("ALIGNMENT_CPU_THREADS", str(DEFAULT_CPU_THREADS)))
    parser.add_argument("--window-seconds", type=int, choices=(5, 10, 30), default=os.environ.get("ALIGNMENT_WINDOW_SECONDS", str(DEFAULT_WINDOW_SECONDS)))
    parser.add_argument("--batch-size", type=int, choices=(1, 2, 4), default=os.environ.get("ALIGNMENT_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))
    parser.add_argument("--max-queued", type=int, default=os.environ.get("ALIGNMENT_MAX_QUEUED", str(DEFAULT_MAX_QUEUED)), help="Waiting requests beyond active workers (default: 4); 0 rejects busy requests")
    parser.add_argument("--queue-timeout", type=float, default=os.environ.get("ALIGNMENT_QUEUE_TIMEOUT", str(DEFAULT_QUEUE_TIMEOUT_SECONDS)), help="Maximum seconds waiting for a worker (default: 600); does not limit processing time")
    parser.add_argument("--buffered", action="store_true", help="Use the original full-audio decoder for comparison")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.window_seconds not in (5, 10, 30) or args.batch_size not in (1, 2, 4):
        parser.error("window must be 5/10/30 and batch size must be 1/2/4")
    service = AlignmentService(args.model, args.workers, args.cpu_threads, args.window_seconds,
                               streaming=not args.buffered, batch_size=args.batch_size,
                               max_queued=args.max_queued, queue_timeout=args.queue_timeout)
    with create_server(service, args.port, args.host) as server:
        print(f"Alignment service listening on http://{args.host}:{server.server_port}", flush=True)
        print(f"Workers={args.workers}, threads/worker={args.cpu_threads}, "
              f"window={args.window_seconds}s, batch={args.batch_size}, "
              f"queue={args.max_queued}, queue timeout={args.queue_timeout}s", flush=True)
        def stop(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
