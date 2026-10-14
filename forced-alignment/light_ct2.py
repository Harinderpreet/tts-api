"""CPU CTranslate2 alignment using NumPy, without torch or transformers imports.

Preserves fast-forced-aligner 0.3.0 chunk/frame and blank-padding conventions.
Uses its unchanged text normalization, romanization and native CTC kernel.
"""

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from itertools import islice

import ctranslate2
import numpy as np

from ctc_primitives import load_primitives
from alignment_config import DEFAULT_MODEL_PATH, DEFAULT_WINDOW_SECONDS, DEFAULT_CPU_THREADS

SAMPLE_RATE = 16000


def load_audio(audio_path: Path) -> np.ndarray:
    """Decode the same mono PCM samples used by the original implementation."""
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-threads", "0", "-i", str(audio_path),
         "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True, check=True,
    )
    samples = np.frombuffer(result.stdout, dtype="<i2").astype(np.float32)
    samples /= np.float32(32768)
    if not samples.size:
        raise ValueError("The audio file contains no audio samples.")
    return samples


def generate_emissions(model, waveform, batch_size=1, window_length=30, context_length=2):
    """Run bounded batches, keeping only the central frames from each window."""
    if batch_size < 1 or window_length <= 0 or context_length < 0:
        raise ValueError("Invalid batch size, window length or context length.")
    window = int(window_length * SAMPLE_RATE)
    length = waveform.size
    if length < window:
        chunks = waveform[None, :]
        extension = context = 0
    else:
        context = int(context_length * SAMPLE_RATE)
        extension = math.ceil(length / window) * window - length
        padded = np.pad(waveform, (context, context + extension))
        chunks = np.lib.stride_tricks.sliding_window_view(
            padded, window + 2 * context
        )[::window]
    parts = []
    for offset in range(0, len(chunks), batch_size):
        features = np.array(chunks[offset:offset + batch_size, None, :], copy=True, order="C")
        encoded = model.encode(ctranslate2.StorageView.from_array(features), to_cpu=True)
        logits = np.asarray(encoded)
        if context:
            frames = int(context_length * 50)
            logits = logits[:, frames:-frames + 1, :]
        parts.append(logits.reshape(-1, logits.shape[-1]).copy())
    logits = np.concatenate(parts)
    trim_frames = int(extension / SAMPLE_RATE * 50)
    if trim_frames:
        logits = logits[:-trim_frames]
    # Stable float32 log-softmax, equivalent to the original torch operation.
    logits -= logits.max(axis=-1, keepdims=True)
    normalizer = np.exp(logits).sum(axis=-1, keepdims=True)
    np.log(normalizer, out=normalizer)
    logits -= normalizer
    emissions = np.pad(logits, ((0, 0), (0, 1)))  # Unpenalized <star> column.
    stride = math.ceil(length * 1000 / len(emissions) / SAMPLE_RATE)
    return emissions, stride


def generate_streaming_emissions(model, audio_path, window_length=30, context_length=2, batch_size=1):
    """Keep PCM bounded and write normalized logits into one final CTC buffer."""
    from streaming_audio import decoded_windows

    if not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("Batch size must be a positive integer")
    parts = []
    with decoded_windows(audio_path, window_length, context_length) as stream:
        windows = iter(stream)
        while batch := list(islice(windows, batch_size)):
            features = np.stack([waveform for waveform, _ in batch])[:, None, :]
            has_context = batch[0][1]
            encoded = model.encode(
                ctranslate2.StorageView.from_array(features), to_cpu=True
            )
            logits = np.asarray(encoded)
            if has_context:
                frames = int(context_length * 50)
                logits = logits[:, frames:-frames + 1, :]
            parts.append(logits.reshape(-1, logits.shape[-1]).copy())
        length, extension = stream.sample_count, stream.extension
    frames = sum(len(part) for part in parts) - int(extension / SAMPLE_RATE * 50)
    if frames <= 0:
        raise ValueError("Audio is too short to align")
    emissions = np.empty((frames, parts[0].shape[1] + 1), dtype=np.float32)
    cursor = 0
    for part in parts:
        count = min(len(part), frames - cursor)
        if count == 0:
            break
        logits = part[:count]
        logits -= logits.max(axis=-1, keepdims=True)
        normalizer = np.exp(logits).sum(axis=-1, keepdims=True)
        np.log(normalizer, out=normalizer)
        logits -= normalizer
        emissions[cursor:cursor+count, :-1] = logits
        cursor += count
    emissions[:, -1] = 0  # Same unpenalized <star> column.
    return emissions, math.ceil(length * 1000 / frames / SAMPLE_RATE)


@dataclass
class FrameSpan:
    start: int
    end: int


