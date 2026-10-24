"""Generate speech and Aeneas word subtitles for each supplied language passage."""

import argparse
import json
import subprocess
from pathlib import Path
from time import perf_counter

from align_words import MINIMUM_PAUSE_SECONDS, force_align
from generate_srt import render_srt


# Voice IDs checked against Microsoft's official language-support catalogue.
# https://learn.microsoft.com/azure/ai-services/speech-service/language-support?tabs=tts
LANGUAGES = {
    "en": ("English", "eng", "en-US-AriaNeural"),
    "hi": ("Hindi", "hin", "hi-IN-SwaraNeural"),
    "es": ("Spanish", "spa", "es-ES-ElviraNeural"),
    "fr": ("French", "fra", "fr-FR-DeniseNeural"),
    "de": ("German", "deu", "de-DE-KatjaNeural"),
    "it": ("Italian", "ita", "it-IT-ElsaNeural"),
}


def save_json(path: Path, data: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("passages", type=Path, help="JSON object mapping language codes to text")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--node", default="node", help="Node with built-in TypeScript stripping")
    args = parser.parse_args()
    passages = json.loads(args.passages.read_text(encoding="utf-8-sig"))
    if not isinstance(passages, dict) or not passages:
        parser.error("The JSON must contain a nonempty language-to-text object.")
    unknown = set(passages) - set(LANGUAGES)
    if unknown:
        parser.error(f"Voice and alignment-language mappings are required for: {sorted(unknown)}")
    if any(not isinstance(text, str) or not text.strip() for text in passages.values()):
        parser.error("Every passage must be a nonempty string.")
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    save_json(output / "passages.json", passages)
    results = []
    started = perf_counter()

    for code, text in passages.items():
        name, alignment_language, voice = LANGUAGES[code]
        directory = output / code
        directory.mkdir()
        transcript = directory / "transcript.txt"
        transcript.write_text(text, encoding="utf-8")
        report = {"language": name, "code": code, "aeneas_language": alignment_language, "voice": voice}
        print(f"[{code}] Generating {name} speech ({len(text)} characters)...", flush=True)
        try:
            generation = subprocess.run([
                args.node, str(Path(__file__).with_name("generate_audio.mjs")),
                str(transcript), voice, str(directory),
            ], text=True, capture_output=True, timeout=200)
            if generation.returncode:
                raise RuntimeError(generation.stderr.strip() or "Audio generation failed")
            speech = directory / "speech.mp3"
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(speech),
            ], text=True, capture_output=True, check=True)
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            # Decode the full generated MP3, so a readable header alone does not
            # count as successful audio generation.
            subprocess.run([
                "ffmpeg", "-v", "error", "-xerror", "-i", str(speech), "-f", "null", "-",
            ], capture_output=True, text=True, check=True)
            print(f"[{code}] Generated {duration:.2f}s. Running Aeneas...", flush=True)
            align_started = perf_counter()
            words = force_align(text, speech, alignment_language)
            alignment_seconds = perf_counter() - align_started
            srt, collapsed = render_srt(words, duration)
            (directory / "words.srt").write_text(srt, encoding="utf-8")
            save_json(directory / "words.json", [word._asdict() for word in words])
            generation_report = json.loads((directory / "generation.json").read_text())
            report.update({
                "status": "completed", "characters": len(text),
                "transcript_words": len(text.split()), "srt_cues": len(words),
                "audio_duration_seconds": duration,
                "generation_seconds": generation_report["generation_seconds"],
                "alignment_seconds": round(alignment_seconds, 3),
                "zero_duration_cues": collapsed,
                "word_sequence_matches_transcript": True,
                "audio_fully_decoded": True,
                "aeneas_adjust_zero_duration_boundaries": True,
                "aeneas_remove_nonspeech": True,
                "minimum_pause_seconds": MINIMUM_PAUSE_SECONDS,
                "timing_accuracy_manually_verified": False,
                "audio": str(speech), "srt": str(directory / "words.srt"),
            })
            print(f"[{code}] Saved {len(words)} cues; alignment {alignment_seconds:.3f}s.", flush=True)
        except Exception as error:
            # Preserve completed languages and any audio when one language fails.
            report.update({"status": "failed", "error": str(error)})
            print(f"[{code}] Failed: {error}", flush=True)
        save_json(directory / "report.json", report)
        results.append(report)

    save_json(output / "summary.json", {
        "source": str(args.passages.expanduser().resolve()),
        "total_elapsed_seconds": round(perf_counter() - started, 3),
        "results": results,
    })
    print(f"Results saved in {output}", flush=True)
    if any(result["status"] != "completed" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
