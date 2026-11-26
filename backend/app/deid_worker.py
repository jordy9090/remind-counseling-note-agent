"""Small dedicated iwinv service. Install no OpenAI or database credentials here."""
from __future__ import annotations

import os
import secrets
import threading
import time
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from app.services.qwen_deidentification import DetectionUnavailable, Entities, detect_on_ollama

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
slot = threading.BoundedSemaphore(1)
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deid")
jobs: dict[str, dict] = {}
job_lock = threading.Lock()
expiry_task = None


class WorkerBoundary:
    """Reject unauthenticated/oversized bodies before JSON parsing or GPU work."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"] == "/detect" or scope["path"].startswith("/jobs")):
            return await self.app(scope, receive, send)
        token = os.environ.get("DEID_SERVICE_TOKEN", "")
        headers = dict(scope.get("headers", []))
        if not token or not secrets.compare_digest(headers.get(b"authorization", b""), f"Bearer {token}".encode()):
            return await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body.extend(event.get("body", b""))
            if len(body) > 1_200_000:
                return await JSONResponse({"detail": "Input too large"}, status_code=413)(scope, receive, send)
            if not event.get("more_body", False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)


app.add_middleware(WorkerBoundary)


class DetectionRequest(BaseModel):
    texts: list[str] = Field(max_length=500)

    @model_validator(mode="after")
    def bounded(self):
        if sum(map(len, self.texts)) > 200_000:
            raise ValueError("Input too long")
        return self


def cleanup_jobs():
    now = time.monotonic()
    for job_id in list(jobs):
        if jobs[job_id]["expires"] < now:
            del jobs[job_id]


async def expire_jobs():
    while True:
        with job_lock:
            cleanup_jobs()
        if os.environ.get("DEID_PRELOAD_MODEL") == "1":
            await asyncio.to_thread(preload_idle_detector)
        await asyncio.sleep(30)


def preload_idle_detector():
    """Load weights without case text. Never refresh a real prompt's keep-alive."""
    if not slot.acquire(blocking=False):
        return
    try:
        with urlopen("http://127.0.0.1:11434/api/ps", timeout=2) as response:
            if json.load(response)["models"]:
                return
        body = {"model": "qwen3.5:27b", "messages": [], "stream": False,
                "options": {"num_ctx": 16384}, "keep_alive": -1}
        request = Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60):
            pass
    except (OSError, ValueError, KeyError):
        # Normal detection remains available if optional warming fails.
        return
    finally:
        slot.release()


@app.on_event("startup")
async def start_expiry():
    global expiry_task
    expiry_task = asyncio.create_task(expire_jobs())


@app.on_event("shutdown")
async def stop_expiry():
    if expiry_task:
        expiry_task.cancel()


def run_job(job_id: str, texts: list[str]):
    try:
        with slot:
            result = detect_on_ollama(texts, timeout=900).model_dump()
    except Exception:
        result = None
    finally:
        texts.clear()
    with job_lock:
        if job_id in jobs:
            job = jobs[job_id]
            job.update(result=result, finished=True, expires=time.monotonic() + 600)
            job["ready"].set()


@app.post("/jobs")
def begin_job(payload: DetectionRequest, wait_seconds: int = 0):
    with job_lock:
        cleanup_jobs()
        if len(jobs) >= 4 or any(not job["finished"] for job in jobs.values()):
            raise HTTPException(429, "Detector is busy; retry shortly", headers={"Retry-After": "10"})
        job_id = secrets.token_urlsafe(24)
        jobs[job_id] = {"finished": False, "expires": time.monotonic() + 3600, "ready": threading.Event()}
        executor.submit(run_job, job_id, payload.texts)
    return get_job(job_id, wait_seconds)


@app.get("/jobs/{job_id}")
def get_job(job_id: str, wait_seconds: int = 0):
    if wait_seconds > 0:
        with job_lock:
            job = jobs.get(job_id)
        if job:
            job["ready"].wait(min(wait_seconds, 12))
    with job_lock:
        cleanup_jobs()
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(410, "Detection expired; start again")
        if not job["finished"]:
            return {"status": "pending", "job_id": job_id}
        if job["result"] is None:
            del jobs[job_id]
            raise HTTPException(503, "Detection unavailable; no partial result returned")
        del jobs[job_id]
        return job["result"]


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, _error):
    return JSONResponse(status_code=422, content={"detail": "Invalid detection request"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/detect", response_model=Entities)
def detect(payload: DetectionRequest, authorization: str = Header(default="")):
    token = os.environ.get("DEID_SERVICE_TOKEN", "")
    if not token or not secrets.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(401, "Unauthorized")
    if not slot.acquire(blocking=False):
        raise HTTPException(429, "Detector is busy; retry shortly", headers={"Retry-After": "10"})
    try:
        return detect_on_ollama(payload.texts)
    except DetectionUnavailable:
        raise HTTPException(503, "Detection unavailable; no partial result returned") from None
    finally:
        slot.release()
