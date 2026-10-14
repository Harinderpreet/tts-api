"""Build a comparison table and memory timeline figure from completed profiles."""

import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot-profiles", nargs="+", required=True)
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent / "output/sample-2026-10-14/optimizations"
    rows, reports = [], {}
    for path in sorted(folder.glob("*/report.json")):
        report = json.loads(path.read_text())
        reports[report["name"]] = report
        for run in report["rounds"]:
            rows.append({"profile":report["name"],"round":run["round"],"requests":run["requests"],
                         "window_seconds":report["window_seconds"],"threads":report["intra_threads"],
                         "processing_seconds":run["processing_seconds"],
                         "sampled_peak_gib":run["memory_during_processing"]["sampled_peak_rss_gib"],
                         "mean_gib":run["memory_during_processing"]["mean_rss_gib"],
                         "idle_gib":run["memory_during_idle"]["last_rss_gib"],
                         "seconds_near_peak":run["memory_during_processing"]["approx_seconds_above_90_percent_of_peak"],
                         "changed_words":max(r["comparison"]["changed_words"] for r in run["results"]),
                         "mean_boundary_difference_ms":max(r["comparison"]["mean_boundary_difference_ms"] for r in run["results"]),
                         "max_boundary_difference_ms":max(r["comparison"]["max_boundary_difference_ms"] for r in run["results"])})
    with (folder/"summary.csv").open("w") as file:
        writer = csv.DictWriter(file,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    with (folder/"summary.json").open("w") as file:
        json.dump({"method":"Same 118.152s English audio, 305 words, shared int8 model, 50ms current RSS samples, fresh process per profile, imports/downloads excluded from processing time.",
                   "results":rows,"profiles":reports},file,indent=2)
    print(json.dumps(rows,indent=2))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(1,2,figsize=(13,4.8),facecolor="white",layout="constrained")
    colors = ["#475569","#2563eb","#059669","#d97706"]
    for profile,color in zip(args.plot_profiles,colors):
        report = reports[profile]
        label = f"{'Streaming' if report['streaming'] else 'Original'}, {report['window_seconds']} seconds"
        with (folder/profile/"memory.csv").open() as file:
            samples = list(csv.DictReader(file))
        for ax,request_count in zip(axes,(1,2)):
            run = next(r for r in report["rounds"] if r["requests"] == request_count)
            begin,end = run["start_seconds"],run["end_seconds"]
            selected = [r for r in samples if begin <= float(r["seconds"]) <= end+report["idle_seconds_after_each_round"]]
            ax.plot([float(r["seconds"])-begin for r in selected],
                    [int(r["rss_bytes"])/1024**3 for r in selected],color=color,linewidth=1.4,label=label)
            ax.axvline(end-begin,color=color,linestyle=":",alpha=.7)
    for ax,title in zip(axes,("One request", "Two concurrent requests — combined RAM")):
        ax.set(title=title,xlabel="Seconds since requests started",ylabel="Resident RAM (GiB)")
        ax.set_ylim(bottom=0)
        ax.grid(alpha=.17)
        ax.spines[["top","right"]].set_visible(False)
        ax.legend(frameon=False,fontsize=8)
    fig.suptitle("Memory during alignment and five seconds afterward\nDotted lines mark completion; the model stays loaded",fontsize=13)
    fig.savefig(folder/"memory-comparison.png",dpi=160)
    fig.savefig(folder/"memory-comparison.svg")


if __name__ == "__main__":
    main()
