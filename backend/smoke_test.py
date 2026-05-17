"""Smoke test for the Re:mind MVP V0 FastAPI backend.

Run from the backend directory:
    uv run python smoke_test.py
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def main() -> None:
    settings.use_stub = True
    settings.openai_api_key = None

    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    assert health.json() == {"status": "ok"}

    sample_path = Path(__file__).resolve().parents[1] / "sample_data" / "session_input_001.json"
    payload = json.loads(sample_path.read_text(encoding="utf-8"))
    response = client.post("/api/notes/generate", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["stub"] is True
    assert data["session_summary_draft"]["session_info"]["case_id"] == payload["case_id"]
    assert "verification_report" in data
    assert "document_transform_preview" in data

    print("Smoke test passed: /api/health and /api/notes/generate are working.")


if __name__ == "__main__":
    main()
