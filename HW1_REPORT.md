# Re:mind Counseling Note Agent Report

Homework #1: LangGraph-Based Agentic System  
Hyunseo Oh | 2315073 | Data Science Track

## 1. Functionality

Re:mind Counseling Note Agent is a LangGraph-based multi-agent system that helps a counselor turn post-session materials into structured counseling documentation.

The system accepts session metadata, counselor memo, transcript/STT text, previous-session summary, counseling goal, optional psychological-test notes, key issue tags, and nonverbal notes. The FastAPI backend runs a six-node LangGraph workflow that sanitizes the input, structures counseling content, maps generated claims to evidence, drafts an editable session summary, verifies unsupported or sensitive content, and previews possible document transformations.

The system is designed as a counseling documentation assistant, not a clinical decision maker. It does not diagnose, evaluate risk, or replace counselor judgment. Generated text is returned as editable draft content, and uncertain or sensitive fields are marked for counselor review.

## 2. Quick Start

Recommended Python version: 3.11. No API keys are included in this repository.

Backend smoke test with deterministic stub output:

```bash
cd backend
uv sync --link-mode=copy
uv run python smoke_test.py
```

If `uv` is not installed, install it first:

```bash
pip install uv
```

Run the FastAPI backend:

```bash
cd backend
uv run uvicorn app.main:app --reload
```

The primary API routes are:

```text
GET  /api/health
POST /api/notes/generate
```

When `OPENAI_API_KEY` is missing or `USE_STUB=1`, the backend returns deterministic stub output so the demo can run without an API key.

To run with a real OpenAI API key:

```bash
cd backend
export OPENAI_API_KEY=your_api_key_here
export USE_STUB=0
uv run uvicorn app.main:app --reload
```

For Windows PowerShell:

```powershell
cd backend
$env:UV_LINK_MODE="copy"
$env:OPENAI_API_KEY="your_api_key_here"
$env:USE_STUB="0"
uv run uvicorn app.main:app --reload
```

Frontend demo:

```bash
cd frontend
pnpm install
pnpm dev
```

A legacy optional Streamlit demo is also available:

```bash
streamlit run streamlit_app.py
```

## 3. Requirement Mapping

| Requirement | Evidence |
| --- | --- |
| Allowed framework | LangGraph is used in `backend/app/graph/graph.py` through `StateGraph`, graph nodes, edges, and compiled workflow execution. |
| At least five agents | 6 specialized graph nodes are implemented: Input Sanitization, Session Structuring, Evidence Mapping, Summary Draft, Verification & Review, and Document Transform Preview. |
| At least five design patterns | More than five agentic design patterns are implemented through graph orchestration, prompt chaining, evidence grounding, structured output, fallback routing, critic-review, guardrails, and human-in-the-loop review. |
| Independent system | Re:mind is a standalone counseling documentation assistant, separate from the CrewAI ResearchPilot system used for Homework #2. |
| Described functionality | The backend returns structured case data, evidence mapping, editable summary draft, verification report, document transform preview, confirmed-note draft metadata, and sanitized input. |
| Easy to run/evaluate | `uv run python smoke_test.py` runs without an API key and validates `/api/health` and `/api/notes/generate`. |

## 4. Agents

| # | Agent | Role | Output |
| --- | --- | --- | --- |
| 1 | Input Sanitization Agent | Normalizes input sources and detects possible sensitive information such as phone numbers, emails, school names, and name-like text. | `sanitized_input`, sensitive information candidates, stub-mode flag |
| 2 | Session Structuring Agent | Converts sanitized materials into a common counseling documentation schema. | Presenting problem, session theme, session content, counselor interventions, client responses, key utterances, nonverbal observations, reflection candidates, next plan |
| 3 | Evidence Mapping Agent | Links structured claims to source references and marks content that requires review. | `evidence_mapped_data` with field, content, evidence type, source refs, and review flag |
| 4 | Session Summary Draft Agent | Produces an editable counseling note draft from structured data and evidence mapping. | `session_summary_draft` with section-level evidence type and source refs |
| 5 | Verification & Review Agent | Reviews the draft for grounded claims, weakly grounded claims, risky claims, sensitive information, and counselor-review fields. | `verification_report` |
| 6 | Document Transform Preview Agent | Previews how the confirmed session note could support later document formats such as supervision report or termination report. | `document_transform_preview`, missing required fields, partial preview sections |

