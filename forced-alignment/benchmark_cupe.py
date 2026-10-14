"""Fresh-process, offline CUPE single/two-request benchmark on the saved sample."""

import time
STARTED = time.perf_counter()

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import resource
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from benchmark_lightweight import read_cues
from generate_srt import format_timestamp


def peak_ram():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def compare(actual, reference):
    if [r[0] for r in actual] != [r[0] for r in reference]:
        raise ValueError("Transcript mismatch")
    deltas = sorted(abs(a[k] - b[k]) for a, b in zip(actual, reference) for k in (1, 2))
    return {
        "words": len(actual), "changed_words": sum(a != b for a, b in zip(actual, reference)),
        "mean_boundary_difference_ms": sum(deltas) / len(deltas),
        "median_boundary_difference_ms": (deltas[len(deltas)//2-1] + deltas[len(deltas)//2]) / 2,
        "p95_boundary_difference_ms": deltas[math.ceil(.95 * len(deltas)) - 1],
        "max_boundary_difference_ms": max(deltas),
        "words_both_boundaries_within_ms": {
            str(limit): sum(max(abs(a[1]-b[1]), abs(a[2]-b[2])) <= limit for a,b in zip(actual,reference))
            for limit in (20, 50, 100, 200, 500, 1000)
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, choices=(1, 2), required=True)
    parser.add_argument("--name", required=True, help="Unique result suffix; outputs never overwritten")
    parser.add_argument("--window-batch-size", type=int, default=64)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    sample = root / "output/sample-2026-10-14"
    checkpoint = root / ".cache/cupe-mswc38/ckpt/multi_mswc38_ug20_e59_val_GER=0.5611.ckpt"
    report_path = sample / f"benchmark.{args.name}.json"
    outputs = [sample / f"words.{args.name}.{i}.srt" for i in range(1, args.requests+1)]
    if report_path.exists() or any(p.exists() for p in outputs):
        raise FileExistsError("Use a new --name")
    transcript = " ".join((sample / "transcript.txt").read_text().split())
    imported = time.perf_counter()
    import torch
    from cupe_alignment import CUPEAligner
    import_seconds = time.perf_counter() - imported
    after_import_ram = peak_ram()
    load_started = time.perf_counter()
    model = CUPEAligner(checkpoint, window_batch_size=args.window_batch_size)
    load_seconds = time.perf_counter() - load_started
    after_load_ram = peak_ram()
    print(f"Loaded {model.parameter_count:,} parameters; PyTorch CPU threads={torch.get_num_threads()}", flush=True)
    barrier = threading.Barrier(args.requests + 1)

    def request(index):
        barrier.wait()
        started = time.perf_counter()
        try:
            aligned, raw = model.align(sample / "speech.mp3", transcript)
        except ValueError as error:
            if hasattr(error, "alignment_result"):
                with (sample / f"failure.{args.name}.{index}.json").open("x") as file:
                    json.dump({"error": str(error), "seconds": time.perf_counter()-started,
                               "peak_ram_bytes": peak_ram(), "raw": error.alignment_result}, file, indent=2)
            raise
        cues = [(w["text"], round(w["start"]*1000), round(w["end"]*1000)) for w in aligned]
        with outputs[index-1].open("x") as file:
            for number, (word, start, end) in enumerate(cues, 1):
                if start < 0 or end <= start:
                    raise ValueError(f"Invalid word timing: {word}, {start}, {end}")
                file.write(f"{number}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{word}\n\n")
        seconds = time.perf_counter() - started
        print(f"Request {index}: {seconds:.3f}s, {len(cues)} words", flush=True)
        return {"request": index, "seconds": seconds, "word_count": len(cues),
                "overlapping_adjacent_words": sum(a[2] > b[1] for a,b in zip(cues, cues[1:])),
                "out_of_bounds_words": sum(a[1] < 0 or a[2] > 118152 for a in cues),
                "output": outputs[index-1].name}, raw

    with ThreadPoolExecutor(max_workers=args.requests) as executor:
        futures = [executor.submit(request, i) for i in range(1, args.requests+1)]
        process_started = time.perf_counter()
        barrier.wait()
        returned = [future.result() for future in futures]
        both_seconds = time.perf_counter() - process_started
    total_seconds = time.perf_counter() - STARTED
    ram = peak_ram()
    results = [r[0] for r in returned]
    report = {
        "model": "Tabahi/CUPE-2i / multi_mswc38_ug20_e59_val_GER=0.5611.ckpt",
        "parameters": model.parameter_count, "backend": "pytorch", "dtype": "float32", "device": "cpu",
        "versions": {name: importlib.metadata.version(name) for name in ("bournemouth-forced-aligner", "torch", "torchaudio", "phonemizer")},
        "phonemizer_library": os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"),
        "torch_cpu_threads": torch.get_num_threads(), "torch_interop_threads": torch.get_num_interop_threads(),
        "shared_model": True, "requests": args.requests, "model_window_ms": 120, "model_stride_ms": 80,
        "window_batch_size": args.window_batch_size, "silence_anchors": model.base.silence_anchors,
        "reference_timings_used_as_input": False,
        "decoder_impossible_state_score": "-Infinity (fixes upstream -1000 sentinel for long audio)",
        "dependency_import_seconds": import_seconds, "model_load_seconds": load_seconds,
        "processing_seconds_excluding_setup": both_seconds,
        "total_seconds_including_imports_and_model_loading": total_seconds,
        "peak_process_ram_bytes": ram, "peak_process_ram_gib": ram/1024**3,
        "peak_after_imports_bytes": after_import_ram, "peak_after_model_loading_bytes": after_load_ram,
        "maximum_overlapping_model_calls": model.predictor.maximum_active, "model_batch_calls": model.predictor.calls,
        "results": results,
        "concurrent_outputs_byte_identical": len(outputs) == 2 and outputs[0].read_bytes() == outputs[1].read_bytes(),
        "input_sha256": {name: hashlib.sha256((sample/name).read_bytes()).hexdigest() for name in ("speech.mp3", "transcript.txt")},
        "comparisons": {},
    }
    actual = read_cues(outputs[0])
    for reference in ("words.lightweight.comparison.srt", "words.int8.batch1.srt", "words.srt"):
        report["comparisons"][reference] = compare(actual, read_cues(sample/reference))
    reference = read_cues(sample / "words.lightweight.comparison.srt")
    with (sample / f"timings.{args.name}.csv").open("x") as file:
        writer = csv.writer(file)
        writer.writerow(["index", "word", "current_start_ms", "current_end_ms", "cupe_start_ms", "cupe_end_ms", "start_delta_ms", "end_delta_ms"])
        for i, (a, b) in enumerate(zip(actual, reference), 1):
            writer.writerow([i, a[0], *b[1:], *a[1:], a[1]-b[1], a[2]-b[2]])
    for i, (_, raw) in enumerate(returned, 1):
        with (sample / f"alignment.{args.name}.{i}.json").open("x") as file:
            json.dump(raw, file, indent=2)
    with report_path.open("x") as file:
        json.dump(report, file, indent=2)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
