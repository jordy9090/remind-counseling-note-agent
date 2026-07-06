"""Seed demo KB documents/chunks into Supabase.

Usage from the repository root:
    python scripts/seed_kb_examples.py

This script is optional and never runs during normal app startup. It is for
short paraphrased demo KB chunks only; do not seed real counseling records,
copyrighted manuals, or paid psychological test material.
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
DEFAULT_SEED_PATH = ROOT / "docs" / "kb_seed_examples.json"


def main() -> None:
    seed_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED_PATH
    config = SupabaseConfig.from_env()
    seed = json.loads(seed_path.read_text(encoding="utf-8"))

    inserted_documents = 0
    inserted_chunks = 0
    skipped_documents = 0

    for document in seed.get("documents", []):
        existing = find_document(config, document)
        if existing:
            document_id = existing["id"]
            skipped_documents += 1
        else:
            rows = request(
                config,
                "POST",
                "kb_documents",
                body=[
                    {
                        "title": document["title"],
                        "source_type": document.get("source_type", ""),
                        "authority_level": document.get("authority_level", "internal_demo"),
                        "doc_category": document["doc_category"],
                        "source_url": document.get("source_url"),
                        "effective_date": document.get("effective_date"),
                        "allowed_use": document.get(
                            "allowed_use",
                            "verification_and_documentation_support_only",
                        ),
                    }
                ],
                prefer="return=representation",
            )
            document_id = rows[0]["id"]
            inserted_documents += 1

        if has_chunks(config, document_id):
            continue

        chunks = [
            {
                "document_id": document_id,
                "chunk_text": chunk["chunk_text"],
                "chunk_type": chunk.get("chunk_type", "guideline"),
                "metadata_json": chunk.get("metadata_json", {}),
            }
            for chunk in document.get("chunks", [])
        ]
        if chunks:
            request(config, "POST", "kb_chunks", body=chunks, prefer="return=minimal")
            inserted_chunks += len(chunks)

    print(
        "Seed complete: "
        f"{inserted_documents} document(s) inserted, "
        f"{skipped_documents} existing document(s) reused, "
        f"{inserted_chunks} chunk(s) inserted."
    )


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


def find_document(config: SupabaseConfig, document: dict[str, Any]) -> dict[str, Any] | None:
    rows = request(
        config,
        "GET",
        "kb_documents",
        query={
            "title": f"eq.{document['title']}",
            "source_type": f"eq.{document.get('source_type', '')}",
            "doc_category": f"eq.{document['doc_category']}",
            "select": "id,title",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


def has_chunks(config: SupabaseConfig, document_id: str) -> bool:
    rows = request(
        config,
        "GET",
        "kb_chunks",
        query={"document_id": f"eq.{document_id}", "select": "id", "limit": "1"},
    )
    return bool(rows)


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
        with urlopen(Request(url, data=data, method=method, headers=headers), timeout=30) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Supabase {error.code}: {detail}") from error
    except URLError as error:
        raise SystemExit(f"Supabase network error: {error}") from error

    return json.loads(payload) if payload else None


if __name__ == "__main__":
    main()
