"""Dedicated self-hosted audio API; no summary/LLM routes or model imports at startup."""
from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.audio import router
from app.core.config import validate_runtime_security


def allowed_origins() -> list[str]:
    origins = [s.strip().rstrip("/") for s in os.getenv("AUDIO_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if s.strip()]
    for origin in origins:
        parsed = urlparse(origin)
        if not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("AUDIO_ALLOWED_ORIGINS must contain exact origins")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise ValueError("Remote audio origins must use HTTPS")
    return origins


app = FastAPI(title="Re:mind local audio API")
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(), allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Remind-Preview-Token"])
app.include_router(router)


@app.on_event("startup")
async def startup():
    validate_runtime_security()
