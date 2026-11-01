# Experimental self-hosted Korean counseling transcription

This source-only candidate is based on main `c15249e`. It is not deployed and is
not a blocker for the voucher PoC. The existing transcript editor is retained;
the previous extractive-summary experiments and new person-dictionary UI/backend/DB
are excluded. See [KoreaIDC handoff](stt-koreaidc-handoff.md) for the current-main
privacy gap, evidence boundaries, and operational acceptance criteria.


The default real engine is now `faster-whisper` large-v3 with Korean fixed,
Silero VAD, independently decoded VAD clips, beam 1, word timestamps, and
independent CAM++ speaker embeddings. CUDA defaults to batch 4; CPU uses batch 1.
VAD clips are passed explicitly to `BatchedInferencePipeline`, which keeps each
utterance's features separate and decodes it once. Concatenating quiet and loud
utterances caused omissions; sequential utterance decoding added spurious outros
in the synthetic comparison. A larger beam or silence-hallucination threshold
did not solve those failures. Clip decoding did. This is a provisional
choice for counselor review, not a claim of clinical readiness. SenseVoiceSmall
with FSMN-VAD remains an evaluated alternative. WhisperX is available only as an
explicit regression baseline (`AUDIO_TRANSCRIPTION_ENGINE=whisperx`).

## Runtime boundary

```text
Browser upload -> self-hosted FastAPI /api/audio/transcribe
  -> temporary upload -> FFmpeg mono/16k PCM -> bounded VAD/ASR chunks
  -> independent CAM++ diarization -> timestamp-based assignment
  -> anonymous editable turns -> counselor correction
  -> self-hosted /api/audio/deidentify -> counselor confirms masking
  -> explicit apply to session input -> CURRENT MAIN model-backed preview/re-masking
  -> Re summary (provider boundary; see the handoff before enabling real data)
```

Run `app.audio_main:app` for an audio-only service. `app.main:app` still supports
the combined development backend. Vercel does not run the models or proxy long
audio requests. Build the frontend with `VITE_AUDIO_API_BASE_URL` pointing to the
self-hosted origin; it otherwise falls back to the existing API origin. The same
verified bearer authentication applies to the audio endpoints. Authentication may
contact the existing identity service; it sends the token, not audio or transcript.
The audio-only app exposes no summary or external-LLM route.

## Install in an isolated environment

Python 3.11/3.12 and an FFmpeg executable on PATH are required. Do not alter the shared
GPU server environment. `uv pip install -r pyproject.toml` reads requirements
without trying to package this repository's multiple top-level development folders.

```bash
cd backend
uv venv .venv-audio --python 3.11
uv pip install --python .venv-audio/bin/python -r pyproject.toml --extra audio-local --extra audio-evaluation
# For the legacy comparison only:
uv pip install --python .venv-audio/bin/python -r pyproject.toml --extra audio-whisperx
```

On Windows use `.venv-audio/Scripts/python.exe`. Install the matching official
PyTorch CUDA wheels for the GPU server's driver before validation. The evaluated
workstation used PyTorch 2.8.0 CPU, CTranslate2 4.8.4, faster-whisper 1.2.1,
FunASR 1.3.0, transformers 4.57.6 and WhisperX 3.8.6. A separate A100 80GB job
validated Python 3.12 and PyTorch 2.8.0+cu126 without modifying shared packages.
The selected clip pipeline processed the 43m22s repeated synthetic fixture in
223.88 seconds (RTF 0.086), with 4,594 MiB peak process GPU memory sampled every
0.5 seconds. These are measured fixture results, not throughput guarantees.
`AUDIO_COMPUTE_TYPE` applies to Whisper's CTranslate2 ASR. SenseVoice and CAM++
use FunASR's float32 default on CPU and CUDA; the GPU benchmark does not silently
cast those weights to half precision.

Download and verify models before accepting uploads. Pin model revisions and
retain their license notices. Set `AUDIO_MODEL`, `AUDIO_CAMPPLUS_MODEL` and (for
SenseVoice) `AUDIO_FSMN_MODEL` to immutable local directories. `HF_HUB_OFFLINE=1`
and `TRANSFORMERS_OFFLINE=1` permit subsequent offline inference. On Windows,
Hugging Face downloads can use `local_dir` and `max_workers=1` without changing
Windows symlink privileges.

