"""Export the long-audio benchmark, word comparison and RAM timeline."""

import argparse
import csv
import json
from pathlib import Path
import subprocess

from benchmark_lightweight import read_cues
from benchmark_cupe import compare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Completed benchmark output directory")
    args = parser.parse_args()
    folder = args.folder.resolve()
    report = json.loads((folder / "report.json").read_text())
    run = report["rounds"][0]
    results = run["results"]
    assert len(results) == 2
    cues = [read_cues(folder / result["srt"]) for result in results]
    hardware = json.loads(subprocess.check_output([
        "node", "-e", 'const os=require("node:os");console.log(JSON.stringify({cpu:os.cpus()[0]?.model,logical_cpus:os.cpus().length,total_memory_bytes:os.totalmem()}))',
    ], text=True))
    summary = {
        "hardware": hardware,
        "audio_duration_seconds": report["audio_duration_seconds"],
        "words_per_request": report["transcript_words"],
        "request_seconds": [r["seconds"] for r in results],
        "both_requests_finished_seconds": run["processing_seconds"],
        "aggregate_audio_seconds_per_processing_second": 2 * report["audio_duration_seconds"] / run["processing_seconds"],
        "imports_seconds": report["imports_seconds"],
        "model_load_seconds": report["model_load_seconds"],
        "os_peak_process_gib": report["os_peak_process_gib"],
        "processing_memory": run["memory_during_processing"],
        "idle_memory": run["memory_during_idle"],
        "idle_observation_seconds": report["idle_seconds_after_each_round"],
        "concurrent_inference_batches_observed": report["maximum_observed_running_batches"],
        "srt_byte_identical": run["all_srt_files_identical"],
        "word_timing_comparison_between_requests": compare(cues[0], cues[1]),
        "method": "Two concurrent calls to one persistent AlignmentService in one fresh process, shared cached int8_float32 model, two workers, four threads per worker, ten-second windows with two-second context on each side, streaming decode, batch size one. Processing excludes synthesis, imports, model loading and downloads. RAM is combined alignment-process RSS, excluding separate FFmpeg child processes and other apps. This is one local run; word agreement is not human-annotated accuracy.",
    }
    events = json.loads((folder / "events.json").read_text())
    summary["request_phase_seconds"] = {}
    for result in results:
        relevant = [event for event in events if event["request"] == f'1.{result["request"]}']
        summary["request_phase_seconds"][str(result["request"])] = {
            a["stage"]: b["seconds"] - a["seconds"] for a,b in zip(relevant, relevant[1:])
        }
    with (folder / "summary.json").open("x") as output:
        json.dump(summary, output, indent=2)
    with (folder / "summary.csv").open("x") as output:
        writer = csv.writer(output)
        writer.writerow(["metric", "value", "unit"])
        for result in results:
            writer.writerow([f'request_{result["request"]}', result["seconds"], "seconds"])
        writer.writerow(["both_requests_complete", run["processing_seconds"], "seconds"])
        writer.writerow(["os_peak_combined_process", report["os_peak_process_gib"], "GiB"])
        writer.writerow(["average_combined_process", run["memory_during_processing"]["mean_rss_gib"], "GiB"])
        writer.writerow(["idle_after_ten_seconds", run["memory_during_idle"]["last_rss_gib"], "GiB"])
        writer.writerow(["identical_word_timings", summary["srt_byte_identical"], "boolean"])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with (folder / "memory.csv").open() as source:
        samples = list(csv.DictReader(source))
    begin, end = run["start_seconds"], run["end_seconds"]
    selected = [row for row in samples if float(row["seconds"]) >= begin]
    fig, ax = plt.subplots(figsize=(10, 4.8), layout="constrained", facecolor="white")
    ax.plot([float(row["seconds"]) - begin for row in selected],
            [int(row["rss_bytes"]) / 1024**3 for row in selected], color="#2563eb", linewidth=1.5)
    ax.axvline(end - begin, color="#475569", linestyle="--", label="Both requests complete")
    ax.axvspan(end - begin, float(selected[-1]["seconds"]) - begin, color="#e2e8f0", alpha=.7, label="Model remains loaded")
    ax.set(title="Two simultaneous requests for the same ten-minute audio",
           xlabel="Seconds since requests started", ylabel="Combined alignment-process RAM (GiB)", ylim=(0, None))
    ax.grid(alpha=.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    fig.savefig(folder / "memory-timeline.png", dpi=160)
    fig.savefig(folder / "memory-timeline.svg")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
