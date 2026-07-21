"""Embed KB chunks that are new or changed.

Usage:
    python scripts/embed_kb_chunks.py

Requires:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY
    OPENAI_API_KEY

This command is explicit and never runs during app startup.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
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
from app.services.embeddings import OpenAIEmbeddingProvider, content_hash  # noqa: E402


def main() -> None:
    args = parse_args()
    config = SupabaseConfig.try_from_env()
    if not settings.openai_api_key and not args.dry_run:
        raise SystemExit("OPENAI_API_KEY is required to embed KB chunks.")

    chunks = fetch_chunks(config)
    pending = [chunk for chunk in chunks if should_embed(chunk)]
    if not pending:
        print("No KB chunks need embeddings.")
        return
    if args.dry_run:
        print(f"Dry run: {len(pending)} KB chunk(s) need embeddings with {settings.embedding_model}.")
        return

    provider = OpenAIEmbeddingProvider(settings.openai_api_key, settings.embedding_model)
    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
    updated = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        texts = [embedding_text(chunk) for chunk in batch]
        embeddings = embed_with_retry(provider, texts, retries=args.retries)
        for chunk, embedding, text in zip(batch, embeddings, texts, strict=True):
            request(
                config,
                "PATCH",
                "kb_chunks",
                query={"id": f"eq.{chunk['id']}"},
                body={
                    "embedding": embedding,
                    "embedding_model": settings.embedding_model,
                    "content_hash": content_hash(text, model=settings.embedding_model),
                    "embedding_updated_at": datetime.now(UTC).isoformat(),
                },
                prefer="return=minimal",
            )
            if config is None:
                update_chunk_embedding_cli(chunk["id"], embedding, content_hash(text, model=settings.embedding_model))
            updated += 1

    print(f"Embedded {updated} KB chunk(s) with {settings.embedding_model}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed KB chunks that are new or changed.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def embed_with_retry(provider: OpenAIEmbeddingProvider, texts: list[str], retries: int) -> list[list[float]]:
    last_error: Exception | None = None
    for attempt in range(max(retries, 1)):
        try:
            return provider.embed(texts)
        except Exception as error:
            last_error = error
            if attempt == retries - 1:
                break
            time.sleep(min(2 ** attempt, 8))
    raise SystemExit(f"Embedding provider failed after {retries} attempt(s): {last_error}") from last_error


def should_embed(chunk: dict[str, Any]) -> bool:
    text = embedding_text(chunk)
    expected_hash = content_hash(text, model=settings.embedding_model)
    return (
        not (chunk.get("embedding") or chunk.get("embedding_present"))
        or chunk.get("embedding_model") != settings.embedding_model
        or chunk.get("content_hash") != expected_hash
    )


def embedding_text(chunk: dict[str, Any]) -> str:
    parts = [
        chunk.get("section_path", ""),
        chunk.get("document_type", ""),
        chunk.get("allowed_use", ""),
        chunk.get("chunk_text", ""),
    ]
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


class SupabaseConfig:
    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.key = key

    @classmethod
    def try_from_env(cls) -> "SupabaseConfig | None":
        try:
            return cls.from_env()
        except SystemExit:
            return None

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


def fetch_chunks(config: SupabaseConfig | None) -> list[dict[str, Any]]:
    if config is not None:
        return request(
            config,
            "GET",
            "kb_chunks",
            query={
                "select": "id,chunk_text,section_path,document_type,allowed_use,content_hash,embedding_model,embedding",
                "limit": "1000",
            },
        )
    result = run_supabase_query_json(
        """
        select
          id::text,
          chunk_text,
          section_path,
          document_type,
          allowed_use,
          content_hash,
          embedding_model,
          embedding is not null as embedding_present
        from public.kb_chunks
        order by created_at asc
        limit 1000;
        """
    )
    return result.get("rows", [])


def update_chunk_embedding_cli(chunk_id: str, embedding: list[float], hash_value: str) -> None:
    vector_literal = "[" + ",".join(f"{value:.10f}" for value in embedding) + "]"
    sql = f"""
    update public.kb_chunks
    set embedding = {sql_literal(vector_literal)}::extensions.vector,
        embedding_model = {sql_literal(settings.embedding_model)},
        content_hash = {sql_literal(hash_value)},
        embedding_updated_at = now()
    where id = {sql_literal(chunk_id)};
    """
    run_supabase_sql(sql)


def run_supabase_query_json(sql: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8") as handle:
        handle.write(sql)
        path = handle.name
    try:
        completed = subprocess.run(
            [npx_executable(), "supabase", "db", "query", "--linked", "--output", "json", "--file", path],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        Path(path).unlink(missing_ok=True)
    return parse_first_json_object(completed.stdout)


def run_supabase_sql(sql: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8") as handle:
        handle.write(sql)
        path = handle.name
    try:
        subprocess.run(
            [npx_executable(), "supabase", "db", "query", "--linked", "--file", path],
            check=True,
            cwd=ROOT,
        )
    finally:
        Path(path).unlink(missing_ok=True)


def npx_executable() -> str:
    executable = shutil.which("npx.cmd") or shutil.which("npx")
    if not executable:
        raise SystemExit("npx is required for linked Supabase CLI fallback.")
    return executable


def parse_first_json_object(output: str) -> dict[str, Any]:
    start = output.find("{")
    if start < 0:
        return {"rows": []}
    depth = 0
    for index in range(start, len(output)):
        char = output[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(output[start : index + 1])
    return {"rows": []}


def sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def request(
    config: SupabaseConfig | None,
    method: str,
    table: str,
    *,
    query: dict[str, str] | None = None,
    body: Any | None = None,
    prefer: str | None = None,
) -> Any:
    if config is None:
        return None
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

