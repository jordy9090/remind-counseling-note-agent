"""Seed synthetic case-memory chunks for dense retrieval demos.

Usage:
    python scripts/seed_synthetic_case_memory.py

This script inserts synthetic demo data only. Do not use it for real counseling
records. Real records must not be embedded until consent, RLS, audit logging,
and retention policy are in place.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(ROOT / ".env")
load_env_file(ROOT / "backend" / ".env")

from app.core.config import settings  # noqa: E402
from app.services.embeddings import content_hash, get_embedding_provider  # noqa: E402


SYNTHETIC_CHUNKS = [
    {
        "field_type": "session_theme",
        "chunk_text": "The client repeatedly described career uncertainty and self-critical thoughts during job preparation.",
    },
    {
        "field_type": "client_response",
        "chunk_text": "The client reported anxiety decreasing when choices were broken into smaller next actions.",
    },
    {
        "field_type": "next_plan",
        "chunk_text": "The next session plan was to review one job-search action and one self-critical thought record.",
    },
]


def main() -> None:
    config = SupabaseConfig.from_env()
    counselor_id = os.getenv("SYNTHETIC_COUNSELOR_ID", "demo-counselor")
    case_id = os.getenv("SYNTHETIC_CASE_ID", "demo-case-001")
    session_id = seed_case_and_session(config, counselor_id, case_id)

    provider = get_embedding_provider()
    texts = [chunk["chunk_text"] for chunk in SYNTHETIC_CHUNKS]
    embeddings = provider.embed(texts)
    rows = []
    for index, (chunk, embedding) in enumerate(zip(SYNTHETIC_CHUNKS, embeddings, strict=True), start=1):
        rows.append(
            {
                "counselor_id": counselor_id,
                "case_id": case_id,
                "session_id": session_id,
                "session_number": 1,
                "session_date": "2026-07-17",
                "field_type": chunk["field_type"],
                "chunk_text": chunk["chunk_text"],
                "source_ref": f"synthetic_case_memory:{case_id}:1:{index}",
                "metadata_json": {"synthetic": True},
                "embedding": embedding,
                "embedding_model": settings.embedding_model,
                "content_hash": content_hash(chunk["chunk_text"], model=settings.embedding_model),
            }
        )

    request(config, "POST", "case_memory_chunks", body=rows, prefer="return=minimal")
    print(f"Seeded {len(rows)} synthetic case-memory chunk(s) for {case_id}.")


def seed_case_and_session(config: "SupabaseConfig", counselor_id: str, case_id: str) -> str:
    request(
        config,
        "POST",
        "cases",
        query={"on_conflict": "id"},
        body=[{"id": case_id, "case_alias": case_id, "counselor_id": counselor_id, "status": "active"}],
        prefer="resolution=merge-duplicates,return=minimal",
    )
    rows = request(
        config,
        "POST",
        "sessions",
        query={"on_conflict": "case_id,session_number"},
        body=[
            {
                "case_id": case_id,
                "session_number": 1,
                "session_date": "2026-07-17",
                "session_title": "Synthetic dense retrieval demo",
                "raw_input_text": None,
                "sanitized_input_text": json.dumps({"synthetic": True}),
            }
        ],
        prefer="resolution=merge-duplicates,return=representation",
    )
    return str(rows[0]["id"])


class SupabaseConfig:
    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.key = key

    @classmethod
    def from_env(cls) -> "SupabaseConfig":
        url = os.getenv("SUPABASE_URL", "").strip()
        key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        )
        if not url or not key:
            raise SystemExit(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY are required."
            )
        return cls(url, key)


def request(
    config: SupabaseConfig,
    method: str,
    table: str,
    *,
    query: dict[str, str] | None = None,
    body: Any | None = None,
    prefer: str | None = None,
) -> Any:
    query_string = f"?{urlencode(query)}" if query else ""
    url = f"{config.url}/rest/v1/{table}{query_string}"
    headers = {
        "apikey": config.key,
        "Authorization": f"Bearer {config.key}",
        "Accept": "application/json",
    }
    data: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if prefer:
        headers["Prefer"] = prefer

    try:
        with urlopen(Request(url, data=data, method=method, headers=headers), timeout=60) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Supabase {error.code}: {detail}") from error
    except URLError as error:
        raise SystemExit(f"Supabase network error: {error}") from error

    return json.loads(payload) if payload else None


if __name__ == "__main__":
    main()

