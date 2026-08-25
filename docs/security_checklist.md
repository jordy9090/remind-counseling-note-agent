# Security Checklist

Re:mind는 Supabase authentication과 user-scoped RLS 경로를 구현했지만, 실제 상담자료를
운영할 준비가 완료된 상태는 아닙니다. 아래 통제의 구현 여부와 배포 설정을 별도로 검증해야
합니다.

## Required Before Real Counseling Data

- Set `ENABLE_REAL_USER_AUTH=1` and verify a Supabase access token for every counseling-data request.
- Keep legacy preview-token access disabled in production. If a synthetic-data demo explicitly enables it, protect every counseling route with `REMIND_PREVIEW_API_TOKEN` and `X-Remind-Preview-Token`.
- Keep `REMIND_ALLOW_LOCAL_BYPASS=0` outside local development/test environments.
- Apply and verify the user-ownership/RLS migration for every table that can contain case, session, note, evidence, verification, draft, or case-memory data.
- Do not use `counselor_name` as a security identity. It is a display label; the verified Supabase user id is the owner boundary.
- Keep service role keys on the backend only. Never expose `SUPABASE_SERVICE_KEY` or `SUPABASE_SERVICE_ROLE_KEY` to frontend code, browser logs, screenshots, or client-side environment variables.
- Add audit logs for create/read/update/delete access to counseling records and generated notes.
- Define a retention policy for raw materials, generated drafts, confirmed notes, evidence items, and temporary drafts.
- Document who can access records, when access is allowed, and how access is reviewed.

## Raw Text And Audio Policy

- `SAVE_RAW_INPUT=0` must remain the default.
- With `SAVE_RAW_INPUT=0`, `sessions.raw_input_text` is stored as `NULL`; only sanitized input and metadata are persisted.
- `SAVE_RAW_INPUT=1` is for synthetic/demo data or explicitly approved test cases only.
- Uploaded PDF/DOCX/TXT files are streamed to temporary files for extraction and deleted after the request. Do not add raw upload persistence without authentication, access control, retention, and deletion policy review.
- Scanned PDF OCR is not supported in the MVP. Do not route image-only clinical records to third-party OCR services without a reviewed data processing agreement.
- Do not store real audio in this MVP.
- Automatic audio transcription is disabled by default. Do not enable `ENABLE_AUDIO_TRANSCRIPTION=1` for real counseling sessions without explicit consent, authentication, storage limits, model/runtime review, and a retention policy.
- Do not upload identifiable counseling materials, psychological test records, or original session audio to any public/shared demo, including deployments using a shared preview token.

## Retrieval Boundaries

- RAG is limited to case-level memory, document templates, and privacy/ethics/security guardrails.
- Dense retrieval is opt-in with `ENABLE_DENSE_RETRIEVAL=1`; real counseling records must not be embedded by default.
- Case-memory indexing is opt-in with `ENABLE_CASE_MEMORY=1`; the default must remain `ENABLE_CASE_MEMORY=0`.
- Case-memory retrieval must filter by counselor and case before ranking to prevent cross-case leakage.
- Do not use RAG to generate diagnosis, clinical risk scoring, treatment recommendations, psychological test interpretation, or counselor performance evaluation.
- KB seed files must not contain copyrighted manuals, paid psychological test material, or real counseling records.
- Use `docs/kb_seed_examples.json` as a short paraphrased demo seed only.

## Supabase Data Controls

- Verify RLS on `cases`, `sessions`, `generated_notes`, `evidence_items`, `verification_reports`, `counseling_drafts`, `case_memory_chunks`, and `retrieval_logs` with two separate test accounts.
- Keep knowledge-base writes on trusted backend/admin paths. Authenticated clients may receive read-only access only where the deployed policies explicitly allow it.
- Keep direct client access to counseling rows constrained by verified owner policies.
- Separate tenant or counselor data by authenticated owner fields before production use.
- Add deletion/export procedures before storing real client data.

## Demo Language

- Safe claim: "Re:mind is an authenticated, retrieval-aware counseling-documentation prototype undergoing operational security validation."
- Avoid: "production-ready RAG", "clinical decision support", "diagnosis assistant", or "secure real counseling data storage."
