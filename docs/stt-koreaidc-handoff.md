# Experimental STT handoff for KoreaIDC

## Decision and scope

Prepared 2026-11-01 against GitHub main `c15249e780f7f07d8523f8fc88195c9b5d28fdf5`.
This is a source-only local candidate, not a production deployment or a claim of
clinical readiness. STT is experimental and is not a prerequisite for the voucher
PoC. Existing counselor transcript editing is retained; no new person dictionary,
name/alias mapping UI, backend, or database work is included.

The provisional pipeline is Korean faster-whisper large-v3, independent Silero VAD
clips, beam 1, CUDA batch 4, word timestamps, and independent CAM++ diarization
with `expected_speakers=2`. WhisperX remains an explicit regression option;
SenseVoiceSmall/FSMN/CAM++ remains an evaluation alternative. The ASR and
diarization implementation is unchanged from the retained long-audio experiment.
Model outputs remain anonymous until the counselor assigns roles. No LLM repairs
ASR text. Partial failures, raw ASR, VAD, diarization and merged turns stay separate.

PR [#72](https://github.com/jordy9090/remind-counseling-note-agent/pull/72),
`Preserve concrete session memory cues and reviewable source evidence`, was a Draft
at inspection (head `f90dfb455c486e88cc7dc640e1811f142245c6ba`). This candidate does
not include its changes, merge it, or replace main's summary implementation.
`SessionDraftPage.tsx` is shared, so future integration must inspect those hunks.
Main's `handleSubmit`, `generateReviewed`, and person-review components are retained.
The inspected 24-file PR list overlaps this candidate only at that session page.

## November 2 publication and validation addendum

The preparation context above is historical. The original candidate `5fce276`
is published in [Draft PR #73](https://github.com/jordy9090/remind-counseling-note-agent/pull/73).
PR #72 has independently merged into main at `f49a35e`; it was not merged or rebased
into this STT branch. Read-only integration checks preserve its 23 other changed
files byte-for-byte and retain its separate evidence/summary hunks in the shared
session page. The STT candidate now contains 33 paths, as listed in
[source separation](stt-source-separation.md).

Dependency follow-up `2a7d3cc` regenerated `backend/uv.lock` for the declared audio
extras and added NumPy/RapidFuzz to the default development group. Base runtime
package versions were preserved. Optional dependency resolution, including
OmegaConf, changed; the new lock is **not** the measured A100 environment or a
qualified Blackwell installation. Fresh Python 3.11 locked installation and
41 focused synthetic backend tests passed without installing Torch, faster-whisper,
FunASR or WhisperX. On that exact head, backend-smoke, backend-pdf-export and
frontend-build passed in [Product CI](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/41321558779);
[security-regressions](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/41321558781)
also passed. Those checks did not run GPU inference.

The subsequent privacy-reapplication correction uses the stored previously applied
block to identify repeat application, even when only the masking textarea changed
and the ASR turns remain clean. It replaces that block without duplicating it or
discarding unrelated memo text. A missing, ambiguous or independently edited prior
block stops the entire update, including acoustic notes, with the existing review
message. New synthetic regressions execute the actual page callback and helpers;
they cover privacy-only correction, repeat application, both initial apply modes,
unrelated text preservation and conflict rejection. See PR #73 for the exact
follow-up commit and CI results; these checks are not a fresh browser/model E2E.

The final review verified all 13 retained evidence-index hashes, the long fixture's
speaker/text sequence and the STT source archive against the candidate. The ASR
implementation and historical measurements below are unchanged. The source archives
and earlier patch are frozen snapshots, not an alternative to checking out the
reviewed PR head. Automatic GitHub-linked Previews do not qualify the self-hosted
GPU service or authorize Production promotion.

Before enabling real data, the downstream outbound privacy boundary, actual
Blackwell kernels/concurrency, crash/deletion-failure recovery, current-main
browser/auth/persistence integration, and dense long-input summary limits still
require separate acceptance. This correction does not close those operational
gates or change the experimental/disabled Blackwell profile.

## Reused evidence, not a new experiment

The original experiment was based on `1879757694dced5530aca80db499323dc4300767`
plus explicitly archived working changes. The primary source is the retained
`outputs/` artifact directory from the STT task, not this branch's commit history.
No GPU, browser E2E, model request, account creation, or database write was repeated
for this handoff. Local extraction checks do not requalify a production end-to-end flow.

| A100 80 GB, same 8m40s fictional audio | CER | Matched-character speaker error | Turn F1 | Seconds | Sampled process VRAM MiB | Display-text edits |
|---|---:|---:|---:|---:|---:|---:|
| Selected large-v3 VAD clips, beam 1, batch 4 | 1.75% | 0.05% | 0.979 | 51.8 | 4,594 | 77 |
| large-v3 concatenated VAD, beam 5 | 3.35% | 0.88% | 0.917 | 112.3 | 3,986 | 122 |
| SenseVoice ITN + FSMN + CAM++ | 4.72% | 5.98% | 0.711 | 32.1 | 1,516 | 421 |
| WhisperX, alignment successful, diarization fallback | 12.65% | 46.12% | 0.190 | 26.2 | 6,562 | 394 |

WhisperX had no gated diarization token: its speaker result is a fallback-path
measurement, not a comparison against a successfully configured pyannote model.
The synthetic script is the reference, not an independent human transcription.
Large beams did not outperform the selected clip strategy on this sample. Do not
generalize the ranking to natural counseling or other microphones.

The later non-looped 46m12.899s fixture has 198 authored utterances and two synthetic
voices, with quiet speech, silence, short overlap and backchannels. Retained WAV
SHA256: `3bc6862934408ec82a6505fb412b9c050b7654f4ea7445c6fc50467a5433a35a`.
Only authored fictional text was sent to Edge TTS; no real client data was used.

| Long fixture measurement | Result |
|---|---|
| ASR + diarization elapsed | 364.889 s; RTF 0.13156; ASR 280.358 s; diarization 83.117 s |
| Process VRAM | 4,594 MiB sampled every 0.5 s; other users' processes excluded |
| Korean CER | 0.5139%; whitespace/punctuation removed; number spelling differences count |
| Speaker attribution | 0% on matched characters after label permutation |
| DER | 14.535%, including miss 11.729% and false alarm 2.807%; TTS envelopes include internal silence |
| Turn boundaries | F1 0.98715; 193 output turns versus 198 scripted utterances |
| Correction proxy | 70 normalized character edits; 257 display edits including whitespace/punctuation; 126/193 output turns touched |
| Coverage candidates | No failed ranges, whole-turn omissions or deletion runs of at least 4 characters; these heuristics do not prove complete transcription |

Actual counselor correction time, acceptability, recall speed, noisy recordings,
and natural overlapping speakers remain unmeasured. The 46-minute browser flow
tested actual upload, role assignment, individual speaker correction, text edits,
split/merge with original timestamps, local masking plus manual correction, and
actual Qwen generation. It used a local nonpersistent harness with overridden auth,
not production Vercel authentication, DB persistence, or this new main-based UI.

The **15/15 fact-preservation result belongs only to the separate synthetic Qwen
experiment plus protected-original-source rules**. Model-only selection was 4/15;
retaining chunk choices was 8/15. That extractive summary, its 96,000-character /
576-span effective budget, provider instrumentation, coverage UI and prompts are
excluded here. Optional relational insights still failed JSON/timeout checks.
Do not use those results as evidence for main or PR #72 summary quality.

## Actual processing and provider boundaries

```text
Browser File -> configured self-hosted /api/audio/transcribe
  -> temporary upload -> FFmpeg PCM -> bounded ASR -> CAM++ -> raw/editable turns
  -> counselor edits -> self-hosted /api/audio/deidentify (deterministic only)
  -> counselor checks and explicitly applies the masked text to the session form
  -> MAIN privacy-preview request -> MAIN server-side re-masking -> summary
```

The following distinction is essential. A local audio endpoint does not make the
remaining application a local-only privacy system.

| Path in inspected source | What crosses the boundary |
|---|---|
| `frontend/src/api/client.ts`: audio methods | File and corrected text go to `VITE_AUDIO_API_BASE_URL`, with the existing bearer token. If omitted, it falls back to the general API origin. Only operator-controlled HTTPS origins may be configured. Vercel has no audio model/proxy route. |
| `backend/app/audio_main.py`, `api/routes/audio.py` | Dedicated app has audio routes, verified-user auth and local masking only. It exposes no summary route. Supabase Auth can receive the token; it does not receive audio through this authentication call. |
| `services/deidentification.py:deidentify_text` | Deterministic rules only; proposals are incomplete and confirmation is a UI workflow, not proof every identifier is gone. Main's detector is retained unchanged, including missed unlabeled names and the known ordinary-word overmasking issue. |
| `DeidentificationReviewModal.tsx` -> `detectDeidentificationItems` -> `/api/notes/deidentification-preview` | On modal opening, the frontend passes original source strings to remote detection. Local candidates are collected but are not substituted before that request. Client/counselor names are also sent as context. This happens before final counselor confirmation; the modal also has a skip path. |
| `services/deidentification_preview.py:preview_items` | Joins submitted strings and calls `_extract_entities(joined)`. No preliminary local masking is applied to that model input. |
| `api/routes/notes.py:_run_pipeline_with_stub_fallback` -> `deidentify_session_input` | Regular summary always re-runs storage de-identification on submitted fields before the graph; `quick_summary.py` does likewise. This can alter already-reviewed names/aliases. |
| `services/storage_deidentification.py:deidentify_texts` | Calls `_extract_entities(joined)` **before** contact and other replacement rules. `_extract_entities` uses `get_structured_llm` unless in stub mode; catching provider failure afterwards does not undo transmission. |
| `services/llm.py:get_llm` | Main uses `ChatOpenAI` with the configured key/model (default model `gpt-5.4`), with no application-level local endpoint routing implemented by this candidate. Runtime environment overrides were not inspected or changed. In ordinary configured operation, detection itself can send raw text to the external provider. |
| `graph/nodes.py:sanitize_input`, `services/summary_skill.py` | Deterministic graph masking and the summary's sanitized input occur after the earlier model detection boundary. Their existence does not prove prior inputs stayed local. |

Audio review reduces risk for text applied through its editor, but misses can
survive; other memo/document fields and registered names can still be raw.
Neither the API nor general main flow verifies an unforgeable reviewed-input
version. The browser gate is not a backend security guarantee. A separate future
privacy task must select/qualify a local detector, preserve counselor-reviewed
aliases across downstream calls, define skip/manual-field behavior and enforce
an outbound boundary. This handoff intentionally does not implement the assigned
person-mapping work or modify production summary/privacy code.

Do not say "all counseling data stays in KoreaIDC" or "only counselor-confirmed
text reaches any AI" for the current main. The accurate claim is that this
candidate's ASR and audio-review proposals are self-hosted/local; the subsequent
main flow has the provider boundaries above.

## Storage, crash behavior, and operational prerequisites

| Artifact | Present behavior | Before accepting real data |
|---|---|---|
| Multipart spool | Framework may spool before the route; OS temporary directory | Set process `TMPDIR` to the same private ephemeral mount; configure proxy body limits before buffering. |
| Uploaded file | `persist_upload_to_temp` writes `remind_audio_*`; route `finally` deletes; validation exceptions/cancellation clean owned files | `cleanup_temp_file` suppresses unlink errors; add observable deletion failures, bounded retention, crash/startup recovery and quota controls. |
| Decoded PCM | `TemporaryDirectory(remind_pcm_*)`; normal success/error cleanup | SIGKILL, power loss, filesystem locks and filled volumes can leave data. A process restart does not itself clear a persistent temp directory. |
| Raw ASR/merged turns | Request memory then browser material state; no transcript file in production service | Disable request/response body logging, core dumps and raw swap/backup capture; decide crash diagnostics policy. Benchmark tools intentionally write outputs and must never be pointed at client data. |
| Browser audio/transcript | Object URLs released on material removal/unmount; editing needs the File and raw turns in memory | Revocation is not secure erasure and cannot remove the user's original file, browser/OS swap or external recordings. |
| Reviewed session text | General form may be stored by current main's drafts/session routes | `draft_store` and confirmation re-run model-backed de-identification. `save_original_input` defaults true, subject to counselor opt-out. `sessions.raw_input_text` can retain what reaches persistence; regular generation currently passes already re-masked input there. Do not equate the column name or audio cleanup with no retained counseling text. |

Ordinary success/failure cleanup was tested and the previous GPU/local services,
private environment/cache, uploads and job directories were removed. No hosted
accounts or rows were created. Synthetic evidence was deliberately retained.
Crash recovery, deletion-failure alerting, reverse-proxy spool retention, backup
exclusion and disk secure erasure were **not** implemented or tested here.

KoreaIDC acceptance must cover service-account-only permissions (0700 directory,
0600 files/umask 077), encrypted/quota-limited ephemeral storage, upload timeout
and rate limits, TLS/authenticated access, stale-file cleanup that cannot delete
active jobs, swap/core-dump policy, raw-data backup exclusion, and a deletion audit
without recording transcript content. Confirm provider operator/console access,
support-session logs, physical dedicated GPU allocation, backup/snapshot scope,
SSD reuse/failed-disk/contract-end disposal, and processing-contract responsibilities.
These are unresolved handoff items, not verified vendor assurances or legal advice.

## RTX PRO 4000 Blackwell 24 GB qualification

No RTX PRO 4000 job was run. A100 timings/VRAM do not establish Blackwell throughput,
driver compatibility, latency under contention, or a 24 GB concurrency budget.
The [NVIDIA capability table](https://developer.nvidia.com/cuda/gpus) lists this
GPU under compute capability 12.0. PyTorch's
[2.7 release notes](https://pytorch.org/blog/pytorch-2-7/) introduce Blackwell support
with CUDA 12.8 wheels. CTranslate2 has its own
[GPU library requirements](https://opennmt.net/CTranslate2/installation.html);
a working PyTorch import is not proof that CTranslate2 or CAM++ kernels work.

Use `backend/audio-blackwell.env.example` as an **unqualified, disabled-by-default**
acceptance profile. It specifies offline immutable model directories, CUDA FP16,
beam 1, batch 1 initially, clip VAD, 120-second cores and 5-second context. Batch 4
is the A100-tested setting; change only after measuring the target device.

1. Inventory OS, exact GPU name/compute capability, available VRAM, driver, CUDA
   libraries, FFmpeg/libsndfile and disk/temp quotas. Record software versions and
   model hashes/licenses; never copy credentials or weights from the development
   checkout implicitly.
2. Create an isolated runtime or immutable image. The evaluated A100 stack was
   Python 3.12, torch/torchaudio 2.8.0+cu126, faster-whisper 1.2.1, CTranslate2 4.8.4,
   FunASR 1.3.0 and transformers 4.57.6. **Do not reuse cu126 as a Blackwell recipe.**
   Qualify matching torch/torchaudio 2.8.0 CUDA 12.8 wheels and compatible driver /
   cuBLAS / cuDNN as a candidate, not a tested dependency lock. Do not update the
   shared server interpreter. Keep the two Torch package variants matched.
3. Verify actual allocation and a tiny kernel on GPU, CTranslate2 supported compute
   types, FFmpeg decode, large-v3 inference and CAM++ inference separately. Failure
   at any stage blocks real uploads, even if `/capabilities` says available.
4. Pre-download verified immutable model revisions and retain license notices:
   Whisper `edaa852ec7e145841d8ffdb056a99866b5f0a478`, CAM++
   `e4b6ede7ce16997aff4ae69fbca1f0175e2afede`; only if evaluating SenseVoice, its
   revision `3847d57b6bdf2dd8875cb1508d2af43d80a16bf7` and FSMN
   `df20e6b30c653645fa4ff125cacfcabd1020a669`. Check each weight license separately
   from package licenses. Infer offline; restrict network egress after download.
5. On explicit future authorization, reuse the retained synthetic WAV/reference;
   capture total/ASR/diarization time, RTF, sampled per-process and whole-device peak
   VRAM, CPU RAM, temp peak, quality/error ranges, and cleanup after failures.
   Qualify batch 1 then 4; real 60-minute dense speech and overlap remain separate
   acceptance cases. No new model experiment is scheduled by this document.

The service caches ASR and CAM++ on the process; it has no automatic LLM handoff
or unload API. One in-process slot protects a worker, not the whole host. Multiple
workers/replicas each own a slot and models. Use one worker without reload and
an operator-managed host-wide queue/process lifecycle for sequential STT then LLM.
Stop/release the STT process and verify VRAM recovery before starting a large LLM;
`torch.cuda.empty_cache()` alone does not free CTranslate2/live model allocations.

The separate Qwen experiment measured 16,352 MiB peak PyTorch allocated memory for
successful core calls; 21,756 MiB was a later whole-process snapshot, **not a measured
process peak**. STT's 4,594 MiB plus that snapshot exceeds 24 GiB, before additional
overhead. Their maxima are not a simultaneous test. Do not promise co-residency or
26B model capacity. Model size, quantization, context, KV cache and concurrency need
target-host measurements. Optional failed inference kept computing after the client
timeout in the old harness; production needs actual cancellation/worker supervision.

## Long input limits: keep STT and summary separate

STT defaults to 500 MiB and 3,600 seconds. FFmpeg decode is bounded to limit + 1
second and a 300-second subprocess timeout; excessive duration returns 422.
Only bounded cores are loaded into ASR GPU memory. The 46-minute run is real
evidence; 60-minute dense speech is not independently measured. Busy requests are
429 only after upload persistence; implement earlier proxy admission/backpressure
before production. There is no durable queue, progress API, or restart/resume.

The audio privacy proposal has a 300,000-character limit. Current main privacy
preview accepts up to 100,000 joined characters; quick summary caps input at
20,000. The retained reviewed long transcript is 21,323 characters, so it exceeds
quick summary's limit. Main's regular summary sends source text to the selected
summary skill/model and has no equivalent of the excluded experiment's deterministic
chunk/budget preflight. Provider/context/time limits can therefore fail independently
of successful STT. Do not advertise a guaranteed 60-minute upload-to-summary SLA.

## Review and application

Review [source separation](stt-source-separation.md), the changed-path allowlist,
the supplied validation ledger and the exact head/checks on Draft PR #73. Use that
reviewed revision for current source. The original local patch remains applicable
only to its recorded base and does not contain subsequent fixes. Published source
contains configuration templates, fictional scripts and docs, not credentials,
model weights, generated audio or benchmark output.

No main merge, Production deployment, GPU/model rerun, server-package change or
real-data processing is part of these follow-ups. Before any later authorized
integration, fetch main and inspect overlapping paths, especially the shared
session page; reuse unchanged checks and run only checks invalidated by the change.
