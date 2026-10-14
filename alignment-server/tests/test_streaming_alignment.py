"""Check PCM boundaries, numerical parity, and persistent-service admission."""

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from streaming_audio import PCMWindows
from light_ct2 import generate_emissions, generate_streaming_emissions
from alignment_service import AlignmentService, ServiceBusyError


class CaptureModel:
    def __init__(self):
        self.inputs = []

    def encode(self, features, to_cpu):
        values = np.asarray(features).copy()
        self.inputs.append(values)
        frames = (values.shape[-1]-400)//320+1
        # Depends on actual input samples to catch dropped/repeated context.
        signal = values[:, 0, :frames*320:320]
        return np.stack([signal, signal*2, signal-1], axis=-1)


class StreamingTests(unittest.TestCase):
    def test_boundaries_and_logits_match_buffered_path(self):
        from contextlib import contextmanager
        for window in (5, 10, 30):
            for seconds in (.1, window-.01, window, window+.01, 2*window, 2*window+1.13,
                            4*window, 4*window+1.13):
                with self.subTest(window=window, seconds=seconds):
                    pcm = (np.arange(round(seconds*16000)) % 60001 - 30000).astype("<i2")
                    @contextmanager
                    def decode(*args):
                        yield PCMWindows(io.BytesIO(pcm.tobytes()), window, 2)
                    for batch_size in (1, 2, 4):
                        with self.subTest(batch_size=batch_size):
                            buffered, streamed = CaptureModel(), CaptureModel()
                            expected, stride = generate_emissions(buffered, pcm.astype(np.float32)/32768,
                                                                  window_length=window, batch_size=batch_size)
                            with patch("streaming_audio.decoded_windows", decode):
                                actual, actual_stride = generate_streaming_emissions(
                                    streamed, "unused", window, batch_size=batch_size)
                            self.assertEqual(len(buffered.inputs), len(streamed.inputs))
                            for a,b in zip(buffered.inputs, streamed.inputs):
                                np.testing.assert_array_equal(a,b)
                            np.testing.assert_array_equal(actual, expected)
                            self.assertEqual(stride, actual_stride)

    def test_empty_and_broken_pcm_rejected(self):
        for raw in (b"", b"\x01"):
            with self.assertRaises(ValueError):
                list(PCMWindows(io.BytesIO(raw), 5, 2))

    def test_service_keeps_model_and_releases_slot_after_failure(self):
        with tempfile.NamedTemporaryFile() as audio, patch("alignment_service.LightCT2Aligner") as factory:
            service = AlignmentService("model", workers=1, max_queued=0, batch_size=2)
            factory.return_value.align.side_effect = [RuntimeError("failed"),
                [{"text":"Hi", "start":0, "end":.2}], [{"text":"Hi", "start":0, "end":.2}]]
            with self.assertRaises(RuntimeError):
                service.align(audio.name,"Hi","eng")
            first = service.align(audio.name,"Hi","eng")
            self.assertEqual(first,service.align(audio.name,"Hi","eng"))
            factory.assert_called_once()
            self.assertEqual(factory.return_value.align.call_args.kwargs["batch_size"], 2)
            with service.queue.slot():
                with self.assertRaises(ServiceBusyError):
                    service.align(audio.name,"Hi","eng")


if __name__ == "__main__":
    unittest.main()
