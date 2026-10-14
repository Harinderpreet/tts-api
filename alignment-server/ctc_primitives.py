"""Load upstream text/native helpers without its heavyweight package initializer.

fast-forced-aligner 0.3.0 imports torch and transformers in __init__. Its text
normalization and compiled CTC implementation do not need either library.
Keep this compatibility boundary isolated; no installed package is modified.
"""

import importlib
import importlib.metadata
import sys
import types
from functools import lru_cache


@lru_cache(maxsize=1)
def load_primitives():
    distribution = importlib.metadata.distribution("fast-forced-aligner")
    if distribution.version != "0.3.0":
        raise RuntimeError("The lightweight adapter supports fast-forced-aligner 0.3.0; review compatibility before upgrading.")
    directory = distribution.locate_file("ctc_forced_aligner")
    namespace = "_alignment_ctc_primitives"
    if namespace not in sys.modules:
        package = types.ModuleType(namespace)
        package.__path__ = [str(directory)]
        package.__package__ = namespace
        sys.modules[namespace] = package
    text = importlib.import_module(f"{namespace}.text_utils")
    native = importlib.import_module(f"{namespace}.ctc_forced_aligner")
    return text, native.forced_align
