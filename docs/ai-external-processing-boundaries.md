# External AI Processing Boundaries

This review covers the repository state on 2026-10-19. It uses synthetic data only and does not claim legal anonymization or regulatory compliance.

## Transmission map

| Path | External destination | Material sent | Boundary and current status |
| --- | --- | --- | --- |
| Public Quick Summary | Configured generation provider | Deterministically masked current-session text, then structured evidence | No Supabase read/write, prior-session context, actor context, or persistence. Raw text is sent once; the summary call reuses structured evidence. |
| Authenticated Full Summary (`persist=false`) | Configured generation provider | Deterministically masked current-session sources; retrieved context only when enabled | Generation provider is selected once per process configuration. There is no automatic provider fallback. |
| Authenticated Full Summary (`persist=true`) | Configured generation provider, then Supabase | Generation receives deterministically masked session material. Storage entity extraction is disabled by default; an explicit opt-in receives only the deterministic masking baseline. | Raw storage text is no longer sent as entered for entity extraction. Unknown contextual quasi-identifiers can remain after deterministic masking, so this is not an anonymity guarantee. |
| Dense retrieval / memory indexing | OpenAI embeddings endpoint | Sanitized retrieval query or de-identified stored chunks | Explicitly enabled only. Embedding telemetry records counts and latency, never text. Generation-provider configuration does not silently redirect embeddings. |
| Relational insight, grounded generation, claim support | Configured generation provider | Sanitized current-session sources and/or explicitly retrieved evidence | Optional paths. Failure preserves the base summary or fails closed depending on the validation stage. |
| Audio transcription | Local WhisperX / pyannote runtime | Uploaded audio is processed by the configured local runtime | Model artifacts may be fetched from their registries during setup, but this code has no remote transcription API call. |
| Supabase Auth and Data API | Configured Supabase project | JWT validation, owned records, and retrieval RPC payloads | Public Quick does not enter this path. This sprint makes no schema, RLS, Production DB, or credential changes. |

The deterministic masker now covers common direct identifiers, institutions, selected rare occupations, and distinctive competition/award phrases. It cannot guarantee that every contextual quasi-identifier is removed. Counselor review and a documented data-processing decision remain required before sending real counseling material to any external provider.

## Request and deployment limits

- Public Quick: 20,000 characters, one chunk, at most three generation calls including one possible format repair, a conservative USD 0.30 estimate cap for known pricing, two concurrent calls per warm instance, 60-second provider timeout, and zero provider retries.
- Authenticated Full: 96,000 sanitized characters/tokens by conservative estimate, at most eight chunks, ten core calls, and sixteen total observed generation calls.
- The in-memory Quick rate limit and concurrency semaphore are instance-local. Vercel can create multiple instances, so they are defense in depth rather than a global spend cap. A shared limit needs approved existing infrastructure or a separately approved durable store.
- `vercel.json` sets `api/notes/generate.py` to 300 seconds. Vercel currently documents a 4.5 MB request/response limit and 300-second Hobby maximum; Pro/Enterprise can configure higher limits. The implementation keeps synchronous work within the repository's 300-second setting rather than raising it. See [Vercel Function limits](https://vercel.com/docs/functions/limitations) and [duration configuration](https://vercel.com/docs/functions/configuring-functions/duration).

## Generation provider abstraction

`LLM_PROVIDER=openai` uses the OpenAI endpoint. `LLM_PROVIDER=openai_compatible` requires one explicit `OPENAI_COMPATIBLE_BASE_URL` and never falls back to OpenAI after an error. Structured Pydantic output is validated through the same shared core.

`ALLOW_EXTERNAL_STORAGE_ENTITY_EXTRACTION=0` is the secure default. Enabling it is an explicit data-processing decision; even then, supported direct identifiers and known aliases are masked before the extraction request.

The reproducible compatibility harness is:

```bash
cd backend
PYTHONPATH=. ../.venv-dev/bin/python -m benchmarks.provider_compatibility \
  --base-url http://127.0.0.1:8000/v1 \
  --model local-model-name \
  --minutes 10 \
  --style speakers
```

No model was downloaded or executed during this sprint. Candidate order for a separately approved A100 experiment:

| Candidate | Why evaluate | Approximate single-GPU weight memory |
| --- | --- | --- |
| Qwen3 14B | Apache-2.0, 40K native context, practical first structured-output baseline | ~28 GB BF16 or ~7–10 GB 4-bit plus KV cache/runtime |
| Gemma 3 12B / 27B | 128K context and official multilingual support across 140+ languages | ~24 / 54 GB BF16 or ~6–16 GB 4-bit plus overhead |
| EXAONE 4.0 32B | Official English/Korean/Spanish model and the most directly Korean-oriented candidate | ~64 GB BF16 or ~16–22 GB 4-bit plus overhead |

Sources: [Qwen3 14B config](https://huggingface.co/Qwen/Qwen3-14B/blob/main/config.json), [Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3), [EXAONE 4 documentation](https://huggingface.co/docs/transformers/ko/model_doc/exaone4). Memory figures are engineering estimates from parameter count and quantization, not measured results.
