# iwinv de-identification validation

## Completion criteria

- Discover entities with the owned iwinv Qwen model; no GPT detection or success fallback.
- Review the final request after person mapping, including supplementary fields.
- Bind review receipts to the actor, purpose, complete normalized request, and expiry.
- Allow only reviewed input and its derived outputs into summary/document/insight calls.
- Reject unreviewed embedding inputs and implicit retrieval of legacy source material.
- Exercise failure paths and one synthetic browser/upload flow before release.

## Validation ledger

- Base commit: `8e510180bde15ffac4971ec76bcab374fcef5822` (`github/main`, fetched at task start).
- Work branch: `codex/iwinv-deidentification`; isolated checkout, original dirty checkout preserved.
- Production rollback: `dpl_31sbGzWXHbq3tzcnezrAs5v9NgLo`, `https://remind.ai.kr`.
- Environment: local Windows development / separate iwinv service / Preview pending.
- 2026-11-12: backend imports passed; frontend initial build found missing preexisting local `pdfjs-dist` dependency. Installing dependencies in the isolated checkout.
- Cleanup: synthetic tests only; no test users or database rows created.
- 2026-11-12 16:36 KST: frontend TypeScript/Vite build passed. Existing bundle-size warning remains.
- 2026-11-12: 88 focused summary/storage/insight/embedding regressions passed. The full backend run executed 543 tests; 5 unrelated STT cases lacked local numpy/rapidfuzz, and 3 access-boundary tests still used the replaced preview contract. Updated that contract; the 40-test access/review suite passed afterward. The final 23-test review/diagnostics/summary-route suite also passed.
- 2026-11-12: actual V100/Qwen synthetic detection passed (14.72 seconds cold synchronous check; 20.58 seconds asynchronous/context-size check; 5.17 seconds warm direct HTTPS check). Name, phone, email, and institution were removed; dosage, duration, negation and score were preserved.
- 2026-11-12: real Chrome TXT upload → actual iwinv detection → required review → signed receipt → masked generation payload → rendered result passed. Only downstream generation was explicitly stubbed; no OpenAI call or database write occurred in this local check.
- 2026-11-12: user approved HTTPS 443. iwinv reported successful policy application; direct pinned-certificate HTTPS was verified. Existing SSH rules were preserved, and Ollama remains on loopback.
- Focused source security review: checked all changed routes/wrappers, signed stages and body/actor binding, HTTP credential and TLS boundary, bounded worker body/job memory, no-fallback error paths, prompt metadata removal, external embedding gating, frontend account/cancellation handling, and deployment secret separation. No unreviewed generation path was found in the changed flows. Automated negative tests cover the key boundaries; this is not a repository-wide audit.

## Scope and deployment boundary

The application transports detection requests through its existing API host to an
authenticated HTTPS service on iwinv. This change removes raw-text **OpenAI entity
detection**; it does not claim to remove Vercel from the original-input transport
path. Ollama remains loopback-only. The worker receives no database or OpenAI keys.

Existing stored material has no review proof. It is not automatically retrieved
into a new AI request. A counselor can explicitly include and review prior-session
text. Stored windows without current review authority cannot be externally embedded.

Production promotion remains separate from implementation and Preview validation.

## Service operation

- Dedicated service: `remind-deid.service`, code under `/opt/remind-deid`, runtime account `remind-deid`.
- Model endpoint remains `127.0.0.1:11434`. The authenticated HTTPS API listens on 443.
- `/jobs` runs bounded discovery asynchronously. Original text is held only in worker memory while processing; successful results are consumed on retrieval, and unread results expire after ten minutes with a thirty-second cleanup interval.
- A separate signing key stays on the application host. Receipts contain hashes and expiry, never original text. Tokens cannot authorize another actor, purpose, stage, or request body.
- Configure `DEID_SERVICE_URL`, `DEID_SERVICE_TOKEN`, `DEID_SERVICE_CA_PEM`, and `DEID_REVIEW_SIGNING_KEY`; keep `REQUIRE_DEID_REVIEW=1`. Never prefix these secrets with `VITE_`.
- Certificate renewal must update the trusted certificate in application deployment configuration before the current certificate expires. No certificate-verification bypass is used.
- Seoyoung's checkout and Python environment are untouched. No OpenAI, Supabase, Codex, or Claude credentials were copied to the worker.
