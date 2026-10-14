"""Read word-level SRT and compare word boundaries for benchmarks."""

import math

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