Copy `backend/audio-runtime.env.example` to an operator-owned configuration file,
set the actual device and exact frontend origin, and provision `UPLOAD_TMP_DIR`
with service-account-only permissions. Use the existing verified-user auth
configuration; never enable a local authentication bypass on a network-facing
service. Do not include LLM credentials in this dedicated runtime.

```bash
# An operator action after local validation; no deployment is performed by this change.
.venv-audio/bin/python -m uvicorn app.audio_main:app --host 127.0.0.1 --port 8011 --workers 1 --env-file /path/to/audio-runtime.env
```

Use an authenticated HTTPS reverse proxy for remote operation, with upload and
read timeouts appropriate to measured processing time. There is one in-process
audio job slot and no durable queue, polling endpoint, or resume after process
restart. Multiple Uvicorn workers would each have their own model and slot. The
browser uses a two-hour request timeout; proxy limits are an operator obligation.
`/capabilities` checks packages/configuration, not model readiness or GPU memory.

## Stage contract and failure handling

The response retains `raw_segments`, `vad_segments`, `diarization_segments`,
merged `segments`, `failed_ranges`, `error_codes`, and `stage_metrics` in memory.
`review_ranges` identifies VAD speech with at least 1.5 seconds lacking matching
word timing. These are clickable listen-back candidates, not fabricated missing
text; inaccurate timestamps and shorter omissions can escape this heuristic.
Each editable turn has `segment_id`, `start`, `end`, `speaker`, `text`, optional
confidence and `review_flags`. `start`/`end` are seconds from the original audio.
Merge/split operations retain source segment IDs and original source ranges.
`speaker_0` and `speaker_1` are acoustic labels, never inferred clinical roles.

The default core is 120 seconds with five seconds of context on each side; only
core-owned words are retained. SenseVoice without word timing uses segment
ownership and marks coarse/mixed-speaker intervals for review. CAM++ fits at most
2,048 stable embedding windows, then assigns remaining windows to centroids.
Short backchannels do not create training clusters. This clustering does not
separate simultaneous voices; overlap remains a review case.

Partial ASR failure returns retained text, failed time ranges and `status: partial`.
OOM stops later cores and marks them unprocessed. Total ASR failure returns 500;
no speech or duration excess returns 422; a busy slot returns 429. A diarization
failure retains ASR with unknown speakers and a Korean review warning. Low
confidence/sensitive expressions produce review flags; they never trigger LLM
text repair. Implausible text density is marked `timestamp_anomaly`, not deleted
using a phrase blacklist. Normalization changes whitespace only. Fillers are retained.

## Data lifecycle

| Data | Location | Removal / retention |
|---|---|---|
| Raw upload | `UPLOAD_TMP_DIR/remind_audio_*` or OS temporary directory | Route `finally`; upload helper also cleans failed/cancelled validation |
| Decoded PCM | `UPLOAD_TMP_DIR/remind_pcm_*/decoded.wav` or OS temporary directory | `TemporaryDirectory` on successful and exceptional service exit |
| Raw/merged stage text | Server request memory, then browser material state | No server transcript file; browser release on remove/unmount |
| Original browser File / object URL | Browser memory | Remove/unmount revokes object URL; retained during editing for playback |
| Confirmed masked transcript | Session form | Existing draft/session storage policy; may persist when saved |
| Synthetic benchmark audio/results | Explicit evaluator output directory | Intentionally retained for reproducibility; never real-client fixtures |

Ordinary success/failure/cancellation cleanup is tested. Process kill, power loss,
filesystem locks and deletion failure are not equivalent to successful cleanup.
The existing unlink helper suppresses filesystem errors. A production operator
must use an ephemeral private volume and a stale-file policy, and must verify
that shutdown/backup/logging policies do not retain raw data. Audio and raw ASR
are not included in the temporary-draft attachment whitelist. PII detection is
heuristic; the counselor must correct missed names/institutions before confirmation.
Manually typed/document inputs retain their pre-existing workflow.

## Reproduce the evaluation

