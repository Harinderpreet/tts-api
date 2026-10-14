"""Focused checks for the local CUPE long-audio and batching adapter."""

import unittest
import torch
from bournemouth_aligner.forced_alignment import ViterbiDecoder
from cupe_alignment import BoundedPredictor


class CUPEAdapterTests(unittest.TestCase):
    def test_long_low_probability_path_visits_all_targets(self):
        # Acoustically unlikely transcript: valid path cost falls below -1000.
        # Invalid transitions must never beat that path merely due to its length.
        logits = torch.tensor([[-10., -10., -10., -10., 0.]]).repeat(200, 1)
        log_probs = logits.log_softmax(-1)
        states = torch.tensor([0, 1, 0, 2, 0, 3, 0])
        indices = torch.tensor([-1, 0, -1, 1, -1, 2, -1])
        decoder = ViterbiDecoder(blank_id=0, silence_id=None, truly_forced=True)
        _, broken = decoder._viterbi_decode(log_probs, states, len(states), indices)
        decoder._neg_inf = float("-inf")
        _, fixed = decoder._viterbi_decode(log_probs, states, len(states), indices)
        self.assertNotEqual(set(broken.tolist()) - {-1}, {0, 1, 2})
        self.assertEqual(set(fixed.tolist()) - {-1}, {0, 1, 2})
        targets = fixed[fixed >= 0]
        self.assertTrue(torch.all(targets[1:] >= targets[:-1]))

    def test_window_batching_keeps_logits_and_order(self):
        class Extractor:
            def predict(self, x, **kwargs):
                return x.unsqueeze(-1) * 2, x.unsqueeze(-1) + 3
        original = Extractor()
        bounded = BoundedPredictor(original, batch_size=3)
        windows = torch.arange(77.).reshape(11, 7)
        for actual, expected in zip(bounded.predict(windows), original.predict(windows)):
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assertEqual(bounded.calls, 4)
        self.assertEqual(bounded.maximum_active, 1)


if __name__ == "__main__":
    unittest.main()
