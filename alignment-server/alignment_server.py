"""HTTP manager for a persistent AlignmentService (start explicitly).

POST /align: multipart audio file, transcript, optional language -> {words, srt}.
Uploaded audio is stored temporarily and removed after processing or failure.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
import tempfile
import threading

from audio_upload import read_audio_upload, UploadTooLarge
from alignment_service import AlignmentService, ServiceBusyError, QueueTimeoutError
from alignment_config import (
    DEFAULT_MODEL_PATH, DEFAULT_WINDOW_SECONDS, DEFAULT_CPU_THREADS, DEFAULT_WORKERS,
    DEFAULT_BATCH_SIZE, DEFAULT_MAX_QUEUED, DEFAULT_QUEUE_TIMEOUT_SECONDS,
)


def create_server(service, port, host="127.0.0.1", max_upload_bytes=100 * 1024 * 1024):
    if max_upload_bytes <= 0:
        raise ValueError("Upload size limit must be positive")
    # Includes uploads, queued requests and active processing, bounding temporary disk use.
    uploads = threading.BoundedSemaphore(service.queue.workers + service.queue.max_queued)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, result):
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def do_POST(self):
            if self.path != "/align":
                self.reply(404, {"error": "Not found"})
                return
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "multipart/form-data":
                self.reply(415, {"error": "Send multipart/form-data with audio and transcript; language is optional"})
                return
            if self.headers.get("Transfer-Encoding") or not self.headers.get("Content-Length"):
                self.reply(411, {"error": "Send a multipart upload with Content-Length"})
                return
            if not uploads.acquire(blocking=False):
                self.reply(503, {"error": "Upload/alignment capacity is full; retry later"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                self.connection.settimeout(60)  # Inactivity limit while receiving the body.
                with tempfile.TemporaryDirectory(prefix="alignment-upload-") as directory:
                    audio, transcript, language = read_audio_upload(
                        self.rfile, content_type, length, directory, max_upload_bytes,
                    )
                    self.connection.settimeout(None)
                    result = service.align(audio, transcript, language)
            except UploadTooLarge as error:
                self.reply(413, {"error": str(error)})
            except TimeoutError:
                self.reply(408, {"error": "Audio upload timed out"})
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
            finally:
                uploads.release()

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"status": "ready", "audio_upload": True, **service.queue.snapshot()})
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
    parser.add_argument("--max-upload-mb", type=int, default=os.environ.get("ALIGNMENT_MAX_UPLOAD_MB", "100"), help="Maximum multipart request size in MiB (default: 100)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.window_seconds not in (5, 10, 30) or args.batch_size not in (1, 2, 4):
        parser.error("window must be 5/10/30 and batch size must be 1/2/4")
    if args.max_upload_mb <= 0:
        parser.error("max upload size must be positive")
    service = AlignmentService(args.model, args.workers, args.cpu_threads, args.window_seconds,
                               streaming=not args.buffered, batch_size=args.batch_size,
                               max_queued=args.max_queued, queue_timeout=args.queue_timeout)
    with create_server(service, args.port, args.host, args.max_upload_mb * 1024 * 1024) as server:
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
