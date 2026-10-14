"""CPU int8 defaults for a two-core server with 8 GB RAM."""

from pathlib import Path
import os

DEFAULT_MODEL_PATH = os.environ.get(
    "ALIGNMENT_MODEL_PATH", str(Path(__file__).resolve().parent / ".cache/mms-300m-ct2-int8")
)
DEFAULT_WINDOW_SECONDS = 10
DEFAULT_CPU_THREADS = 2
DEFAULT_WORKERS = 1
DEFAULT_BATCH_SIZE = 1
DEFAULT_MAX_QUEUED = 4
DEFAULT_QUEUE_TIMEOUT_SECONDS = 600
