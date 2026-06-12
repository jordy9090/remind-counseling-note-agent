"""Vercel serverless health endpoint."""
from fastapi import FastAPI

app = FastAPI(title="Re:mind Health API")


@app.get("/")
@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