```bash
python benchmarks/stt_synthetic.py --output /private/synthetic-stt --long-minutes 40
python benchmarks/stt_benchmark.py --audio /private/synthetic-stt/roleplay.wav --reference /private/synthetic-stt/reference.json --output /private/results/faster-beam1 --engine faster-whisper --beam 1
python benchmarks/stt_benchmark.py --audio /private/synthetic-stt/roleplay.wav --reference /private/synthetic-stt/reference.json --output /private/results/faster-beam5 --engine faster-whisper --beam 5
python benchmarks/stt_benchmark.py --audio /private/synthetic-stt/roleplay.wav --reference /private/synthetic-stt/reference.json --output /private/results/sensevoice --engine sensevoice --model /models/SenseVoiceSmall
python benchmarks/stt_benchmark.py --audio /private/synthetic-stt/roleplay.wav --reference /private/synthetic-stt/reference.json --output /private/results/whisperx --engine whisperx --batch 4
python benchmarks/stt_benchmark.py --audio /private/synthetic-stt/stress.wav --reference /private/synthetic-stt/stress-reference.json --output /private/results/stress --engine faster-whisper --beam 1
python benchmarks/stt_audit.py --reference /private/synthetic-stt/stress-reference.json --short-reference /private/synthetic-stt/reference.json --transcription /private/results/stress/transcription.json --output /private/results/stress/long-audio-audit.json
```

The commands above retain the original concatenated-audio comparison defaults
(`--context 2 --whisper-vad-mode concatenate`, no hallucination silence filter).
To reproduce the selected GPU configuration, use both short and long fixtures:

```bash
python benchmarks/stt_benchmark.py --audio /private/synthetic-stt/roleplay.wav --reference /private/synthetic-stt/reference.json --output /private/results/selected-short --engine faster-whisper --device cuda --model /models/faster-whisper-large-v3 --beam 1 --batch 4 --context 5 --whisper-vad-mode clips
python benchmarks/stt_benchmark.py --audio /private/synthetic-stt/stress.wav --reference /private/synthetic-stt/stress-reference.json --output /private/results/selected-long --engine faster-whisper --device cuda --model /models/faster-whisper-large-v3 --beam 1 --batch 4 --context 5 --whisper-vad-mode clips
```

Diagnostic variants use `--context 5` alone, or
`--context 5 --whisper-vad-mode segments --batch 1`, optionally adding
`--hallucination-silence 0.5`. Neither diagnostic variant was selected. Independent
sequential decoding and SenseVoice require batch 1. Batched clip decoding supports
configurable batches, but the library does not implement its silence-hallucination
filter in that mode, so incompatible settings are rejected rather than ignored.

The generator sends only the fixed fictional script to Edge TTS, caches its voice
clips and writes a separately hashed reference. It has no real-data input option.
STT inference is local. The long file repeats the short sample and tests duration,
memory and drift; it is not an independent natural-conversation quality set.

The evaluator reports strict Korean CER and a separately disclosed ITN-equivalent
CER, speaker errors after label permutation, turn boundaries, protected phrases,
whole-turn coverage, partial lexical omissions, unexpected lexical insertion runs,
repetitions and silence output. Insertion runs are candidates relative to the script,
not a substitute for listening to the source audio.
Its frame DER uses TTS turn envelopes, including internal pauses, so miss/false
alarm figures are provisional. Character edits and boundary/speaker operations
are editing-burden proxies. A separate display-text edit count includes spacing
and punctuation so a low CER cannot hide a difficult-to-edit rendering. Script
punctuation is a reference style, not the only acceptable transcript. Actual counselor editing minutes and acceptability
remain unmeasured until a consented roleplay usability study.

The previous A100 job runner is preserved in the original evidence bundle, not
this source-only candidate. It depends on the separately maintained `gpu.ps1`
workflow and installs a private CUDA 12.6 environment; it is not a Blackwell
installation recipe. Do not copy it to the 24 GB host unchanged. The commands above
are explicit evaluator commands, not production deployment commands. Synthetic
generation calls Edge TTS; offline reevaluation must reuse the exact retained WAV.
The separate `benchmarks/counseling_long_synthetic.py` builds the non-looped 46-minute
fixture; newly synthesized voices may differ, so verify the retained WAV SHA256.

SenseVoice uses built-in ITN/punctuation. FunASR's separate CT-punctuation model
advertises Chinese/English and is not applied to Korean. SenseVoice weights have
the linked FunASR model license; do not describe them as Apache solely because a
runtime package has a permissive license. CAM++/FSMN cards and all selected model
revisions must be reviewed before operational distribution.
