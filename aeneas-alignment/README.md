# Aeneas word-level SRT

Adapted from [John Meade's word-alignment gist](https://gist.github.com/johnmeade/80e411d6a9482c6b1ed4836820d85306).
It splits the supplied transcript into words, aligns them locally with Aeneas,
reads the TextGrid Token tier, and writes one SRT cue per word. No service is
started, no transcription is performed, and existing results are preserved.

The gist's nonspeech masking options are passed through Aeneas's documented
`RuntimeConfiguration` rather than the task-format configuration. Temporary
input and TextGrid files are cleaned up after alignment.

The task also enables Aeneas's documented `task_adjust_boundary_no_zero=True`:
the unadjusted run gave nine words zero duration, and the gist's TextGrid reader
silently omitted them. Aeneas adjusts these boundaries before export so the
result retains all transcript words. Adjusted boundaries are estimates.

Built-in pause handling is now enabled with
`task_adjust_boundary_nonspeech_min=1.000` and
`task_adjust_boundary_nonspeech_string=REMOVE`. Detected nonspeech intervals of
at least one second at word boundaries become caption-free gaps. Shorter pauses
keep the previous behavior. Audio is unchanged. This uses Aeneas's existing
speech detection, rather than an additional detector or fixed word-duration cap.
The TextGrid reader ignores the empty intervals between words, and SRT
serialization preserves the resulting gaps.

The one-second minimum is shared through `MINIMUM_PAUSE_SECONDS` in
`align_words.py`; new CLI and batch reports record this setting. Results already
saved in the original ten-minute and multilingual runs below were generated
before pause handling was enabled.

With the user's permission, the one-second setting passed these local checks:

- A controlled 0.5-second pause retained continuous word cues.
- A controlled 1.5-second pause produced a 1.48-second caption-free gap; detected
  boundaries have Aeneas's frame resolution and need not match injected silence
  endpoints exactly. Every word was preserved, with no zero-duration cues.
- The existing mixed English/Hindi audio retained all 439 cues, identical to the
  previous English alignment, in 1.622 seconds. It had no qualifying detected
  long pause. Results: `output/mixed-english-hindi-2026-10-15/english-pause-1s/`.

The reproducible controlled check is `check_pause_handling.py`; it synthesizes
speech locally with the installed eSpeak and needs no external service. Run it
only when test execution is authorized. Supply a fresh `--output-dir` on reruns;
existing results are never overwritten. The completed fixture and report are in
`output/pause-1s-check/`.

## Installation (run yourself)

From the repository root, use a separate Python 3.11 environment. The existing
alignment environment uses NumPy 2, whereas this older Aeneas build needs NumPy
1.x and its build tools. These commands keep the existing environment intact.
FFmpeg, FFprobe, and eSpeak are already present on this Mac.

```sh
forced-alignment/.venv/bin/python -m venv aeneas-alignment/.venv
aeneas-alignment/.venv/bin/python -m pip install 'numpy==1.26.4' 'setuptools<70' wheel
env CFLAGS='-I/opt/homebrew/include' LDFLAGS='-L/opt/homebrew/lib' \
  aeneas-alignment/.venv/bin/python -m pip install --no-build-isolation -r aeneas-alignment/requirements.txt
```

The compiler paths above match this Mac's existing Homebrew eSpeak installation.
Installation on other systems may require different compiler paths and system
dependencies; see the [Aeneas installation guide](https://github.com/readbeyond/aeneas/blob/master/wiki/INSTALL.md).

## Run on the existing ten-minute audio

```sh
aeneas-alignment/.venv/bin/python aeneas-alignment/generate_srt.py \
  forced-alignment/output/ten-minute-2026-10-14/speech.mp3 \
  --transcript-file forced-alignment/output/ten-minute-2026-10-14/transcript.txt \
  --language eng \
  --output-dir aeneas-alignment/output/ten-minute
```

The audio is 600 seconds with a matching 1,554-word English transcript. Results:

- `words.srt`: one original transcript word per cue, retaining punctuation.
- `words.json`: aligned word boundaries for further inspection.
- `report.json`: elapsed alignment time, cue count, boundary checks, and paths.

Choose a new output directory when rerunning. Word sequence and timing ordering
are checked during generation. Any zero-duration cues remaining after Aeneas's
boundary adjustment are counted and reported without further modification.

As the gist and [Aeneas documentation](https://pypi.org/project/aeneas/) explain,
this TTS/DTW approach is approximate at word level. Structural checks do not
establish perceptual accuracy. Listen against the SRT before relying on exact
word boundaries.

## Completed run: 15 October 2026

Executed locally using the isolated environment after the user authorized
package installation. No service was started and no unit tests were run.

| Measurement | Result |
| --- | --- |
| Audio duration | 600.000 seconds |
| Transcript words / SRT cues | 1,554 / 1,554 |
| Alignment and TextGrid extraction time | 3.776 seconds |
| Processing speed | 158.897 audio seconds per processing second |
| Zero-duration cues | 0 |
| Word sequence | Exact transcript match |
| Timing bounds / overlap | Valid bounds, no overlap |
| Manual listening review | Not performed |

Files are in `output/ten-minute/`: `words.srt`, `words.json`, and `report.json`.
Elapsed time covers dependency imports, alignment, and TextGrid extraction;
it excludes installation, audio probing, and writing the final result files.

## Multilingual speech and subtitle batch

`run_multilingual.py` accepts a JSON object containing `en`, `hi`, `es`, `fr`,
`de`, and/or `it` passages. It preserves the supplied text, generates speech
using the existing Speechma Microsoft provider, and runs the same Aeneas word
alignment. Each language has its own folder containing `speech.mp3`,
`transcript.txt`, `words.srt`, `words.json`, `generation.json`, and `report.json`.
A combined `summary.json` is written at the batch root.

```sh
aeneas-alignment/.venv/bin/python aeneas-alignment/run_multilingual.py \
  /Users/harinderpreetsingh/Downloads/multilingual_3000_char_passages.json \
  --output-dir aeneas-alignment/output/multilingual-2026-10-15
```

Choose a new destination when repeating the run. The runner calls
`generate_audio.mjs`, which imports the existing SSML builder and speech adapter
directly. No service is started, no API key is printed, and no packages are
installed. Speech generation sends the text to Microsoft; alignment is local.
The Node executable must support native TypeScript stripping (the installed
Node 22.23.1 does).

All six voice IDs were checked against the
[official Microsoft voice catalogue](https://learn.microsoft.com/azure/ai-services/speech-service/language-support?tabs=tts).
Full MP3 decoding, transcript-word preservation, and subtitle timing bounds are
checked as part of generation. These checks do not establish perceived speech
quality or subtitle synchronization; those need listening review.

### Completed multilingual run: 15 October 2026

All six passages completed in 44.395 seconds, including speech generation,
full audio decoding, alignment, and saving files. The total generated audio is
1,190.976 seconds (19 minutes 51 seconds), containing 2,906 word cues.

| Language | Audio seconds | Word cues | Aeneas seconds |
| --- | --- | --- | --- |
| English | 191.184 | 506 | 1.174 |
| Hindi | 261.720 | 624 | 1.140 |
| Spanish | 185.712 | 467 | 1.327 |
| French | 170.784 | 449 | 0.849 |
| German | 202.608 | 409 | 0.922 |
| Italian | 178.968 | 451 | 0.921 |

All word sequences match their original passages. Every MP3 decoded fully,
all timing bounds were valid, and no overlapping or zero-duration cues remained.
Aeneas boundary adjustment is enabled as above; these are structurally checked
results, without a manual listening review. Results are under
`output/multilingual-2026-10-15/`, grouped into `en/`, `hi/`, `es/`, `fr/`,
`de/`, and `it/`.
