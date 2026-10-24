"""Word alignment adapted from John Meade's Aeneas gist.

Source: https://gist.github.com/johnmeade/80e411d6a9482c6b1ed4836820d85306
Retains its word-per-line input, Aeneas task and TextGrid Token extraction.
Uses managed temporary files and passes masking through RuntimeConfiguration.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NamedTuple


MINIMUM_PAUSE_SECONDS = 1.0


class ForceAlignedText(NamedTuple):
    text: str
    start_sec: float
    end_sec: float


def force_align(txt: str, audio_path: Path, lang: str) -> list[ForceAlignedText]:
    """Align the supplied words locally; this does not transcribe the audio."""
    from aeneas.executetask import ExecuteTask
    from aeneas.runtimeconfiguration import RuntimeConfiguration
    from aeneas.task import Task
    from textgrid import TextGrid

    words = txt.split()
    if not words:
        raise ValueError("The transcript contains no words.")

    with TemporaryDirectory(prefix="aeneas-words-") as temporary:
        text_path = Path(temporary, "words.txt")
        grid_path = Path(temporary, "words.TextGrid")
        text_path.write_text("\n".join(words), encoding="utf-8")

        # These are runtime options, rather than task-format options.
        runtime = RuntimeConfiguration(
            "mfcc_mask_nonspeech=True|mfcc_mask_nonspeech_l3=True"
        )
        task = Task(config_string=(
            f"task_language={lang}|is_text_type=plain|os_task_file_format=textgrid"
            # TextGrid readers discard zero-length words. Let Aeneas adjust
            # those boundaries before exporting, preserving every word.
            "|task_adjust_boundary_no_zero=True"
            # Leave detected pauses of at least one second without captions.
            # Shorter pauses retain Aeneas's existing word-boundary behavior.
            f"|task_adjust_boundary_nonspeech_min={MINIMUM_PAUSE_SECONDS:.3f}"
            "|task_adjust_boundary_nonspeech_string=REMOVE"
        ))
        task.audio_file_path_absolute = str(audio_path)
        task.text_file_path_absolute = str(text_path)
        task.sync_map_file_path_absolute = str(grid_path)
        ExecuteTask(task, rconf=runtime).execute()
        task.output_sync_map_file()

        grid = TextGrid.fromFile(str(grid_path))
        tier = next((tier for tier in grid.tiers if tier.name == "Token"), None)
        if tier is None:
            raise RuntimeError("Aeneas returned no Token tier in the TextGrid.")
        aligned = [
            ForceAlignedText(interval.mark, interval.minTime, interval.maxTime)
            for interval in tier.intervals if interval.mark.strip()
        ]
        if [word.text for word in aligned] != words:
            mismatch = next((
                index for index, (actual, expected) in enumerate(zip(aligned, words))
                if actual.text != expected
            ), min(len(aligned), len(words)))
            raise RuntimeError(
                f"Aligned words differ from the supplied transcript: expected {len(words)}, "
                f"got {len(aligned)}; first mismatch at {mismatch + 1}; "
                f"expected {words[mismatch:mismatch + 3]!r}, "
                f"got {[word.text for word in aligned[mismatch:mismatch + 3]]!r}."
            )
        return aligned
