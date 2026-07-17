"""FastAPI application for the Re:mind MVP V0 backend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import documents, health, notes

app = FastAPI(
    title="Re:mind MVP V0 API",
    description="Evidence-tracked counseling session summary API.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(notes.router)
app.include_router(documents.router)


@app.get("/")
async def root():
    return {
        "message": "Re:mind MVP V0 API",
        "docs": "/docs",
        "health": "/api/health",
        "generate": "/api/notes/generate",
        "document_capabilities": "/api/documents/capabilities",
        "export": "/api/documents/export",
    }
