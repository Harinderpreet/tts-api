"""Align a supplied transcript to audio and export one SRT cue per word."""

import argparse
import math
import shutil
from pathlib import Path

from alignment_config import DEFAULT_MODEL_PATH, DEFAULT_WINDOW_SECONDS, DEFAULT_CPU_THREADS


def align_words(
    audio_path: Path, transcript: str, language: str, alignment_model: str | None = None,
    batch_size: int = 4,
) -> list[dict]:
    """Return word timestamps, optionally using a converted CTranslate2 model."""
    import torch
    from ctc_forced_aligner import (
        generate_emissions,
        get_alignments,
        get_spans,
        load_alignment_model,
        load_audio,
        postprocess_results,
        preprocess_text,
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_options = {"model_path": alignment_model} if alignment_model else {}
    model, tokenizer = load_alignment_model(device, dtype=torch.float32, **model_options)
    waveform = load_audio(str(audio_path), model.dtype, model.device)
    if waveform.numel() == 0:
        raise ValueError("The audio file contains no audio samples.")

    tokens, text = preprocess_text(
        transcript,
        romanize=True,
        language=language,
        split_size="word",
        star_frequency="edges",
    )
    if not any(token.strip() for token in tokens if token != "<star>"):
        raise ValueError("The transcript contains no alignable speech text.")

    emissions, stride = generate_emissions(model, waveform, batch_size=batch_size)
    segments, scores, blank_token = get_alignments(emissions, tokens, tokenizer)
    spans = get_spans(tokens, segments, blank_token)
    return postprocess_results(text, spans, stride, scores)


def format_timestamp(milliseconds: int) -> str:
    """Format whole milliseconds as an SRT timestamp, including hour rollover."""
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def render_word_srt(words: list[dict]) -> str:
    """Validate and serialize word timings for file and service callers."""
    if not words:
        raise ValueError("The aligner returned no word timestamps.")

    cues = []
    previous_end = 0
    for index, word in enumerate(words, start=1):
        start, end = float(word["start"]), float(word["end"])
        text = str(word["text"]).strip()
        if not text or len(text.split()) != 1:
            raise ValueError(f"Alignment cue {index} does not contain a single word.")
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f"Invalid alignment timing for word {index}: {text!r}.")

        start_ms, end_ms = round(start * 1000), round(end * 1000)
        if end_ms <= start_ms or start_ms < previous_end:
            raise ValueError(f"Collapsed or overlapping timing for word {index}: {text!r}.")
        previous_end = end_ms
        cues.append(
            f"{index}\n{format_timestamp(start_ms)} --> {format_timestamp(end_ms)}\n{text}\n\n"
        )

    return "".join(cues)


def write_word_srt(words: list[dict], output_path: Path) -> None:
    """Write validated word subtitles without overwriting an existing file."""
    content = render_word_srt(words)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)


def generate_word_srt(
    audio_path: str,
    transcript: str,
    language: str,
    output_path: str | None = None,
    alignment_model: str | None = None,
    batch_size: int = 1,
    lightweight: bool = True,
    window_seconds: int | None = None,
    cpu_threads: int | None = None,
    streaming: bool | None = None,
) -> Path:
    """Generate an SRT from transcript text; return the saved absolute path.

    language must be an ISO 639-3 code. Existing output files are preserved.
    Defaults to cached CPU int8, streaming, 10-second windows and two threads.
    Set lightweight=False for the original package backend. Unspecified window,
    thread and streaming options then use its original 30/0/False settings.
    """
    if window_seconds is None:
        window_seconds = DEFAULT_WINDOW_SECONDS if lightweight else 30
    if cpu_threads is None:
        cpu_threads = DEFAULT_CPU_THREADS if lightweight else 0
    if streaming is None:
        streaming = lightweight
    audio = Path(audio_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve() if output_path else audio.with_suffix(".srt")
    transcript = " ".join(transcript.split())
    language = language.strip().lower()
    if not audio.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio}")
    if batch_size < 1:
        raise ValueError("Batch size must be at least 1.")
    if not transcript:
        raise ValueError("The transcript must not be empty.")
    if len(language) != 3 or not language.isascii() or not language.isalpha():
        raise ValueError("Provide an ISO 639-3 language code, such as eng for English.")
    if language in {"jpn", "chi"}:
        raise ValueError("This package forces character-level alignment for jpn/chi; word-level output is unavailable.")
    if output.suffix.lower() != ".srt":
        raise ValueError("The output path must have an .srt extension.")
    if output.exists():
        raise FileExistsError(f"Output already exists; choose another path: {output}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg is required and must be available on PATH.")

    if lightweight:
        alignment_model = alignment_model or DEFAULT_MODEL_PATH
        from light_ct2 import LightCT2Aligner

        words = LightCT2Aligner(
            alignment_model, intra_threads=cpu_threads,
            window_length=window_seconds, streaming=streaming,
        ).align(audio, transcript, language, batch_size)
    else:
        if streaming or window_seconds != 30 or cpu_threads != 0:
            raise ValueError("Window, thread and streaming options require --lightweight")
        words = align_words(audio, transcript, language, alignment_model, batch_size)
    write_word_srt(words, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_path", help="Path to the audio file")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--transcript", help="The exact spoken transcript")
    source.add_argument("--transcript-file", type=Path, help="UTF-8 text file containing the transcript")
    parser.add_argument("--language", required=True, help="ISO 639-3 code, e.g. eng")
    parser.add_argument("--output", help="SRT destination; defaults to the audio path with .srt extension")
    parser.add_argument("--alignment-model", help=f"Converted model directory (default: {DEFAULT_MODEL_PATH}); with --no-lightweight, also accepts a model name")
    parser.add_argument("--batch-size", type=int, default=1, help="Audio windows processed together (default: 1); try 2 or 4 when benchmarking")
    parser.add_argument("--lightweight", action=argparse.BooleanOptionalAction, default=True, help="Use CPU int8 without torch/transformers (default); --no-lightweight selects the original backend")
    parser.add_argument("--streaming", action=argparse.BooleanOptionalAction, default=None, help="Decode incrementally (default with lightweight); --no-streaming buffers full audio")
    parser.add_argument("--window-seconds", type=int, choices=(5,10,30), help="Central window duration (default: 10; original backend: 30)")
    parser.add_argument("--cpu-threads", type=int, help="Threads per worker (default: 2; original backend: 0); 0 uses backend threading")
    args = parser.parse_args()

    try:
        transcript = (
            args.transcript_file.expanduser().read_text(encoding="utf-8-sig")
            if args.transcript_file is not None
            else args.transcript
        )
        output = generate_word_srt(
            args.audio_path, transcript, args.language, args.output, args.alignment_model,
            args.batch_size, args.lightweight, args.window_seconds, args.cpu_threads, args.streaming,
        )
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Saved word-level SRT: {output}")


if __name__ == "__main__":
    main()
