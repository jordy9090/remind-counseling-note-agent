# STT candidate source separation

## Provenance

The original checkout is `C:/Users/USER/Documents/ChatGPT/remind`, branch
`codex/ai-core-integration`, HEAD `1879757694dced5530aca80db499323dc4300767`.
It contains multiple unfinished tasks. It was neither reset, stashed, committed,
nor switched for this handoff. A private inventory records the path/hash of all
1,014 modified or untracked files present at handoff start; unselected files are
preserved without claiming authorship. Environment files, credentials, generated
audio, private datasets, model weights and whole runtime directories are not copied.

The original STT `outputs/source-manifest.json` and `stt-source.zip` identify the
owned STT files. Later browser/long-E2E artifacts identify the consent dialog,
speaker-role retention and non-looped fictional fixture. Selection is by explicit
file/hunk allowlist, never by wholesale copying the dirty checkout. The candidate
starts at GitHub main `c15249e780f7f07d8523f8fc88195c9b5d28fdf5` in a separate
managed local worktree, branch `codex/stt-experimental-handoff`.

The original candidate is `5fce276`. Dependency follow-up `2a7d3cc` adds the
default NumPy/RapidFuzz development group and synchronizes `backend/uv.lock`.
The November 2 privacy-reapplication follow-up changes only the audio apply
callback, its regression script, and these handoff documents. It does not change
ASR/diarization, dependencies, summary implementation, or person mapping.
PR #73 remains Draft; PR #72 is now independently merged into main at `f49a35e`.
The current candidate has 33 changed paths: the original 32 plus `backend/uv.lock`.

## Included files

| Files | Selected behavior |
|---|---|
| `backend/app/audio_main.py` | Dedicated audio-only FastAPI entry point, existing auth, exact CORS origins |
| `backend/app/api/routes/audio.py` | Korean transcription contract, local-only audio privacy proposal |
| `backend/app/schemas/audio.py` | Stage artifacts, stable segment IDs, partial failures and review metadata |
| `backend/app/services/audio_transcription.py` | Opt-in local engine selection/cache/capability integration; regression WhisperX remains explicit |
| `backend/app/services/local_audio_pipeline.py` | Previously evaluated bounded ASR/VAD/diarization and timestamp merge; no algorithm changes in this handoff |
| `backend/pyproject.toml` | `audio-local` / `audio-evaluation` extras and default NumPy/RapidFuzz development dependencies for synthetic CI; CTranslate2 pinned to the measured 4.8.4; no summary-evaluation extras |
| `backend/uv.lock` | Synchronized optional audio and development dependencies; base runtime versions preserved; not a qualified target-GPU environment |
| `backend/audio-runtime.env.example`, `backend/audio-blackwell.env.example` | Non-secret operator templates; Blackwell profile is unqualified and disabled |
| `backend/benchmarks/stt_{synthetic,benchmark,evaluate,rediarize,audit,gpu_probe}.py` | Fictional fixture generation, comparison/scoring and diagnostic tools |
| `backend/benchmarks/counseling_long_synthetic.py`, `backend/tests/fixtures/{stt_roleplay,counseling_long_v3}.json` | Authored fictional scripts only, no generated audio or client data |
| `backend/test_local_audio_pipeline.py`, `backend/test_stt_evaluation.py` | Existing stage/failure/cleanup/metric tests; local privacy expectation adapted to main's unchanged detector |
| `backend/test_audio_app_boundary.py` | New minimal main-integration check: existing auth, no summary route, no model call for audio masking, disabled target-host template |
| `frontend/src/api/client.ts` | Audio-origin routing and local privacy request only; main summary/preview methods unchanged |
| `frontend/src/types/{session,materials}.ts` | Audio stage/provenance metadata only; summary coverage types excluded |
| `frontend/src/lib/audioTranscriptWorkflow.ts` | Existing split/merge, timestamp provenance and anonymous-role formatting |
| `frontend/src/components/audio/AudioTranscriptEditor.tsx` | Previously tested edits, roles, playback, omission candidates and audio masking confirmation |
| `frontend/src/components/session-input/SessionInputPage.tsx` | Existing upload-consent dialog and audio lifecycle copy; unrelated summary-replacement dialog excluded |
| `frontend/src/pages/SessionDraftPage.tsx` | Audio results held for review; confirmed text applied explicitly; later privacy-only corrections replace the tracked prior block safely; main summary submission/privacy flow retained |
| `frontend/scripts/verify-audio-transcript-workflow.mjs` | Audio/editor/consent and actual-callback reapplication regressions, including repeated apply and conflicting prior blocks; unrelated summary-replacement-dialog assertions excluded |
| `docs/api_contract.md`, `docs/local-audio-runtime.md` | Audio contract and runtime explanation, corrected to disclose current-main downstream boundaries |
| `docs/stt-koreaidc-handoff.md`, this file | Evidence, exclusions, target-host acceptance and review instructions |

