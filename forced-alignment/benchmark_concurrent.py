"""Measure two concurrent requests sharing one cached CTranslate2 int8 model.

Run from the repository root with HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1.
Uses the saved sample; writes new SRTs and a benchmark report without overwrites.
"""

import time

PROCESS_STARTED = time.perf_counter()

import argparse
import json
import resource
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ctranslate2

from generate_srt import write_word_srt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lightweight", action="store_true")
    parser.add_argument("--name", help="Optional unique output/report suffix")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    sample = folder / "output/sample-2026-10-14"
    model_path = folder / ".cache/mms-300m-ct2-int8"
    suffix = ".lightweight" if args.lightweight else ""
    name = args.name or f"concurrent{suffix}"
    outputs = [sample / f"words.{name}.{index}.srt" for index in (1, 2)]
    report_path = sample / f"benchmark.{name}.json"
    for path in [*outputs, report_path]:
        if path.exists():
            raise FileExistsError(path)
    transcript = " ".join((sample / "transcript.txt").read_text().split())
    expected_srt = (sample / "words.int8.batch1.srt").read_bytes()

    if args.lightweight:
        from light_ct2 import LightCT2Aligner
    else:
        from transformers import AutoTokenizer
        from ctc_forced_aligner import (
            CTranslate2AlignmentModel, generate_emissions, get_alignments,
            get_spans, load_audio, postprocess_results, preprocess_text,
        )

    load_started = time.perf_counter()
    # Two inference workers are needed: two callers with the default single
    # worker would queue their model calls rather than execute them in parallel.
    if args.lightweight:
        model = LightCT2Aligner(str(model_path), workers=2, intra_threads=0,
                               window_length=30, streaming=False)
    else:
        model = CTranslate2AlignmentModel(
            str(model_path), device="cpu", compute_type="int8", inter_threads=2
        )
        tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    load_seconds = time.perf_counter() - load_started
    assert model.model.num_workers == 2

    barrier = threading.Barrier(3)
    stop_monitor = threading.Event()
    observed_active_batches = []

    def monitor():
        while not stop_monitor.is_set():
            observed_active_batches.append(model.model.num_active_batches)
            stop_monitor.wait(0.01)

    def request(index, output):
        barrier.wait()
        started = time.perf_counter()
        if args.lightweight:
            words = model.align(sample / "speech.mp3", transcript, "eng", batch_size=1)
        else:
            waveform = load_audio(str(sample / "speech.mp3"), model.dtype, model.device)
            tokens, text = preprocess_text(
                transcript, romanize=True, language="eng",
                split_size="word", star_frequency="edges",
            )
            emissions, stride = generate_emissions(
                model, waveform, window_length=30, context_length=2, batch_size=1
            )
            segments, scores, blank = get_alignments(emissions, tokens, tokenizer)
            spans = get_spans(tokens, segments, blank)
            words = postprocess_results(text, spans, stride, scores)
        write_word_srt(words, output)
        seconds = time.perf_counter() - started
        print(f"Request {index} finished in {seconds:.3f} seconds", flush=True)
        return {
            "request": index,
            "seconds_including_audio_processing_and_srt_write": seconds,
            "word_count": len(words),
            "transcript_matches": [word["text"] for word in words] == transcript.split(),
            "matches_single_request_int8_srt": output.read_bytes() == expected_srt,
            "output": str(output),
        }

    sampler = threading.Thread(target=monitor, daemon=True)
    sampler.start()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(request, index, path) for index, path in enumerate(outputs, 1)]
            both_started = time.perf_counter()
            barrier.wait()
            results = [future.result() for future in futures]
            both_seconds = time.perf_counter() - both_started
    finally:
        stop_monitor.set()
        sampler.join()

    process_seconds = time.perf_counter() - PROCESS_STARTED
    raw_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = raw_peak if sys.platform == "darwin" else raw_peak * 1024
    heavy_imports = [name for name in ("torch", "transformers") if name in sys.modules]
    if args.lightweight and heavy_imports:
        raise RuntimeError(f"Unexpected heavyweight imports: {heavy_imports}")
    report = {
        "backend": "ctranslate2", "version": ctranslate2.__version__,
        "lightweight": args.lightweight, "heavyweight_libraries_imported": heavy_imports,
        "compute_type": model.model.compute_type, "device": "cpu",
        "shared_model": True, "inference_workers": model.model.num_workers,
        "intra_threads": "backend default", "requests": 2,
        "audio_duration_seconds_per_request": 118.152,
        "window_seconds": 30, "context_seconds_each_side": 2, "batch_size": 1,
        "cached_model_load_seconds": load_seconds,
        "both_requests_seconds_excluding_setup": both_seconds,
        "total_seconds_including_imports_and_model_loading": process_seconds,
        "combined_peak_process_ram_bytes": peak_bytes,
        "combined_peak_process_ram_gib": peak_bytes / 1024**3,
        "maximum_observed_active_inference_batches": max(observed_active_batches, default=0),
        "results": results,
    }
    with report_path.open("x") as file:
        json.dump(report, file, indent=2)
        file.write("\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
