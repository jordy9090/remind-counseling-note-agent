# Vercel Deployment

This project deploys to Vercel as a Vite frontend plus Python serverless API functions.

## Project settings

- Framework Preset: Vite
- Install Command: `npm --prefix frontend install`
- Build Command: `npm --prefix frontend run build`
- Output Directory: `frontend/dist`

The API functions are:

- `GET /api/health`
- `POST /api/notes/generate`
- `POST /api/notes/confirm`
- `POST /api/notes/supervision-report`
- `GET /api/documents/capabilities`
- `POST /api/documents/export`

## Environment variables

For an offline UI-only demo, the app can run without an OpenAI key and falls
back to deterministic output. The August 20 RAG/persistence demo must use an
OpenAI key because query embeddings need to be compatible with the remotely
seeded KB embeddings.

Recommended demo environment:

```env
USE_STUB=1
```

Optional real LLM environment:

```env
OPENAI_API_KEY=sk-proj-your-key
OPENAI_MODEL=gpt-4o-mini
USE_STUB=0
```

Do not upload real counseling data or real client information to the demo deployment.

## CLI deploy

```bash
npx vercel login
npx vercel pull --yes --environment production
npx vercel deploy --prod --archive=tgz
```

The current production alias is:

```text
https://remind-counseling-note-agent.vercel.app
```

Older shorthand:

```bash
npx vercel
npx vercel --prod
```