## 5. Agentic Design Patterns

| Pattern | Implementation | Purpose |
| --- | --- | --- |
| Multi-agent collaboration | Six specialized LangGraph nodes divide the counseling documentation workflow. | Keeps responsibilities clear and inspectable. |
| Graph-based orchestration | `StateGraph` defines node order from sanitization to document preview. | Makes execution predictable and easy to evaluate. |
| Prompt chaining | Earlier outputs become state inputs for later nodes: sanitized input -> structure -> evidence map -> summary -> verification -> document preview. | Reduces one-shot generation risk and preserves intermediate reasoning. |
| Evidence grounding | Evidence mapping records source references such as `counselor_memo`, `transcript_text`, and `previous_session_summary`. | Helps counselors inspect where generated claims came from. |
| Structured output | All major outputs use Pydantic models in `backend/app/schemas/note.py`. | Prevents format drift and supports reliable frontend rendering. |
| Fallback routing / mode switching | Missing API key or `USE_STUB=1` switches the workflow to deterministic stub output; the API wrapper also falls back to stub mode if live execution fails. | Allows grading and demos without API-key setup. |
| Reflection / critic-reviewer | The Verification & Review Agent separates grounded, weakly grounded, risky, sensitive, and counselor-review items. | Catches unsupported or risky output before final use. |
| Guardrails / safety | The prompts and verification model avoid diagnosis, risk evaluation, and final clinical judgment. | Keeps the system within counseling documentation support. |
| Human-in-the-loop review | Reflection, case conceptualization, goal attainment, and uncertain fields are marked for counselor review. | Keeps final responsibility with the counselor. |

## 6. API Key Policy

- No API keys are included in the repository.
- If `OPENAI_API_KEY` is missing, the backend uses deterministic stub output.
- `USE_STUB=1` forces offline stub mode even if an API key exists.
- Live mode reads `OPENAI_API_KEY` and `OPENAI_MODEL` from the environment.

## 7. Example Input and Expected Output

Example input is provided in:

```text
sample_data/session_input_001.json
```

Expected core response from `POST /api/notes/generate` includes:

- `sanitized_input`: normalized input sources and sensitive information candidates
- `structured_case_data`: structured counseling documentation fields
- `evidence_mapped_data`: evidence-linked claims and review flags
- `session_summary_draft`: editable counseling note sections
- `verification_report`: grounded claims, weakly grounded claims, risky claims, sensitive items, and counselor-review fields
- `document_transform_preview`: preview-level document transformation information
- `confirmed_session_note`: draft status and review summary metadata

## 8. Inspectable Artifacts

| File or Route | Purpose |
| --- | --- |
| `backend/smoke_test.py` | Runs the backend in stub mode and validates the health and note-generation routes. |
| `sample_data/session_input_001.json` | Synthetic counseling-session sample input. |
| `sample_data/session_output_001.json` | Sample compact output for quick inspection. |
| `GET /api/health` | Health check endpoint. |
| `POST /api/notes/generate` | Primary full JSON generation endpoint. |
| `frontend/src/pages/SessionDraftPage.tsx` | React screen for input, editable summary draft, verification report, and document transform preview. |

## 9. Notes for Grading

- The system should be evaluated through the FastAPI backend and smoke test, not through a non-existent root CLI.
- The main grading command is `cd backend && uv run python smoke_test.py`.
- The primary implementation path is React + FastAPI + LangGraph.
- Streamlit is retained only as a legacy optional quick demo.
- All counseling examples are synthetic and should not contain real counseling data.
