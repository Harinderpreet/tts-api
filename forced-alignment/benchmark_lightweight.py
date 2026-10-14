"""Compare fresh-process standard/lightweight int8 paths on the saved sample."""

import time

STARTED = time.perf_counter()

import argparse
import json
import resource
import sys
from pathlib import Path

from generate_srt import generate_word_srt


def peak_ram():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def read_cues(path):
    cues = []
    for index, block in enumerate(path.read_text().strip().split("\n\n"), 1):
        number, timing, word = block.splitlines()
        if int(number) != index:
            raise ValueError("Invalid SRT numbering")
        boundaries = []
        for timestamp in timing.split(" --> "):
            hours, minutes, remainder = timestamp.split(":")
            seconds, milliseconds = remainder.split(",")
            boundaries.append(int(hours) * 3600000 + int(minutes) * 60000 + int(seconds) * 1000 + int(milliseconds))
        cues.append((word, *boundaries))
    return cues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("standard", "lightweight"))
    parser.add_argument("--name", help="Optional unique output/report suffix")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    sample = folder / "output/sample-2026-10-14"
    name = args.name or f"{args.mode}.comparison"
    output = sample / f"words.{name}.srt"
    report_path = sample / f"benchmark.{name}.json"
    if output.exists() or report_path.exists():
        raise FileExistsError("Choose a new output name before rerunning this benchmark.")
    transcript = (sample / "transcript.txt").read_text().strip()
    stages = {}
    import_started = time.perf_counter()
    if args.mode == "lightweight":
        import light_ct2
        original = light_ct2.LightCT2Aligner

        def load(*a, **kw):
            begin = time.perf_counter()
            result = original(*a, **kw)
            stages["model_load_seconds"] = time.perf_counter() - begin
            stages["peak_ram_after_model_load_bytes"] = peak_ram()
            return result

        light_ct2.LightCT2Aligner = load
    else:
        import ctc_forced_aligner
        original = ctc_forced_aligner.load_alignment_model

        def load(*a, **kw):
            begin = time.perf_counter()
            result = original(*a, **kw)
            stages["model_load_seconds"] = time.perf_counter() - begin
            stages["peak_ram_after_model_load_bytes"] = peak_ram()
            return result

        ctc_forced_aligner.load_alignment_model = load
    stages["dependency_import_seconds"] = time.perf_counter() - import_started
    stages["peak_ram_after_imports_bytes"] = peak_ram()
    print(f"Starting {args.mode} alignment", flush=True)
    generation_started = time.perf_counter()
    generate_word_srt(
        str(sample / "speech.mp3"), transcript, "eng", str(output),
        str(folder / ".cache/mms-300m-ct2-int8"), batch_size=1,
        lightweight=args.mode == "lightweight",
        window_seconds=30, cpu_threads=0, streaming=False,
    )
    elapsed_generation = time.perf_counter() - generation_started
    total = time.perf_counter() - STARTED
    peak_bytes = peak_ram()
    heavy_imports = [name for name in ("torch", "transformers") if name in sys.modules]
    if args.mode == "lightweight" and heavy_imports:
        raise RuntimeError(f"Unexpected heavyweight imports: {heavy_imports}")
    reference_path = sample / "words.int8.batch1.srt"
    reference, actual = read_cues(reference_path), read_cues(output)
    words_match = [row[0] for row in actual] == transcript.split() == [row[0] for row in reference]
    assert words_match and all(0 <= start < end <= 118152 for _, start, end in actual)
    assert all(left[2] <= right[1] for left, right in zip(actual, actual[1:]))
    differences = [abs(a[column] - b[column]) for a, b in zip(actual, reference) for column in (1, 2)]
    report = {
        "mode": args.mode, "backend": "ctranslate2", "compute_type": "int8_float32",
        "device": "cpu", "batch_size": 1, "window_seconds": 30, "context_seconds": 2,
        "audio_duration_seconds": 118.152, "transcript_characters": len(transcript),
        "total_seconds_including_imports_and_model_loading": total,
        "generation_seconds_excluding_imports_and_model_load": elapsed_generation - stages["model_load_seconds"],
        "peak_process_ram_bytes": peak_bytes, "peak_process_ram_gib": peak_bytes / 1024**3,
        "heavyweight_libraries_imported": heavy_imports, "stages": stages,
        "comparison": {
            "reference": reference_path.name, "words": len(actual), "words_match": words_match,
            "srt_byte_identical": output.read_bytes() == reference_path.read_bytes(),
            "changed_words": sum(a[1:] != b[1:] for a, b in zip(actual, reference)),
            "mean_boundary_difference_ms": sum(differences) / len(differences),
            "max_boundary_difference_ms": max(differences),
        },
    }
    with report_path.open("x") as file:
        json.dump(report, file, indent=2)
        file.write("\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
