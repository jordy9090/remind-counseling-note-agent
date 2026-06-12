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

## Environment variables

For a public class/demo deployment, the app can run without an OpenAI key. If `OPENAI_API_KEY` is missing, the backend uses deterministic stub output.

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
