"""Focused local check of short-pause preservation and long-pause caption gaps."""

import argparse
import array
import json
import subprocess
import wave
from pathlib import Path
from time import perf_counter

from align_words import MINIMUM_PAUSE_SECONDS, force_align
from generate_srt import render_srt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "output" / "pause-1s-check")
    output = parser.parse_args().output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    phrases = [
        "We start with the first sentence and then take a short break.",
        "This second sentence follows the short break and leads into a longer pause.",
        "The final sentence begins after the long pause and finishes this demonstration.",
    ]
    samples = array.array("h")
    fixture_pauses = []
    sample_rate = None
    for index, phrase in enumerate(phrases):
        part = output / f"part-{index + 1}.wav"
        subprocess.run(["espeak", "-v", "en-us", "-s", "160", "-w", str(part), phrase], check=True)
        with wave.open(str(part), "rb") as source:
            assert source.getnchannels() == 1 and source.getsampwidth() == 2
            rate = source.getframerate()
            assert sample_rate is None or sample_rate == rate
            sample_rate = rate
            speech = array.array("h", source.readframes(source.getnframes()))
        # Trim only fixture edges so injected pauses have known durations.
        audible = [i for i, value in enumerate(speech) if abs(value) > 100]
        assert audible, "Fixture synthesis returned no audible samples"
        samples.extend(speech[audible[0]:audible[-1] + 1])
        if index < 2:
            pause_seconds = (0.5, 1.5)[index]
            start = len(samples) / sample_rate
            samples.extend(array.array("h", [0]) * round(pause_seconds * sample_rate))
            fixture_pauses.append({"start": start, "end": len(samples) / sample_rate})

    audio = output / "speech.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(samples.tobytes())
    transcript = " ".join(phrases)
    (output / "transcript.txt").write_text(transcript, encoding="utf-8")
    started = perf_counter()
    words = force_align(transcript, audio, "eng")
    elapsed = perf_counter() - started
    srt, collapsed = render_srt(words, len(samples) / sample_rate)
    (output / "words.srt").write_text(srt, encoding="utf-8")
    gaps = [
        {"start": left.end_sec, "end": right.start_sec,
         "duration": round(right.start_sec - left.end_sec, 3),
         "previous_word": left.text, "next_word": right.text}
        for left, right in zip(words, words[1:])
        if round(right.start_sec * 1000) > round(left.end_sec * 1000)
    ]
    short, long = fixture_pauses
    intersects = lambda gap, pause: gap["start"] < pause["end"] and gap["end"] > pause["start"]
    checks = {
        "all_words_preserved": [word.text for word in words] == transcript.split(),
        "no_zero_duration_cues": collapsed == 0,
        "short_pause_stays_inside_word_cues": not any(intersects(gap, short) for gap in gaps),
        "long_pause_has_caption_free_gap": any(
            intersects(gap, long) and gap["duration"] >= MINIMUM_PAUSE_SECONDS for gap in gaps
        ),
    }
    report = {"minimum_pause_seconds": MINIMUM_PAUSE_SECONDS, "fixture_pauses": fixture_pauses,
              "caption_gaps": gaps, "alignment_seconds": round(elapsed, 3), "checks": checks}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    assert all(checks.values()), "Pause handling check failed; inspect report.json"


if __name__ == "__main__":
    main()
