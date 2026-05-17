# Re:mind Development Instructions

## Product Scope

We are building an MVP for Re:mind, a counseling documentation assistant.

The MVP V0 primary flow is:

1. Counselor enters session memo, optional transcript/STT text, and optional previous session summary.
2. FastAPI backend runs the LangGraph six-agent workflow.
3. Backend returns Pydantic-validated JSON.
4. Frontend displays structured data, evidence mapping, editable summary draft, verification report, and document transform preview.

The primary MVP path is React + FastAPI + LangGraph. Streamlit is kept only as a legacy/optional quick demo.

## Tech Stack

Frontend:
- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui

Backend:
- FastAPI
- Python 3.11
- LangGraph
- Pydantic
- OpenAI API

Package managers:
- Frontend: pnpm
- Backend: uv

## MVP Constraints

Do not add these unless explicitly requested:
- Database
- Authentication
- Audio upload
- Real-time STT
- Payment
- User management
- Vector DB
- RAG
- Deployment config

For now, the backend should process a request and return a response without persistence.

## Backend Architecture

Use this graph flow:

SessionInput
→ Input Sanitization Agent
→ Session Structuring Agent
→ Evidence Mapping Agent
→ Session Summary Draft Agent
→ Verification & Review Agent
→ Document Transform Preview Agent
→ GenerateNoteResponse

Primary routes:

- GET /api/health
- POST /api/notes/generate

Legacy compatibility routes may exist, but new MVP work should use /api/notes/generate.

All outputs must be validated with Pydantic models in backend/app/schemas/note.py.

If OPENAI_API_KEY is missing or USE_STUB=1, the backend should return deterministic stub output so the demo can run without an API key.

If information is not present in the input, do not infer it confidently. Mark it as missing or requiring counselor review.

Document Transform is preview-level in MVP V0.

## Counseling Domain Rules

The system must not claim to diagnose, evaluate risk, or replace counselor judgment.

The verification report should flag:
- unsupported inference
- possible personal information
- sensitive content
- fields requiring counselor review

The tone of generated summaries should be professional, concise, and editable by counselors.

## Development Rules

- Keep files small and modular.
- Do not over-engineer.
- Prefer readable code over clever abstractions.
- Add comments only where they clarify domain logic.
- Never commit API keys or real counseling data.
- Use synthetic sample data only.
