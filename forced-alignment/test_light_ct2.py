"""Focused compatibility checks against the installed upstream implementation."""

import unittest
from types import SimpleNamespace

import numpy as np
import torch
from ctc_forced_aligner import alignment_utils as upstream

from light_ct2 import generate_emissions, spans_from_path


def fake_logits(batch):
    frames = (batch.shape[-1] - 400) // 320 + 1
    row = np.linspace(-3, 3, frames * 4, dtype=np.float32).reshape(frames, 4)
    return np.broadcast_to(row, (batch.shape[0], frames, 4)).copy()


class NumpyModel:
    def encode(self, features, to_cpu):
        return fake_logits(np.asarray(features))


class TorchModel:
    def __call__(self, batch):
        return SimpleNamespace(logits=torch.from_numpy(fake_logits(batch.numpy())))


class LightweightParityTests(unittest.TestCase):
    def test_window_padding_trimming_and_stride(self):
        # Short clips, exact window boundaries, and partially filled last chunks.
        for seconds in (5, 29.95, 30, 31, 61):
            for batch_size in (1, 4):
                with self.subTest(seconds=seconds, batch_size=batch_size):
                    audio = np.zeros(round(seconds * 16000), dtype=np.float32)
                    expected, expected_stride = upstream.generate_emissions(
                        TorchModel(), torch.from_numpy(audio), batch_size=batch_size
                    )
                    actual, stride = generate_emissions(NumpyModel(), audio, batch_size=batch_size)
                    self.assertEqual(stride, expected_stride)
                    self.assertEqual(actual.dtype, np.float32)
                    np.testing.assert_allclose(actual, expected.numpy(), rtol=0, atol=1e-6)

    def test_blank_padding_repeated_and_empty_tokens(self):
        names = {0: "<blank>", 1: "a", 2: "b", 3: "<star>"}
        tokens = ["<star>", "a b", "b", "", "<star>"]
        ids = [[3], [1, 2], [2], [], [3]]
        for path in ([0, 3, 3, 0, 1, 0, 2, 0, 2, 0, 3, 3, 0],
                     [3, 1, 2, 0, 2, 3],
                     [0, 0, 3, 0, 0, 1, 1, 0, 2, 0, 0, 2, 0, 3, 0, 0]):
            with self.subTest(path=path):
                expected = upstream.get_spans(tokens, upstream.merge_repeats(path, names), "<blank>")
                actual = spans_from_path(path, ids, 0)
                self.assertEqual(
                    [(span[0].start, span[-1].end) for span in expected],
                    [(span[0].start, span[-1].end) for span in actual],
                )

    def test_bad_path_is_rejected(self):
        with self.assertRaises(ValueError):
            spans_from_path([3, 1, 0], [[3], [2]], 0)


if __name__ == "__main__":
    unittest.main()
