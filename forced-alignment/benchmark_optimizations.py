"""Profile a persistent shared-model process, including idle RSS after requests."""

import time
STARTED = time.perf_counter()

import argparse
import csv
import json
import hashlib
import platform
from pathlib import Path
import resource
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from memory_timeline import MemoryTimeline
from benchmark_lightweight import read_cues
from benchmark_cupe import compare
from alignment_config import (
    DEFAULT_MODEL_PATH, DEFAULT_WINDOW_SECONDS, DEFAULT_CPU_THREADS, DEFAULT_WORKERS,
    DEFAULT_BATCH_SIZE, DEFAULT_MAX_QUEUED, DEFAULT_QUEUE_TIMEOUT_SECONDS,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--streaming", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--window", type=int, choices=(5,10,30), default=DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--threads", type=int, default=DEFAULT_CPU_THREADS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--batch-size", type=int, choices=(1,2,4), default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-queued", type=int, default=DEFAULT_MAX_QUEUED)
    parser.add_argument("--queue-timeout", type=float, default=DEFAULT_QUEUE_TIMEOUT_SECONDS)
    parser.add_argument("--model", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--rounds", type=int, nargs="+", default=[1,2])
    parser.add_argument("--idle", type=float, default=5)
    parser.add_argument("--sample", type=Path, help="Directory containing speech.mp3 and transcript.txt")
    parser.add_argument("--reference", type=Path, help="Optional reference SRT for a custom sample")
    args = parser.parse_args()
    if any(n not in (1,2) for n in args.rounds):
        raise ValueError("Only one/two request rounds are supported")
    if args.idle <= 0:
        raise ValueError("Idle observation must be positive")
    root = Path(__file__).resolve().parent
    sample = args.sample.resolve() if args.sample else root / "output/sample-2026-10-14"
    output = sample / "optimizations" / args.name
    output.mkdir(parents=True, exist_ok=False)
    transcript = " ".join((sample / "transcript.txt").read_text().split())
    reference_path = args.reference or (None if args.sample else sample / "words.lightweight.comparison.srt")
    reference = read_cues(reference_path) if reference_path else None
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(sample / "speech.mp3"),
    ], text=True))
    state_lock = threading.Lock()
    phase, requests, events = "imports", {}, []
    service = None

    def snapshot():
        with state_lock:
            state = {"phase":phase, "requests":json.dumps(requests, sort_keys=True)}
        if service:
            model = service.aligner.model
            queued = model.num_queued_batches
            state.update(queued_batches=queued, active_batches=max(0,model.num_active_batches-queued))
            state.update(service.queue.snapshot())
        else:
            state.update(queued_batches=0, active_batches=0, active_requests=0, queued_requests=0)
        return state

    def event(request_id, stage):
        with state_lock:
            requests[str(request_id)] = stage
            events.append({"seconds":time.perf_counter()-STARTED,"request":request_id,"stage":stage})

    monitor = MemoryTimeline(STARTED, snapshot)
    monitor.start()
    reports = []
    try:
        from alignment_service import AlignmentService
        import_finished = time.perf_counter()-STARTED
        phase = "model_load"
        load_started = time.perf_counter()
        service = AlignmentService(args.model, workers=args.workers,
                                   intra_threads=args.threads, window_length=args.window,
                                   streaming=args.streaming, batch_size=args.batch_size,
                                   max_queued=args.max_queued, queue_timeout=args.queue_timeout)
        model_load = time.perf_counter()-load_started
        phase = "ready_idle"
        time.sleep(1)
        for round_index, count in enumerate(args.rounds, 1):
            phase = f"round_{round_index}_requests_{count}"
            barrier = threading.Barrier(count+1)

            def request(index):
                barrier.wait()
                begin = time.perf_counter()
                request_id = f"{round_index}.{index}"
                stages = {}

                def on_phase(stage):
                    stages[stage] = time.perf_counter()
                    event(request_id, stage)

                result = service.align(str(sample / "speech.mp3"), transcript, "eng",
                                       on_phase)
                path = output / f"words.{round_index}.{index}.srt"
                with path.open("x") as file:
                    file.write(result["srt"])
                elapsed = time.perf_counter()-begin
                actual = read_cues(path)
                assert [word for word,_,_ in actual] == transcript.split()
                assert all(0 <= start < end <= round(duration*1000) for _,start,end in actual)
                assert all(a[2] <= b[1] for a,b in zip(actual, actual[1:]))
                comparison = compare(actual,reference) if reference else None
                return {"request":index,"seconds":elapsed,"srt":path.name,"comparison":comparison,
                        "queue_wait_seconds":stages["started"]-stages["queue_wait"],
                        "processing_seconds":begin+elapsed-stages["started"],
                        "words":len(actual),"srt_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}

            with ThreadPoolExecutor(max_workers=count) as executor:
                futures = [executor.submit(request,index) for index in range(1,count+1)]
                begin = time.perf_counter()-STARTED
                cpu_begin = time.process_time()
                barrier.wait()
                results = [future.result() for future in futures]
                cpu_seconds = time.process_time()-cpu_begin
                end = time.perf_counter()-STARTED
            phase = f"round_{round_index}_idle"
            time.sleep(args.idle)
            idle_end = time.perf_counter()-STARTED
            entry = {"round":round_index,"requests":count,"start_seconds":begin,"end_seconds":end,
                     "process_cpu_seconds":cpu_seconds,"average_cpu_cores_used":cpu_seconds/(end-begin),
                     "processing_seconds":end-begin,"memory_during_processing":monitor.summarize(begin,end),
                     "memory_during_idle":monitor.summarize(end,idle_end),"results":results}
            entry["all_srt_files_identical"] = len({r["srt_sha256"] for r in results}) == 1
            reports.append(entry)
            print(json.dumps({"name":args.name,"round":round_index,"requests":count,
                              "seconds":round(end-begin,3),**entry["memory_during_processing"],
                              "idle_rss_gib":entry["memory_during_idle"]["last_rss_gib"]}), flush=True)
    finally:
        monitor.finish()
        with (output / "memory.csv").open("x") as file:
            writer = csv.DictWriter(file,fieldnames=list(monitor.rows[0]))
            writer.writeheader();writer.writerows(monitor.rows)
        with (output / "events.json").open("x") as file:
            json.dump(events,file,indent=2)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = {"name":args.name,"window_seconds":args.window,"context_each_side_seconds":2,
              "audio_duration_seconds":duration,"transcript_words":len(transcript.split()),
              "transcript_characters":len(transcript),"audio_path":str(sample / "speech.mp3"),
              "audio_sha256":hashlib.sha256((sample / "speech.mp3").read_bytes()).hexdigest(),
              "platform":platform.platform(),"machine":platform.machine(),
              "compute_type":service.aligner.model.compute_type,
              "intra_threads":args.threads,"workers":args.workers,"streaming":args.streaming,
              "batch_size":args.batch_size,"max_queued":args.max_queued,"queue_timeout_seconds":args.queue_timeout,
              "timing_note":"Round processing_seconds is wall time until all callers finish, including their queue waits. Per-request processing_seconds excludes queue wait. CPU seconds include alignment-process threads, excluding FFmpeg child processes.",
              "imports_seconds":import_finished,"model_load_seconds":model_load,
              "os_peak_process_gib":rss/(1024**3 if sys.platform=="darwin" else 1024**2),
              "maximum_observed_running_batches":max(r["active_batches"] for r in monitor.rows),
              "maximum_observed_queued_requests":max(r["queued_requests"] for r in monitor.rows),
              "heavy_imports":[m for m in ("torch","transformers") if m in sys.modules],
              "memory_sampling_seconds":.05,"idle_seconds_after_each_round":args.idle,"rounds":reports}
    assert not report["heavy_imports"]
    with (output / "report.json").open("x") as file:
        json.dump(report,file,indent=2)


if __name__ == "__main__":
    main()