The `SessionDraftPage` three-way conflict was resolved by retaining main's complete
`handleSubmit` / `generateReviewed` privacy-review path. No summary prompt, seven-field
response, persistence schema, person mapping, voucher behavior, general modal or DB
migration was ported. Mixed-file extraction is checked against the final diff.

## Excluded experiments and other work

| Exclusion | Reason / retained evidence |
|---|---|
| `backend/app/graph/{summary_core,nodes}.py`, summary settings in `core/config.py`, `schemas/note.py` | Old long-input/evidence-selector pipeline; current main deleted `summary_core`; not a silent dependency of STT |
| `services/{evidence_summary,summary_grounding,llm,relational_insights}.py`, `summary-runtime.env.example` | Experimental extraction/grounding/provider behavior, including Qwen configuration, retries and timeout handling |
| Summary coverage UI/types and summary replacement-confirmation UI | Separate experiment; not necessary to adopt STT or its existing editor |
| `services/deidentification.py`, `test_storage_deidentification.py` changes | Prior detector correction is not ported into main's separate person/privacy work; missed names and ordinary-word overmasking remain explicit |
| `api/notes/recompose.py`, `backend/app/api/routes/notes.py`, summary/provider tests and benchmark servers | Production summary surface and old harness; preserve main / PR #72 ownership |
| `backend/benchmarks/stt_gpu_suite.sh`, `long_audio_e2e_server.py`, `tools/*`, `gpu.ps1`, `docs/local_gpu_workflow.md` | Historical run machinery depends on separately owned GPU tooling, private environments or synthetic harness setup. Kept in original artifacts; not required by the source-only candidate |
| `.gitignore`, `AGENTS.md`, unrelated docs/research/tools and other dirty files | Pre-existing or unattributed work is left in place; no wholesale patch or authorship claim |

The summary experiment remains available in `summary-quality-v2-source.zip`,
`long-e2e-v3-source.zip`, their evidence archives and reports. The handoff artifact
index records their hashes and explicit separation. Those archives contain old-base
experimental code, not patches to apply to current main. No summary result from
them qualifies this STT candidate's current-main downstream behavior.

## Validation boundary

Reused: prior 46-minute synthetic browser/GPU results and cleanup ledger, with
the exact audio and artifact hashes. Not reused as a passing current-main browser
run: the old auth-overridden, nonpersistent harness and experimental Qwen summary.

New checks are limited to the separated candidate: audio route/config/cleanup and
metric tests, frontend audio workflow and existing main privacy-review script,
TypeScript/Vite build, a network-free provider-boundary probe, final diff/source
review, original-file preservation and patch applicability. No production smoke
test is appropriate because nothing is deployed. Exact commands, timestamps,
candidate SHA and cleanup status are in the supplied validation ledger.

The November 2 follow-up adds synthetic callback regressions for privacy-only
corrections, repeat application, append/replace modes, unrelated memo preservation,
and atomic rejection of edited, missing, ambiguous or independently edited acoustic
blocks. These checks do not make the old browser/model run a current-main E2E.
Exact-head CI results and follow-up SHAs are linked from PR #73; the original
source/evidence archives remain immutable historical artifacts.
