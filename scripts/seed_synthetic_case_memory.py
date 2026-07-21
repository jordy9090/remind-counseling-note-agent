"""Seed synthetic case-memory chunks for dense retrieval demos.

Usage:
    python scripts/seed_synthetic_case_memory.py

This script inserts synthetic demo data only. Do not use it for real counseling
records. Real records must not be embedded until consent, RLS, audit logging,
and retention policy are in place.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    args = parse_args()
    config = SupabaseConfig.try_from_env()
    counselor_id = os.getenv("SYNTHETIC_COUNSELOR_ID", "demo-counselor")
    case_id = os.getenv("SYNTHETIC_CASE_ID", "demo-case-001")
    session_id = seed_case_and_session(config, counselor_id, case_id, dry_run=args.dry_run)
    note_id = seed_demo_confirmed_note(config, case_id, session_id, dry_run=args.dry_run)

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
                "source_note_id": note_id,
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

    inserted = 0
    updated = 0
    for row in rows:
        existing = None if args.dry_run else find_case_memory_chunk(config, row["source_ref"])
        if existing:
            updated += 1
            if not args.dry_run:
                if config is None:
                    update_case_memory_chunk_cli(existing["id"], row)
                else:
                    request(
                        config,
                        "PATCH",
                        "case_memory_chunks",
                        query={"id": f"eq.{existing['id']}"},
                        body=row,
                        prefer="return=minimal",
                    )
        else:
            inserted += 1
            if not args.dry_run:
                if config is None:
                    insert_case_memory_chunk_cli(row)
                else:
                    request(config, "POST", "case_memory_chunks", body=[row], prefer="return=minimal")
    prefix = "Dry run:" if args.dry_run else "Seeded:"
    print(f"{prefix} {inserted} synthetic chunk(s) inserted, {updated} updated for {case_id}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed synthetic confirmed case-memory chunks.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def seed_case_and_session(config: "SupabaseConfig | None", counselor_id: str, case_id: str, *, dry_run: bool) -> str:
    if dry_run:
        return "00000000-0000-0000-0000-000000000101"
    if config is None:
        result = run_supabase_query_json(
            f"""
            insert into public.cases (id, case_alias, counselor_id, status)
            values ({sql_literal(case_id)}, {sql_literal(case_id)}, {sql_literal(counselor_id)}, 'active')
            on conflict (id) do update set case_alias = excluded.case_alias, counselor_id = excluded.counselor_id
            returning id;

            insert into public.sessions (case_id, session_number, session_date, session_title, raw_input_text, sanitized_input_text)
            values ({sql_literal(case_id)}, 1, '2026-07-17', 'Synthetic dense retrieval demo', null, '{{\"synthetic\": true}}')
            on conflict (case_id, session_number) do update set session_title = excluded.session_title
            returning id::text;
            """
        )
        rows = result.get("rows", [])
        return str(rows[-1]["id"]) if rows else "00000000-0000-0000-0000-000000000101"
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


def seed_demo_confirmed_note(config: "SupabaseConfig | None", case_id: str, session_id: str, *, dry_run: bool) -> str:
    if dry_run:
        return "00000000-0000-0000-0000-000000000102"
    if config is None:
        existing = run_supabase_query_json(
            f"""
            select id::text
            from public.generated_notes
            where case_id = {sql_literal(case_id)}
              and session_id = {sql_literal(session_id)}::uuid
              and note_type = 'session_note'
              and confirmation_status = 'demo_confirmed'
            limit 1;
            """
        ).get("rows", [])
        if existing:
            return str(existing[0]["id"])
        sections = {chunk["field_type"]: chunk["chunk_text"] for chunk in SYNTHETIC_CHUNKS}
        inserted = run_supabase_query_json(
            f"""
            insert into public.generated_notes (
              case_id, session_id, note_type, draft_json, confirmed_json,
              counselor_edited, confirmation_status, confirmed_by, confirmed_at
            )
            values (
              {sql_literal(case_id)},
              {sql_literal(session_id)}::uuid,
              'session_note',
              '{{\"synthetic\": true}}'::jsonb,
              {sql_json({'sections': sections})},
              true,
              'demo_confirmed',
              'synthetic_seed',
              '2026-07-17T00:00:00+00:00'
            )
            returning id::text;
            """
        ).get("rows", [])
        return str(inserted[0]["id"])
    existing = request(
        config,
        "GET",
        "generated_notes",
        query={
            "case_id": f"eq.{case_id}",
            "session_id": f"eq.{session_id}",
            "note_type": "eq.session_note",
            "confirmation_status": "eq.demo_confirmed",
            "select": "id",
            "limit": "1",
        },
    )
    if existing:
        return str(existing[0]["id"])
    rows = request(
        config,
        "POST",
        "generated_notes",
        body=[
            {
                "case_id": case_id,
                "session_id": session_id,
                "note_type": "session_note",
                "draft_json": {"synthetic": True},
                "confirmed_json": {"sections": {chunk["field_type"]: chunk["chunk_text"] for chunk in SYNTHETIC_CHUNKS}},
                "counselor_edited": True,
                "confirmation_status": "demo_confirmed",
                "confirmed_by": "synthetic_seed",
                "confirmed_at": "2026-07-17T00:00:00+00:00",
            }
        ],
        prefer="return=representation",
    )
    return str(rows[0]["id"])


def find_case_memory_chunk(config: "SupabaseConfig | None", source_ref: str) -> dict[str, Any] | None:
    if config is None:
        rows = run_supabase_query_json(
            f"select id::text, content_hash from public.case_memory_chunks where source_ref = {sql_literal(source_ref)} limit 1;"
        ).get("rows", [])
        return rows[0] if rows else None
    rows = request(
        config,
        "GET",
        "case_memory_chunks",
        query={"source_ref": f"eq.{source_ref}", "select": "id,content_hash", "limit": "1"},
    )
    return rows[0] if rows else None


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


def insert_case_memory_chunk_cli(row: dict[str, Any]) -> None:
    run_supabase_sql(case_memory_insert_sql(row))


def update_case_memory_chunk_cli(chunk_id: str, row: dict[str, Any]) -> None:
    run_supabase_sql(case_memory_update_sql(chunk_id, row))


def case_memory_insert_sql(row: dict[str, Any]) -> str:
    return f"""
    insert into public.case_memory_chunks (
      counselor_id, case_id, session_id, source_note_id, session_number, session_date,
      field_type, chunk_text, source_ref, metadata_json, embedding, embedding_model, content_hash
    )
    values (
      {sql_literal(row['counselor_id'])},
      {sql_literal(row['case_id'])},
      {sql_literal(row['session_id'])}::uuid,
      {sql_literal(row['source_note_id'])}::uuid,
      {int(row['session_number'])},
      {sql_literal(row['session_date'])},
      {sql_literal(row['field_type'])},
      {sql_literal(row['chunk_text'])},
      {sql_literal(row['source_ref'])},
      {sql_json(row['metadata_json'])},
      {sql_vector(row['embedding'])},
      {sql_literal(row['embedding_model'])},
      {sql_literal(row['content_hash'])}
    );
    """


def case_memory_update_sql(chunk_id: str, row: dict[str, Any]) -> str:
    return f"""
    update public.case_memory_chunks
    set counselor_id = {sql_literal(row['counselor_id'])},
        case_id = {sql_literal(row['case_id'])},
        session_id = {sql_literal(row['session_id'])}::uuid,
        source_note_id = {sql_literal(row['source_note_id'])}::uuid,
        session_number = {int(row['session_number'])},
        session_date = {sql_literal(row['session_date'])},
        field_type = {sql_literal(row['field_type'])},
        chunk_text = {sql_literal(row['chunk_text'])},
        metadata_json = {sql_json(row['metadata_json'])},
        embedding = {sql_vector(row['embedding'])},
        embedding_model = {sql_literal(row['embedding_model'])},
        content_hash = {sql_literal(row['content_hash'])}
    where id = {sql_literal(chunk_id)}::uuid;
    """


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


def sql_json(value: Any) -> str:
    return sql_literal(json.dumps(value, ensure_ascii=False, sort_keys=True)) + "::jsonb"


def sql_vector(values: list[float]) -> str:
    return sql_literal("[" + ",".join(f"{value:.10f}" for value in values) + "]") + "::extensions.vector"


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

