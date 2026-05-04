# Re:mind Development Instructions

## Product Scope

We are building an MVP for Re:mind, a counseling documentation assistant.

The MVP flow is:

1. Counselor enters session memo, optional transcript/STT text, and optional previous session summary.
2. Backend structures the input into a counseling-specific schema.
3. Backend generates a session summary draft.
4. Backend verifies unsupported inference, possible PII, and fields requiring counselor review.
5. Frontend displays structured result, summary draft, and verification report.

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
→ Structure Node
→ Summary Node
→ Verification Node
→ Final API Response

All LLM outputs must be validated with Pydantic models.

If information is not present in the input, do not infer it confidently. Mark it as missing or requiring counselor review.

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