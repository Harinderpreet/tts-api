"""Decode PCM incrementally, retaining only one model window and its context."""

from contextlib import contextmanager
import subprocess
import tempfile

import numpy as np

SAMPLE_RATE = 16000


class PCMWindows:
    def __init__(self, reader, window_seconds, context_seconds):
        self.reader = reader
        self.window = round(window_seconds * SAMPLE_RATE)
        self.context = round(context_seconds * SAMPLE_RATE)
        if self.window < 400 or self.context < 0:
            raise ValueError("Invalid audio window/context length")
        self.sample_count = 0
        self.extension = 0
        self.eof = False

    def read(self, samples):
        chunks = bytearray()
        while len(chunks) < samples * 2:
            chunk = self.reader.read(samples * 2 - len(chunks))
            if not chunk:
                self.eof = True
                break
            chunks.extend(chunk)
        if len(chunks) % 2:
            raise ValueError("Decoder returned incomplete PCM sample")
        values = np.frombuffer(chunks, dtype="<i2").astype(np.float32)
        values /= np.float32(32768)
        self.sample_count += len(values)
        return values

    def __iter__(self):
        first = self.read(self.window + self.context)
        if len(first) == 0:
            raise ValueError("The audio file contains no audio samples")
        if len(first) < self.window:
            yield first, False
            return
        buffer = np.concatenate((np.zeros(self.context, dtype=np.float32), first))
        offset = 0
        size = self.window + 2 * self.context
        while True:
            if len(buffer) < size and not self.eof:
                buffer = np.concatenate((buffer, self.read(size-len(buffer))))
            if self.eof and offset >= self.sample_count:
                break
            features = np.zeros(size, dtype=np.float32)
            features[:len(buffer)] = buffer
            yield features, self.context > 0
            offset += self.window
            buffer = buffer[self.window:]
        self.extension = offset - self.sample_count


@contextmanager
def decoded_windows(audio_path, window_seconds, context_seconds):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-i", str(audio_path),
             "-threads", "1", "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", "16000", "-"],
            stdout=subprocess.PIPE, stderr=errors,
        )
        try:
            yield PCMWindows(process.stdout, window_seconds, context_seconds)
            if process.wait() != 0:
                errors.seek(0)
                raise RuntimeError(f"Audio decoding failed: {errors.read(8192).decode(errors='replace')}")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
