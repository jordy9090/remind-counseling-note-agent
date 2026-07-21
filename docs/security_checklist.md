# Security Checklist

Re:mind V1 is a lightweight retrieval-aware documentation demo. Do not store real counseling data until the controls below are implemented and reviewed.

## Required Before Real Counseling Data

- Enable authentication and identify the counselor/organization for every request.
- Until production Auth exists, protect every `/api/notes/*` route with `REMIND_PREVIEW_API_TOKEN` and `X-Remind-Preview-Token`.
- Keep `REMIND_ALLOW_LOCAL_BYPASS=0` outside local development/test environments.
- Configure Supabase Row Level Security for every table that can contain case, session, note, evidence, verification, or draft data.
- Do not use `counselor_name` as a production security identity. It is a display/demo label until Supabase Auth user-to-counselor mapping exists.
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
- Public demo deployments have no authentication. Do not upload identifiable counseling materials, psychological test records, or original session audio to public deployments.

## Retrieval Boundaries

- RAG is limited to case-level memory, document templates, and privacy/ethics/security guardrails.
- Dense retrieval is opt-in with `ENABLE_DENSE_RETRIEVAL=1`; real counseling records must not be embedded by default.
- Case-memory indexing is opt-in with `ENABLE_CASE_MEMORY=1`; the default must remain `ENABLE_CASE_MEMORY=0`.
- Case-memory retrieval must filter by counselor and case before ranking to prevent cross-case leakage.
- Do not use RAG to generate diagnosis, clinical risk scoring, treatment recommendations, psychological test interpretation, or counselor performance evaluation.
- KB seed files must not contain copyrighted manuals, paid psychological test material, or real counseling records.
- Use `docs/kb_seed_examples.json` as a short paraphrased demo seed only.

## Supabase Data Controls

- Apply RLS to `cases`, `sessions`, `generated_notes`, `evidence_items`, `verification_reports`, `kb_documents`, `kb_chunks`, and `counseling_drafts`.
- Apply RLS to `case_memory_chunks` before any real case memory is stored.
- Keep direct anon/authenticated client access denied until verified owner/tenant policies are implemented.
- Restrict `kb_documents` and `kb_chunks` writes to trusted backend/admin paths.
- Separate tenant or counselor data by authenticated owner fields before production use.
- Add deletion/export procedures before storing real client data.

## Demo Language

- Safe claim: "Re:mind V1 is a lightweight retrieval-aware workflow for counseling documentation demos."
- Avoid: "production-ready RAG", "clinical decision support", "diagnosis assistant", or "secure real counseling data storage."