def spans_from_path(path, token_ids, blank_id):
    """Match target tokens to CTC runs and split intervening blank runs equally.

    End frames are inclusive, matching the upstream postprocessor convention.
    """
    labels = np.asarray(path).reshape(-1)
    starts = np.r_[0, np.flatnonzero(labels[1:] != labels[:-1]) + 1]
    ends = np.r_[starts[1:] - 1, len(labels) - 1]
    runs = [(int(labels[start]), int(start), int(end)) for start, end in zip(starts, ends)]
    intervals = []
    cursor = 0
    for ids in token_ids:
        if not ids:
            if not intervals:
                raise ValueError("Empty initial alignment token.")
            intervals.append((intervals[-1][1], intervals[-1][1]))
            continue
        first = None
        for token in ids:
            while cursor < len(runs) and runs[cursor][0] == blank_id:
                cursor += 1
            if cursor == len(runs) or runs[cursor][0] != token:
                raise ValueError("Native CTC path does not match the transcript tokens.")
            if first is None:
                first = cursor
            last = cursor
            cursor += 1
        intervals.append((first, last))
    if any(run[0] != blank_id for run in runs[cursor:]):
        raise ValueError("Native CTC path has unmatched trailing tokens.")

    spans = []
    for index, (first, last) in enumerate(intervals):
        start, end = runs[first][1], runs[last][2]
        if first > 0 and runs[first - 1][0] == blank_id:
            _, left, right = runs[first - 1]
            start = left if index == 0 else (left + right) // 2
        if last + 1 < len(runs) and runs[last + 1][0] == blank_id:
            _, left, right = runs[last + 1]
            end = right if index == len(intervals) - 1 else (left + right) // 2
        spans.append([FrameSpan(start, end)])
    return spans


class LightCT2Aligner:
    """Reusable loaded CPU model; callers may retain it across requests."""

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH, workers: int = 1,
                 intra_threads: int = DEFAULT_CPU_THREADS,
                 window_length: int = DEFAULT_WINDOW_SECONDS, context_length: int = 2,
                 streaming: bool = True):
        if workers < 1 or intra_threads < 0 or window_length not in (5, 10, 30) or context_length != 2:
            raise ValueError("Use positive workers, nonnegative threads, 5/10/30s windows and 2s context")
        self.window_length = window_length
        self.context_length = context_length
        self.streaming = streaming
        directory = Path(model_path).expanduser().resolve()
        if not (directory / "model.bin").is_file():
            raise FileNotFoundError(
                f"Converted CTranslate2 model not found in {directory}. "
                "See forced-alignment/README.md for model conversion instructions."
            )
        self.text, self.forced_align = load_primitives()
        vocabulary = json.loads((directory / "vocab.json").read_text())
        config = json.loads((directory / "tokenizer_config.json").read_text())
        if config.get("tokenizer_class") != "Wav2Vec2CTCTokenizer":
            raise ValueError("Expected an exported Wav2Vec2CTCTokenizer vocabulary.")
        for index, token in config.get("added_tokens_decoder", {}).items():
            vocabulary[token["content"]] = int(index)
        self.vocabulary = {key.lower(): value for key, value in vocabulary.items()}
        if set(self.vocabulary.values()) != set(range(len(self.vocabulary))):
            raise ValueError("Vocabulary must have consecutive, unique token IDs.")
        blank_token = "<blank>" if "<blank>" in self.vocabulary else config["pad_token"].lower()
        self.blank = self.vocabulary[blank_token]
        self.vocabulary["<star>"] = len(self.vocabulary)
        self.model = ctranslate2.models.Wav2Vec2(
            str(directory), device="cpu", compute_type="int8", inter_threads=workers,
            intra_threads=intra_threads,
        )

    def align(self, audio_path: Path, transcript: str, language: str, batch_size: int = 1,
              phase_callback=None):
        phase = phase_callback or (lambda name: None)
        transcript = " ".join(transcript.split())
        if not transcript or language in {"jpn", "chi"}:
            raise ValueError("A nonempty transcript and word-level language are required.")
        phase("text_preparation")
        tokens, text = self.text.preprocess_text(
            transcript, romanize=True, language=language,
            split_size="word", star_frequency="edges",
        )
        if not any(token.strip() for token in tokens if token != "<star>"):
            raise ValueError("The transcript contains no alignable speech text.")
        if self.streaming:
            phase("streaming_inference")
            emissions, stride = generate_streaming_emissions(
                self.model, audio_path, self.window_length, self.context_length, batch_size
            )
        else:
            phase("audio_decode")
            waveform = load_audio(audio_path)
            phase("inference")
            emissions, stride = generate_emissions(
                self.model, waveform, batch_size=batch_size,
                window_length=self.window_length, context_length=self.context_length,
            )
            del waveform
        if emissions.shape[-1] != len(self.vocabulary):
            raise ValueError("Model output and tokenizer vocabulary sizes differ.")
        token_ids = [[self.vocabulary[c] for c in token.split() if c in self.vocabulary] for token in tokens]
        targets = np.asarray([[c for word in token_ids for c in word]], dtype=np.int64)
        if self.blank in targets or not targets.size:
            raise ValueError("Transcript has empty or invalid CTC targets.")
        phase("ctc_alignment")
        path, scores = self.forced_align(
            np.ascontiguousarray(emissions[None, :, :], dtype=np.float32), targets, self.blank
        )
        phase("word_boundaries")
        spans = spans_from_path(path, token_ids, self.blank)
        words = self.text.postprocess_results(text, spans, stride, scores)
        phase("complete")
        return words
