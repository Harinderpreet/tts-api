"""Persistent alignment logic: shared weights, bounded concurrency, reusable API."""

from pathlib import Path

from generate_srt import render_word_srt
from light_ct2 import LightCT2Aligner
from alignment_queue import AlignmentQueue, ServiceBusyError, QueueTimeoutError
from alignment_config import (
    DEFAULT_MODEL_PATH, DEFAULT_WINDOW_SECONDS, DEFAULT_CPU_THREADS, DEFAULT_WORKERS,
    DEFAULT_BATCH_SIZE, DEFAULT_MAX_QUEUED, DEFAULT_QUEUE_TIMEOUT_SECONDS,
)


class AlignmentService:
    def __init__(self, model_path=DEFAULT_MODEL_PATH, workers=DEFAULT_WORKERS,
                 intra_threads=DEFAULT_CPU_THREADS, window_length=DEFAULT_WINDOW_SECONDS,
                 streaming=True, batch_size=DEFAULT_BATCH_SIZE,
                 max_queued=DEFAULT_MAX_QUEUED, queue_timeout=DEFAULT_QUEUE_TIMEOUT_SECONDS):
        if not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        self.queue = AlignmentQueue(workers, max_queued, queue_timeout)
        self.batch_size = batch_size
        self.aligner = LightCT2Aligner(
            model_path, workers=workers, intra_threads=intra_threads,
            window_length=window_length, streaming=streaming,
        )

    def align(self, audio_path, transcript, language, phase_callback=None):
        if not all(isinstance(value, str) and value.strip() for value in (audio_path, transcript, language)):
            raise ValueError("audio_path, transcript and language must be nonempty strings")
        language = language.strip().lower()
        if len(language) != 3 or not language.isascii() or not language.isalpha():
            raise ValueError("language must be an ISO 639-3 code, for example eng")
        if language in {"jpn", "chi"}:
            raise ValueError("Word-level output is unavailable for jpn/chi")
        audio = Path(audio_path).expanduser().resolve()
        if not audio.is_file():
            raise FileNotFoundError("Audio file does not exist")
        phase = phase_callback or (lambda name: None)
        phase("queue_wait")
        with self.queue.slot():
            phase("started")
            words = self.aligner.align(audio, transcript, language, batch_size=self.batch_size,
                                       phase_callback=phase_callback)
            return {"words": words, "srt": render_word_srt(words)}
