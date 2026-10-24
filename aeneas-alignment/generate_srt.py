"""Generate one SRT cue per transcript word using the linked Aeneas approach."""

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from align_words import MINIMUM_PAUSE_SECONDS, ForceAlignedText, force_align


def timestamp(milliseconds: int) -> str:
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(words: list[ForceAlignedText], duration: float) -> tuple[str, int]:
    """Validate timings and retain raw boundaries, including collapsed cues."""
    cues = []
    previous_end = 0
    collapsed = 0
    for index, word in enumerate(words, start=1):
        start, end = word.start_sec, word.end_sec
        if not (math.isfinite(start) and math.isfinite(end)):
            raise ValueError(f"Non-finite timing at word {index}.")
        if start < 0 or end < start or end > duration + 0.001:
            raise ValueError(f"Timing outside the audio at word {index}: {word}.")
        start_ms, end_ms = round(start * 1000), round(end * 1000)
        if start_ms < previous_end:
            raise ValueError(f"Overlapping timing at word {index}: {word}.")
        if len(word.text.split()) != 1:
            raise ValueError(f"Cue {index} must contain exactly one word.")
        collapsed += start_ms == end_ms
        cues.append(
            f"{index}\n{timestamp(start_ms)} --> {timestamp(end_ms)}\n{word.text}\n\n"
        )
        previous_end = end_ms
    if not cues:
        raise ValueError("The aligner returned no words.")
    return "".join(cues), collapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--transcript-file", type=Path, required=True)
    parser.add_argument("--language", required=True, help="Aeneas language code; eng = English")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for results")
    args = parser.parse_args()

    try:
        audio = args.audio.expanduser().resolve()
        transcript_path = args.transcript_file.expanduser().resolve()
        output = args.output_dir.expanduser().resolve()
        if not audio.is_file():
            raise FileNotFoundError(f"Audio not found: {audio}")
        transcript = transcript_path.read_text(encoding="utf-8-sig")
        if not transcript.split():
            raise ValueError("The transcript contains no words.")
        if len(args.language) != 3 or not args.language.isascii() or not args.language.isalpha():
            raise ValueError("Supply a three-letter Aeneas language code.")
        if output.exists():
            raise FileExistsError(f"Choose a new output directory: {output}")
        for executable in ("ffmpeg", "ffprobe", "espeak"):
            if shutil.which(executable) is None:
                raise RuntimeError(f"Required executable missing: {executable}")
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(audio),
        ], check=True, capture_output=True, text=True)
        duration = float(json.loads(probe.stdout)["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Audio duration must be positive and finite.")

        print(f"Aligning {len(transcript.split())} words to {duration:.3f}s of audio...", flush=True)
        started = perf_counter()
        words = force_align(transcript, audio, args.language.lower())
        alignment_seconds = perf_counter() - started
        srt, collapsed = render_srt(words, duration)
        output.mkdir(parents=True, exist_ok=False)
        (output / "words.srt").write_text(srt, encoding="utf-8")
        (output / "words.json").write_text(
            json.dumps([word._asdict() for word in words], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report = {
            "method": "Aeneas word-per-line alignment (John Meade gist adaptation)",
            "audio": str(audio),
            "transcript": str(transcript_path),
            "language": args.language.lower(),
            "audio_duration_seconds": duration,
            "transcript_words": len(transcript.split()),
            "srt_cues": len(words),
            "alignment_seconds": round(alignment_seconds, 3),
            "audio_seconds_per_processing_second": round(duration / alignment_seconds, 3),
            "first_word_start_seconds": words[0].start_sec,
            "last_word_end_seconds": words[-1].end_sec,
            "zero_duration_cues": collapsed,
            "aeneas_adjust_zero_duration_boundaries": True,
            "aeneas_remove_nonspeech": True,
            "minimum_pause_seconds": MINIMUM_PAUSE_SECONDS,
            "word_sequence_matches_transcript": True,
            "timing_accuracy_manually_verified": False,
            "srt": str(output / "words.srt"),
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        if collapsed:
            print(f"WARNING: {collapsed} cues have zero duration; raw timings were retained.", file=sys.stderr)
        print("\nFirst 12 cues:\n" + "\n\n".join(srt.strip().split("\n\n")[:12]))
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
