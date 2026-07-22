"""Seed demo KB documents/chunks into Supabase.

Usage from the repository root:
    python scripts/seed_kb_examples.py

This script is optional and never runs during normal app startup. It is for
short paraphrased demo KB chunks only; do not seed real counseling records,
copyrighted manuals, or paid psychological test material.
"""
from __future__ import annotations

import argparse
import json
import os
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED_PATH = ROOT / "docs" / "kb_seed_examples.json"


def main() -> None:
    args = parse_args()
    load_env_file(ROOT / ".env")
    load_env_file(ROOT / "backend" / ".env")
    seed_path = Path(args.seed_path)
    config = None if args.dry_run else SupabaseConfig.try_from_env()
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    if config is None and not args.dry_run:
        seed_with_cli(seed)
        return

    inserted_documents = 0
    updated_documents = 0
    inserted_chunks = 0
    updated_chunks = 0
    skipped_documents = 0

    for document in seed.get("documents", []):
        document_checksum = checksum_json(document)
        existing = None if config is None else find_document(config, document)
        if existing:
            document_id = existing["id"]
            skipped_documents += 1
            if existing.get("checksum") != document_checksum:
                updated_documents += 1
                if not args.dry_run:
                    request(
                        config,
                        "PATCH",
                        "kb_documents",
                        query={"id": f"eq.{document_id}"},
                        body=document_row(document, document_checksum),
                        prefer="return=minimal",
                    )
        else:
            inserted_documents += 1
            if args.dry_run:
                document_id = f"dry-run:{document.get('slug') or document['title']}"
            else:
                rows = request(
                    config,
                    "POST",
                    "kb_documents",
                    body=[document_row(document, document_checksum)],
                    prefer="return=representation",
                )
                document_id = rows[0]["id"]

        chunks = [
            {
                "document_id": document_id,
                "chunk_text": chunk["chunk_text"],
                "chunk_type": chunk.get("chunk_type", "guideline"),
                "section_path": chunk.get("section_path", ""),
                "document_type": chunk.get("document_type", document.get("source_type", "")),
                "allowed_use": chunk.get("allowed_use", document.get("allowed_use", "")),
                "counselor_review_required": bool(chunk.get("counselor_review_required", False)),
                "source_ref": chunk.get("source_ref")
                or f"kb:{document.get('slug') or document_id}:{index + 1}",
                "content_hash": chunk_content_hash(chunk, document),
                "metadata_json": chunk.get("metadata_json", {}),
            }
            for index, chunk in enumerate(document.get("chunks", []))
        ]
        for chunk in chunks:
            existing_chunk = None if args.dry_run else find_chunk_by_source_ref(config, chunk["source_ref"])
            if existing_chunk:
                if existing_chunk.get("content_hash") != chunk["content_hash"]:
                    updated_chunks += 1
                    request(
                        config,
                        "PATCH",
                        "kb_chunks",
                        query={"id": f"eq.{existing_chunk['id']}"},
                        body=chunk,
                        prefer="return=minimal",
                    )
            else:
                inserted_chunks += 1
                if not args.dry_run:
                    request(config, "POST", "kb_chunks", body=[chunk], prefer="return=minimal")

    print(
        ("Dry run complete: " if args.dry_run else "Seed complete: ") +
        f"{inserted_documents} document(s) inserted, "
        f"{updated_documents} document(s) updated, "
        f"{skipped_documents} existing document(s) reused, "
        f"{inserted_chunks} chunk(s) inserted, "
        f"{updated_chunks} chunk(s) updated."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed demo KB documents/chunks into Supabase.")
    parser.add_argument("seed_path", nargs="?", default=str(DEFAULT_SEED_PATH))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def document_row(document: dict[str, Any], checksum: str) -> dict[str, Any]:
    meta = {"slug": document.get("slug", "")}
    if "metadata_json" in document and isinstance(document["metadata_json"], dict):
        meta.update(document["metadata_json"])
    return {
        "title": document["title"],
        "source_org": document.get("source_org", ""),
        "source_type": document.get("source_type", ""),
        "authority_level": document.get("authority_level", "internal_demo"),
        "doc_category": document["doc_category"],
        "source_url": document.get("source_url"),
        "effective_date": document.get("effective_date"),
        "allowed_use": document.get(
            "allowed_use",
            "verification_and_documentation_support_only",
        ),
        "checksum": checksum,
        "metadata_json": meta,
    }


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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


def seed_with_cli(seed: dict[str, Any]) -> None:
    statements = ["do $$", "declare", "  v_document_id uuid;", "  v_chunk_id uuid;", "begin"]
    inserted_documents = 0
    chunks_total = 0
    for document in seed.get("documents", []):
        checksum = checksum_json(document)
        slug = document.get("slug", "")
        doc_meta = {"slug": slug}
        if "metadata_json" in document and isinstance(document["metadata_json"], dict):
            doc_meta.update(document["metadata_json"])
        inserted_documents += 1
        statements.extend(
            [
                f"  select id into v_document_id from public.kb_documents where metadata_json->>'slug' = {sql_literal(slug)} limit 1;",
                "  if v_document_id is null then",
                "    insert into public.kb_documents (title, source_org, source_type, authority_level, doc_category, source_url, effective_date, allowed_use, checksum, metadata_json)",
                (
                    "    values ("
                    f"{sql_literal(document['title'])}, "
                    f"{sql_literal(document.get('source_org', ''))}, "
                    f"{sql_literal(document.get('source_type', ''))}, "
                    f"{sql_literal(document.get('authority_level', 'internal_demo'))}, "
                    f"{sql_literal(document['doc_category'])}, "
                    f"{sql_nullable(document.get('source_url'))}, "
                    f"{sql_nullable(document.get('effective_date'))}, "
                    f"{sql_literal(document.get('allowed_use', 'verification_and_documentation_support_only'))}, "
                    f"{sql_literal(checksum)}, "
                    f"{sql_json(doc_meta)}"
                    ") returning id into v_document_id;"
                ),
                "  else",
                "    update public.kb_documents set",
                (
                    f"      title = {sql_literal(document['title'])}, "
                    f"source_org = {sql_literal(document.get('source_org', ''))}, "
                    f"source_type = {sql_literal(document.get('source_type', ''))}, "
                    f"authority_level = {sql_literal(document.get('authority_level', 'internal_demo'))}, "
                    f"doc_category = {sql_literal(document['doc_category'])}, "
                    f"source_url = {sql_nullable(document.get('source_url'))}, "
                    f"effective_date = {sql_nullable(document.get('effective_date'))}, "
                    f"allowed_use = {sql_literal(document.get('allowed_use', 'verification_and_documentation_support_only'))}, "
                    f"checksum = {sql_literal(checksum)}, "
                    f"metadata_json = {sql_json(doc_meta)}, "
                    "updated_at = now()"
                ),
                "    where id = v_document_id;",
                "  end if;",
            ]
        )
        for index, chunk in enumerate(document.get("chunks", [])):
            source_ref = chunk.get("source_ref") or f"kb:{slug or document['title']}:{index + 1}"
            chunk_hash = chunk_content_hash(chunk, document)
            chunks_total += 1
            statements.extend(
                [
                    f"  select id into v_chunk_id from public.kb_chunks where source_ref = {sql_literal(source_ref)} limit 1;",
                    "  if v_chunk_id is null then",
                    "    insert into public.kb_chunks (document_id, chunk_text, chunk_type, section_path, document_type, allowed_use, counselor_review_required, source_ref, content_hash, metadata_json)",
                    (
                        "    values (v_document_id, "
                        f"{sql_literal(chunk['chunk_text'])}, "
                        f"{sql_literal(chunk.get('chunk_type', 'guideline'))}, "
                        f"{sql_literal(chunk.get('section_path', ''))}, "
                        f"{sql_literal(chunk.get('document_type', document.get('source_type', '')))}, "
                        f"{sql_literal(chunk.get('allowed_use', document.get('allowed_use', '')))}, "
                        f"{'true' if chunk.get('counselor_review_required', False) else 'false'}, "
                        f"{sql_literal(source_ref)}, "
                        f"{sql_literal(chunk_hash)}, "
                        f"{sql_json(chunk.get('metadata_json', {}))}"
                        ");"
                    ),
                    "  else",
                    "    update public.kb_chunks set",
                    (
                        "      document_id = v_document_id, "
                        f"chunk_text = {sql_literal(chunk['chunk_text'])}, "
                        f"chunk_type = {sql_literal(chunk.get('chunk_type', 'guideline'))}, "
                        f"section_path = {sql_literal(chunk.get('section_path', ''))}, "
                        f"document_type = {sql_literal(chunk.get('document_type', document.get('source_type', '')))}, "
                        f"allowed_use = {sql_literal(chunk.get('allowed_use', document.get('allowed_use', '')))}, "
                        f"counselor_review_required = {'true' if chunk.get('counselor_review_required', False) else 'false'}, "
                        f"content_hash = {sql_literal(chunk_hash)}, "
                        f"metadata_json = {sql_json(chunk.get('metadata_json', {}))}"
                    ),
                    "    where id = v_chunk_id;",
                    "  end if;",
                ]
            )
    statements.extend(["end $$;"])
    run_supabase_sql("\n".join(statements))
    print(f"Seed complete through linked CLI: {inserted_documents} document(s), {chunks_total} chunk(s) upserted.")


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


def sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_nullable(value: Any) -> str:
    return "null" if value in (None, "") else sql_literal(value)


def sql_json(value: Any) -> str:
    return sql_literal(json.dumps(value, ensure_ascii=False, sort_keys=True)) + "::jsonb"


def find_document(config: SupabaseConfig, document: dict[str, Any]) -> dict[str, Any] | None:
    rows = request(
        config,
        "GET",
        "kb_documents",
        query={
            "title": f"eq.{document['title']}",
            "source_type": f"eq.{document.get('source_type', '')}",
            "doc_category": f"eq.{document['doc_category']}",
            "select": "id,title,checksum",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


def find_chunk_by_source_ref(config: SupabaseConfig, source_ref: str) -> dict[str, Any] | None:
    rows = request(
        config,
        "GET",
        "kb_chunks",
        query={"source_ref": f"eq.{source_ref}", "select": "id,content_hash", "limit": "1"},
    )
    return rows[0] if rows else None


def checksum_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chunk_content_hash(chunk: dict[str, Any], document: dict[str, Any]) -> str:
    return content_hash(
        embedding_text(chunk, document),
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
    )


def embedding_text(chunk: dict[str, Any], document: dict[str, Any]) -> str:
    parts = [
        chunk.get("section_path", ""),
        chunk.get("document_type", document.get("source_type", "")),
        chunk.get("allowed_use", document.get("allowed_use", "")),
        chunk.get("chunk_text", ""),
    ]
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def content_hash(text: str, *, model: str) -> str:
    payload = f"{model}\n{' '.join(text.split())}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
