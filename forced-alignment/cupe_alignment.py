"""CPU CUPE/BFA adapter with bounded inference batches and shared model weights.

Uses the full audio/transcript, without reference timestamps or transcript chunks.
Model window batching is bounded, and impossible decoder states use negative
infinity (upstream's -1000 sentinel can win over valid long-recording paths).
Word boundary selection remains upstream. A request owns decoder/counter state;
eSpeak phonemization is serialized because the native library has global state.
"""

import copy
import importlib.metadata
import math
import subprocess
import threading
import unicodedata

import numpy as np
import torch
from bournemouth_aligner import PhonemeTimestampAligner


def normalized_word(text):
    return "".join(c for c in text.casefold() if not unicodedata.category(c).startswith("P"))


class BoundedPredictor:
    def __init__(self, extractor, batch_size=64):
        self.extractor = extractor
        self.batch_size = batch_size
        self.lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0
        self.calls = 0

    def predict(self, audio_batch, return_embeddings=False, groups_only=False):
        if return_embeddings or groups_only:
            raise ValueError("This word-alignment adapter only requests class and group logits.")
        classes, groups = [], []
        for chunk in audio_batch.split(self.batch_size):
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                self.calls += 1
            try:
                with torch.inference_mode():
                    c, g = self.extractor.predict(chunk, return_embeddings=False, groups_only=False)
                classes.append(c)
                groups.append(g)
            finally:
                with self.lock:
                    self.active -= 1
        return torch.cat(classes), torch.cat(groups)


class CUPEAligner:
    def __init__(self, checkpoint, language="en-us", window_batch_size=64):
        if importlib.metadata.version("bournemouth-forced-aligner") != "1.1.5":
            raise RuntimeError("Review this adapter before changing BFA 1.1.5.")
        if window_batch_size < 1:
            raise ValueError("window_batch_size must be positive")
        self.base = PhonemeTimestampAligner(
            cupe_ckpt_path=str(checkpoint), lang=language, device="cpu",
        )
        self.parameter_count = sum(p.numel() for p in self.base.extractor.parameters())
        self.predictor = BoundedPredictor(self.base.extractor, window_batch_size)
        self.phonemizer_lock = threading.Lock()

    def align(self, audio_path, transcript):
        # Same FFmpeg int16 mono/16 kHz decoding as the current lightweight path.
        pcm = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(audio_path),
             "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", "-"],
            check=True, capture_output=True,
        ).stdout
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if not len(samples):
            raise ValueError("Empty audio")
        waveform = torch.from_numpy(samples).unsqueeze(0)
        context = copy.copy(self.base)
        context.extractor = self.predictor
        context.seg_duration_max = math.ceil(len(samples) / 16000)
        context.wav_len_max = context.seg_duration_max * 16000
        context.reset_counters()
        context._setup_decoders()
        for decoder in (context.alignment_utils_p, context.alignment_utils_g):
            decoder.viterbi_decoder._neg_inf = float("-inf")

        def phonemize(text):
            with self.phonemizer_lock:
                return self.base.phonemize_sentence(text)

        context.phonemize_sentence = phonemize
        with torch.inference_mode():
            result = context.process_sentence(transcript, waveform, debug=False)
        result["audio_samples"] = len(samples)
        result["audio_duration_seconds"] = len(samples) / 16000
        result["max_segment_seconds"] = context.seg_duration_max
        for segment in result["segments"]:
            # Upstream word aggregation assumes a complete, ordered phone list.
            indices = [p["target_seq_idx"] for p in segment["phoneme_ts"]]
            if indices != list(range(len(segment["ph66"]))):
                error = ValueError("Incomplete or reordered phoneme path; cannot safely assign word timings")
                error.alignment_result = result
                raise error
        words = [word for seg in result["segments"] for word in seg["words_ts"]
                 if word["word"] != "<sil>"]
        expected = transcript.split()
        if [normalized_word(w["word"]) for w in words] != [normalized_word(w) for w in expected]:
            error = ValueError(f"CUPE word coverage mismatch: {len(words)} returned, {len(expected)} expected")
            error.alignment_result = result
            raise error
        # Preserve the user's spelling/punctuation, without changing any timestamps.
        aligned = [{"text": original, "start": word["start_ms"] / 1000,
                    "end": word["end_ms"] / 1000, "confidence": word["confidence"]}
                   for original, word in zip(expected, words)]
        return aligned, result
