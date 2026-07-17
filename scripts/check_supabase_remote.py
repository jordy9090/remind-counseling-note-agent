"""Check remote Supabase state for Re:mind.

Usage:
    python scripts/check_supabase_remote.py

Requires Supabase service credentials. Retrieval samples run only when
OPENAI_API_KEY is present and KB embeddings exist.
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


PROJECT_REF = "bgjapctiawosgpjcyfuq"
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
from app.services.embeddings import EmbeddingError, embed_query  # noqa: E402


TABLES = [
    "cases",
    "sessions",
    "generated_notes",
    "evidence_items",
    "verification_reports",
    "kb_documents",
    "kb_chunks",
]

SAMPLE_QUERIES = [
    ("session note structure", "session_note"),
    ("privacy sensitive information warning", "session_note"),
    ("supervision report required fields", "supervision_report"),
]


def main() -> None:
    config = SupabaseConfig.from_env()
    print(f"Project ref: {PROJECT_REF}")
    print("Table checks:")
    for table in TABLES:
        count = table_count(config, table)
        print(f"- {table}: {'missing or inaccessible' if count is None else count}")

    print("KB document counts by category:")
    docs = request(config, "GET", "kb_documents", query={"select": "doc_category", "limit": "10000"})
    grouped: dict[str, int] = {}
    for row in docs or []:
        grouped[str(row.get("doc_category") or "")] = grouped.get(str(row.get("doc_category") or ""), 0) + 1
    for category, count in sorted(grouped.items()):
        print(f"- {category}: {count}")
    if not grouped:
        print("- no KB documents found")

    seed_titles = {
        doc["title"]
        for doc in json.loads((ROOT / "docs" / "kb_seed_examples.json").read_text(encoding="utf-8")).get("documents", [])
    }
    remote_titles = {
        str(row.get("title"))
        for row in request(config, "GET", "kb_documents", query={"select": "title", "limit": "10000"}) or []
    }
    seeded = seed_titles.issubset(remote_titles)
    print(f"docs/kb_seed_examples.json seeded: {seeded}")

    if not settings.openai_api_key:
        print("Sample retrieval skipped: OPENAI_API_KEY is missing.")
        return

    for query, document_type in SAMPLE_QUERIES:
        try:
            vector = embed_query(query)
        except EmbeddingError as error:
            print(f"Sample retrieval skipped for {query!r}: {error}")
            continue
        rows = request(
            config,
            "POST",
            "rpc/hybrid_search_kb",
            body={
                "query_text": query,
                "query_embedding": vector,
                "match_count": 5,
                "filter_doc_categories": None,
                "filter_document_type": document_type,
                "filter_allowed_uses": None,
                "filter_authority_levels": None,
            },
        )
        print(f"Sample query: {query}")
        for row in rows or []:
            print(
                "- "
                f"{row.get('source_ref')} "
                f"score={row.get('similarity_score')} "
                f"method={row.get('retrieval_method')}"
            )


def table_count(config: "SupabaseConfig", table: str) -> int | None:
    try:
        rows = request(config, "GET", table, query={"select": "id", "limit": "1"}, count=True)
    except SystemExit:
        return None
    return int(rows.get("count", 0)) if isinstance(rows, dict) else None


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
    count: bool = False,
) -> Any:
    query_string = f"?{urlencode(query)}" if query else ""
    url = f"{config.url}/rest/v1/{table}{query_string}"
    headers = {
        "apikey": config.key,
        "Authorization": f"Bearer {config.key}",
        "Accept": "application/json",
    }
    if count:
        headers["Prefer"] = "count=exact"
    data: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if prefer:
        headers["Prefer"] = prefer

    try:
        with urlopen(Request(url, data=data, method=method, headers=headers), timeout=60) as response:
            payload = response.read().decode("utf-8")
            content_range = response.headers.get("Content-Range", "")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Supabase {error.code}: {detail}") from error
    except URLError as error:
        raise SystemExit(f"Supabase network error: {error}") from error

    if count:
        total = content_range.rsplit("/", 1)[-1] if "/" in content_range else "0"
        return {"count": 0 if total == "*" else int(total)}
    return json.loads(payload) if payload else None


if __name__ == "__main__":
    main()

