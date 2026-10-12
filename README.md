# Re:mind

Re:mind is a counseling documentation workspace that helps counselors organize post-session materials, review evidence, and prepare drafts of session notes, supervision reports, and termination documents. AI output is a draft for review; counselors retain final responsibility for factual accuracy and clinical judgment.

## Current release and handoff

Start with the [Seoyoung handoff](docs/seoyoung_handoff.md) for the October 2 session-summary release,
its evidence, setup commands, and follow-up after the counselor demo/interview.

Verified on 2026-10-12: [remind.ai.kr](https://remind.ai.kr) runs commit
`f2e74b71a406a6a69acbbe062bf8dddeef16c8db` from `codex/fix-session-summary-quality`,
Vercel deployment `dpl_8p59zhFZ7eEtnDh2AxBn46nBaK7J` (`READY`, Production).
`origin/main` remains at `e30fe3d58354b47d22b59f59a3003795e120edb6`; [PR #36](https://github.com/jordy9090/remind-counseling-note-agent/pull/36)
is not merged. Newer handoff documentation does not mean that Production has changed.
Check the live deployment before releasing from `main`; it currently lacks the six release commits.
This snapshot does not establish remote migration state or activation of every optional feature flag.

## Stack

- Frontend: React 18, TypeScript, Vite, Tailwind CSS, Axios, Supabase Auth
- Backend: Python 3.11+, FastAPI and Vercel Python functions
- AI: LangGraph, LangChain/OpenAI structured output; optional retrieval/grounding
- Data: Supabase Postgres/Auth, optional pgvector search and record persistence
- Documents/audio: python-docx, WeasyPrint/ReportLab; optional WhisperX in a separate runtime

## Current user workflow

1. Landing is public. `로그인` opens the email login form and `무료로 시작하기` opens email signup.
   Signup sends a confirmation email; after confirmation (or an existing persisted session) the
   workspace opens. Password reset and logout are available. Anonymous sign-in is no longer used and
   anonymous tokens are rejected by the protected API.
2. Enter a case ID and session materials. Enter notes/transcripts directly or extract text from PDF/DOCX/TXT
   and apply it to the input. Automatic audio transcription requires a supporting backend.
3. Generate a session summary, inspect evidence and review items, and edit it directly. The checklist
   controls which already-generated items are displayed.
4. Transform the summary into a session note, supervision report, or termination document, then download
   the edited content as DOCX/PDF. PDF depends on server capabilities; HWPX is unsupported.
5. In the case dashboard, retrieve sessions, documents, and export history saved under an existing case ID,
   and update the planned total session count and next session date.

The ordinary workspace requests generation persistence (`persist:true`); the local DEV demo uses
`persist:false`. Temporary-save, confirmation, and record-reopen paths are implemented. Successful
storage still depends on authentication, backend configuration, ownership checks, and the API result;
unsaved browser edits are not durable. A fresh authenticated Production generation/save/reopen flow
was not part of the October 2 release smoke check; see the handoff for the exact validation boundary.
OAuth buttons render only when a provider is enabled in the Supabase project; email auth is the normal path.

Raw-region grounding is OFF by default. Successful generation persistence also stores transcript turns
and indexes windows when sanitized transcript text is available; this is distinct from enabling optional
historical retrieval. See [Architecture](docs/architecture.md) for conditions and
[Product Runtime Map](docs/product_runtime_map.md) for actual connections.

## Local setup

The commands below use PowerShell, starting at the repository root. Python 3.11+, uv,
Node.js, and pnpm are required. CI uses Python 3.11, Node.js 22, and pnpm 10.

Backend:

```powershell
Set-Location backend
uv sync --link-mode=copy
$env:USE_STUB = "1"
$env:RUNTIME_ENVIRONMENT = "development"
$env:ENABLE_REAL_USER_AUTH = "1"
$env:ENABLE_PERSISTENCE = "0"
$env:ENABLE_RAG = "0"
$env:ENABLE_CASE_MEMORY = "0"
uv run uvicorn app.main:app --reload
```

The backend reads `backend/.env`. The user authentication path requires `SUPABASE_URL` and
`SUPABASE_PUBLISHABLE_KEY`. Use the same project as the frontend. Email signup requires the project's
Site URL / Redirect URLs to include the app origin so confirmation and reset links return to Re:mind.
`USE_STUB=1` replaces OpenAI calls; it does not bypass authentication.

Run the frontend from the repository root in a separate terminal.

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
```

The frontend requires `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in
`frontend/.env.local`. Without `VITE_API_BASE_URL`, Vite's development `/api` proxy connects
to `http://localhost:8000`. The normal UI does not allow workspace entry without auth configuration.
Do not put service-role/OpenAI keys in `VITE_` variables.

For API-only checks with local synthetic data, explicitly set `ENABLE_REAL_USER_AUTH=0`,
`RUNTIME_ENVIRONMENT=development`, and `REMIND_ALLOW_LOCAL_BYPASS=1` instead of real-user
authentication. This path does not bypass the normal frontend AuthGate.
For actual WhisperX execution, follow the [H100 runbook](docs/h100_audio_runbook.md).

## Build and primary checks

Run these in their respective directories after installing dependencies.

```powershell
# backend
uv run python smoke_test.py
uv run python test_vercel_wrappers.py
uv run python test_supervision_form.py
uv run python test_case_dashboard.py
uv run python test_grounded_generation.py
uv run python test_raw_window_pipeline.py
uv run python test_transcript_storage.py
```

```powershell
# frontend
pnpm verify:material-workflow
pnpm verify:audio-transcript-workflow
pnpm verify:grounding-review
pnpm verify:counselor-edit
pnpm build
```

For the grounding DEV browser check, start the server in another terminal with
`pnpm dev -- --host 127.0.0.1 --port 4174`, then run `pnpm verify:grounding-demo-browser`.
The default browser is Windows Edge; use `EDGE_PATH` for a different installation path.
The DEV fixture is not enabled in production build/preview.

`pnpm build` runs TypeScript checks and the Vite build. Backend PDF CI installs WeasyPrint native
dependencies and Korean fonts. Local PDF generation may use the ReportLab fallback; distinguish this
from verification with the same renderer. Test coverage and CI inclusion are documented in the
[Runtime Map](docs/product_runtime_map.md#verification-commands-and-coverage).
Passing mock/stub tests does not establish remote RLS correctness, real LLM quality, or Production E2E success.

## Detailed documentation

- [Seoyoung handoff](docs/seoyoung_handoff.md): deployed source versus main, changes, validation, and pending interview feedback
- [Domestic supervision sources](docs/domestic_supervision_sources.md), [Relational evaluation](docs/relational_insight_evaluation.md)
- [Architecture](docs/architecture.md): system responsibilities and default/optional paths
- [Product Runtime Map](docs/product_runtime_map.md): connections from screens to APIs, storage, and tests
- [Data Model](docs/data_model.md): entities, ownership, persistence conditions, and migration baseline
- [API contract](docs/api_contract.md): major requests/responses and DTO concepts
- [Vercel deployment](docs/deployment_vercel.md), [Deployment checklist](docs/deployment_checklist.md):
  existing deployment guidance; compare current state with the baseline above and runtime documentation
- [Supabase migrations](supabase/README.md): migration workflow
- [Product spec](docs/product_spec.md), [Security checklist](docs/security_checklist.md):
  product hypotheses and operational security controls
- [Grounding checkpoint](docs/raw_evidence_grounding_checkpoint.md): research decisions and synthetic evaluation at that time
- [Audio licenses](docs/THIRD_PARTY_AUDIO_COMPONENTS.md), [H100 runbook](docs/h100_audio_runbook.md)

Audit logging, retention/deletion, consent, and operational security review for real counseling data remain separate work.

Use the following precedence when comparing documentation with implementation.

1. Runtime behavior: production code
2. Database schema: `supabase/migrations/`
3. Runtime documentation: this README, architecture, product runtime map, data model, API contract
4. Product/research/history documents: supporting reference. Product hypotheses and research results do not imply enabled features.
