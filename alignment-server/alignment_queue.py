"""Bounded FIFO admission; waiting callers hold no audio or model tensors."""

from collections import deque
from contextlib import contextmanager
import math
import threading
import time


class ServiceBusyError(RuntimeError):
    pass


class QueueTimeoutError(ServiceBusyError):
    pass


class AlignmentQueue:
    def __init__(self, workers, max_queued, timeout_seconds):
        if not isinstance(workers, int) or workers < 1:
            raise ValueError("workers must be a positive integer")
        if not isinstance(max_queued, int) or max_queued < 0:
            raise ValueError("max_queued must be a nonnegative integer")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("queue timeout must be finite and positive")
        self.workers = workers
        self.max_queued = max_queued
        self.timeout_seconds = timeout_seconds
        self.condition = threading.Condition()
        self.waiting = deque()
        self.active = 0

    def snapshot(self):
        with self.condition:
            return {"active_requests": self.active, "queued_requests": len(self.waiting)}

    @contextmanager
    def slot(self):
        with self.condition:
            if self.active >= self.workers or self.waiting:
                if len(self.waiting) >= self.max_queued:
                    raise ServiceBusyError("Alignment queue is full; retry later")
                ticket = object()
                self.waiting.append(ticket)
                deadline = time.monotonic() + self.timeout_seconds
                try:
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise QueueTimeoutError("Timed out waiting for alignment; retry later")
                        if self.waiting[0] is ticket and self.active < self.workers:
                            break
                        self.condition.wait(remaining)
                finally:
                    # Remove timed-out/interrupted callers too, so they cannot block the queue.
                    self.waiting.remove(ticket)
                    self.condition.notify_all()
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()
