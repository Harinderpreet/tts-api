"""50 ms current-RSS sampling; separate from the OS lifetime high-water mark."""

import ctypes
import os
import sys
import threading
import time
from pathlib import Path


if sys.platform == "darwin":
    # Layout/constants from the macOS SDK sys/proc_info.h, PROC_PIDTASKINFO.
    class TaskInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("virtual", "resident", "user", "system", "thread_user", "thread_system")]
        _fields_ += [(f"counter{i}", ctypes.c_int32) for i in range(12)]

    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    libproc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                    ctypes.c_void_p, ctypes.c_int]
    libproc.proc_pidinfo.restype = ctypes.c_int


def current_rss():
    if sys.platform == "darwin":
        info = TaskInfo()
        size = libproc.proc_pidinfo(os.getpid(), 4, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size != ctypes.sizeof(info):
            raise OSError(ctypes.get_errno(), "Unable to read process resident memory")
        return info.resident
    if sys.platform.startswith("linux"):
        return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    raise RuntimeError("RSS sampling currently supports macOS and Linux")


class MemoryTimeline:
    def __init__(self, started, state):
        self.started, self.state = started, state
        self.rows = []
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def sample(self):
        self.rows.append({"seconds": time.perf_counter()-self.started,
                          "rss_bytes": current_rss(), **self.state()})

    def run(self):
        try:
            while not self.stop.is_set():
                self.sample()
                self.stop.wait(.05)
        except Exception as error:
            self.error = error

    def start(self):
        current_rss()  # Fail before beginning the benchmark if unavailable.
        self.thread.start()

    def finish(self):
        self.stop.set()
        self.thread.join()
        if self.error:
            raise self.error
        self.sample()

    def summarize(self, start, end):
        rows = [r for r in self.rows if start <= r["seconds"] <= end]
        if not rows:
            raise RuntimeError("No memory samples in measurement interval")
        peak = max(r["rss_bytes"] for r in rows)
        intervals = [(a, min(b["seconds"], end)-a["seconds"])
                     for a,b in zip(rows, rows[1:])]
        return {
            "sampled_peak_rss_gib": peak/1024**3,
            "mean_rss_gib": sum(a["rss_bytes"]*dt for a,dt in intervals)/sum(dt for _,dt in intervals)/1024**3 if intervals else peak/1024**3,
            "approx_seconds_above_90_percent_of_peak": sum(dt for a,dt in intervals if a["rss_bytes"] >= .9*peak),
            "approx_seconds_above_gib": {str(n): sum(dt for a,dt in intervals if a["rss_bytes"] >= n*1024**3) for n in (1,2,3,4,5)},
            "maximum_sample_gap_seconds": max((dt for _,dt in intervals), default=0),
            "last_rss_gib": rows[-1]["rss_bytes"]/1024**3,
        }
