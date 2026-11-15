"""FastAPI application for the Re:mind MVP backend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import audio, cases, documents, health, materials, notes
from app.api.routes.vouchers import router as voucher_router
from app.core.config import settings, validate_runtime_security

app = FastAPI(
    title="Re:mind MVP API",
    description="Evidence-tracked counseling session summary API.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.api_cors_allowed_origins.split(",") if origin.strip()] + ([
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ] if settings.is_local_environment else []),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Retry-After"],
)


@app.middleware("http")
async def prevent_api_caching(request, call_next):
    response = await call_next(request)
    if "no-store" not in response.headers.get("Cache-Control", "").lower():
        response.headers["Cache-Control"] = "no-store"
    return response

app.include_router(health.router)
app.include_router(notes.router)
app.include_router(cases.router)
app.include_router(documents.router)
app.include_router(materials.router)
app.include_router(audio.router)
app.include_router(voucher_router)


@app.on_event("startup")
async def validate_startup_security() -> None:
    validate_runtime_security()


@app.get("/")
async def root():
    return {
        "message": "Re:mind MVP API",
        "docs": "/docs",
        "health": "/api/health",
        "generate": "/api/notes/generate",
        "document_capabilities": "/api/documents/capabilities",
        "export": "/api/documents/export",
        "material_extract": "/api/materials/documents/extract",
        "audio_capabilities": "/api/audio/capabilities",
    }
