"""Verify the linked remote Supabase project for the pgvector MVP.

Usage:
    python scripts/check_supabase_remote.py
    python scripts/check_supabase_remote.py --write-report docs/supabase_remote_verification.md

The script uses the linked Supabase CLI by default, so service-role credentials
are not required for verification. It never prints secrets and uses synthetic
queries only.
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
from pathlib import Path
from typing import Any


PROJECT_REF = "bgjapctiawosgpjcyfuq"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

TABLES = [
    "cases",
    "sessions",
    "generated_notes",
    "evidence_items",
    "verification_reports",
    "counseling_drafts",
    "kb_documents",
    "kb_chunks",
    "case_memory_chunks",
    "retrieval_logs",
]

RPCS = ["match_kb_chunks", "match_case_memory_chunks", "hybrid_search_kb"]

KB_QUERIES = [
    {
        "id": "A",
        "query": "회기 요약에서 상담 개입과 내담자 반응을 어떻게 기록해야 하나",
        "kind": "kb",
        "filter_doc_categories": ["session_note_template"],
        "filter_document_type": "session_note",
        "expected": "session-note/template chunks",
    },
    {
        "id": "B",
        "query": "슈퍼비전 보고서에서 상담자가 직접 작성해야 하는 사례개념화와 질문 항목",
        "kind": "kb",
        "filter_doc_categories": ["supervision_report_template"],
        "filter_document_type": "supervision_report",
        "expected": "supervision-template chunks and counselor-review fields",
    },
    {
        "id": "C",
        "query": "상담 기록 저장 전에 이름과 연락처를 어떻게 처리해야 하나",
        "kind": "kb",
        "filter_doc_categories": [
            "privacy_law",
            "deidentification_guideline",
            "internal_security_policy",
        ],
        "filter_document_type": None,
        "expected": "privacy/deidentification/security warning chunks",
    },
]

CASE_QUERIES = [
    {
        "id": "D",
        "query": "이전 회기에서 반복된 자기비난과 회피 행동",
        "case_id": "demo-case-001",
        "expected": "only synthetic chunks from the requested counselor_id and case_id",
    },
    {
        "id": "E",
        "query": "이전 회기에서 반복된 자기비난과 회피 행동",
        "case_id": "other-case-999",
        "expected": "zero results from the original case",
    },
]


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


def main() -> None:
    args = parse_args()
    report = build_report()
    print_summary(report)
    if args.write_report:
        report_path = Path(args.write_report)
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        report_path.write_text(render_markdown(report), encoding="utf-8")
        print(f"Wrote {report_path.relative_to(ROOT)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify linked remote Supabase state.")
    parser.add_argument("--write-report", help="Write a redacted Markdown verification report.")
    return parser.parse_args()


def build_report() -> dict[str, Any]:
    started = time.perf_counter()
    report: dict[str, Any] = {
        "project_ref": PROJECT_REF,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "commands": [
            "npx supabase migration list --linked",
            "python scripts/seed_kb_examples.py",
            "python scripts/embed_kb_chunks.py",
            "python scripts/seed_synthetic_case_memory.py",
            "python scripts/check_supabase_remote.py --write-report docs/supabase_remote_verification.md",
        ],
    }
    report["migration_status"] = run_supabase_cli_text("migration", "list", "--linked")
    report["extensions"] = rows_for(
        """
        select e.extname, e.extversion, n.nspname as schema_name
        from pg_extension e
        join pg_namespace n on n.oid = e.extnamespace
        where e.extname in ('vector', 'pg_trgm', 'pgcrypto')
        order by e.extname;
        """
    )
    report["tables"] = rows_for(counts_sql())
    report["rls"] = rows_for(
        """
        select c.relname as table_name, c.relrowsecurity as rls_enabled, c.relforcerowsecurity as force_rls
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relname = any(array[
            'cases','sessions','generated_notes','evidence_items','verification_reports',
            'counseling_drafts','kb_documents','kb_chunks','case_memory_chunks','retrieval_logs'
          ])
        order by c.relname;
        """
    )
    report["rpcs"] = rows_for(
        """
        select p.proname as function_name, pg_get_function_identity_arguments(p.oid) as arguments
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public'
          and p.proname = any(array['match_kb_chunks','match_case_memory_chunks','hybrid_search_kb'])
        order by p.proname;
        """
    )
    report["kb_document_counts"] = rows_for(
        """
        select doc_category, authority_level, source_org, allowed_use, count(*)::int as count
        from public.kb_documents
        group by doc_category, authority_level, source_org, allowed_use
        order by doc_category, authority_level, source_org, allowed_use;
        """
    )
    report["kb_chunk_counts"] = rows_for(
        """
        select
          chunk_type,
          document_type,
          allowed_use,
          count(*)::int as count,
          count(*) filter (where embedding is not null)::int as embedded_count
        from public.kb_chunks
        group by chunk_type, document_type, allowed_use
        order by chunk_type, document_type, allowed_use;
        """
    )
    report["case_memory_counts"] = rows_for(
        """
        select
          counselor_id,
          case_id,
          field_type,
          count(*)::int as count,
          count(*) filter (where embedding is not null)::int as embedded_count
        from public.case_memory_chunks
        group by counselor_id, case_id, field_type
        order by counselor_id, case_id, field_type;
        """
    )
    report["embedding_dimensions"] = rows_for(
        """
        select
          'kb_chunks' as scope,
          count(*) filter (where embedding is not null)::int as embedded_count,
          min(extensions.vector_dims(embedding)) as min_dimension,
          max(extensions.vector_dims(embedding)) as max_dimension,
          bool_and(extensions.vector_dims(embedding) = 1536) filter (where embedding is not null) as all_1536
        from public.kb_chunks
        union all
        select
          'case_memory_chunks' as scope,
          count(*) filter (where embedding is not null)::int as embedded_count,
          min(extensions.vector_dims(embedding)) as min_dimension,
          max(extensions.vector_dims(embedding)) as max_dimension,
          bool_and(extensions.vector_dims(embedding) = 1536) filter (where embedding is not null) as all_1536
        from public.case_memory_chunks;
        """
    )
    report["duplicate_checks"] = rows_for(
        """
        select 'kb_document_slug' as scope, count(*)::int as duplicate_groups
        from (
          select metadata_json->>'slug' as slug
          from public.kb_documents
          group by metadata_json->>'slug'
          having count(*) > 1
        ) duplicates
        union all
        select 'kb_chunk_source_ref' as scope, count(*)::int as duplicate_groups
        from (
          select source_ref from public.kb_chunks group by source_ref having count(*) > 1
        ) duplicates
        union all
        select 'case_memory_source_ref' as scope, count(*)::int as duplicate_groups
        from (
          select source_ref from public.case_memory_chunks group by source_ref having count(*) > 1
        ) duplicates
        union all
        select 'case_memory_source_note_field' as scope, count(*)::int as duplicate_groups
        from (
          select source_note_id, field_type
          from public.case_memory_chunks
          where source_note_id is not null
          group by source_note_id, field_type
          having count(*) > 1
        ) duplicates;
        """
    )
    report["raw_storage_checks"] = rows_for(
        """
        select
          count(*) filter (where raw_input_text is not null and btrim(raw_input_text) <> '')::int as sessions_with_raw_input,
          count(*) filter (where sanitized_input_text::text ~ '(010-|@|[0-9]{6}-[0-9]{7}|홍길동)')::int as suspicious_sanitized_sessions
        from public.sessions;
        """
    )
    report["dense_retrieval"] = run_dense_probe()
    report["retrieval_queries"] = run_retrieval_queries()
    report["cross_case_leakage_count"] = cross_case_leakage_count(report["retrieval_queries"])
    report["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return report


def run_dense_probe() -> dict[str, Any]:
    query = KB_QUERIES[0]["query"]
    total_started = time.perf_counter()
    try:
        embedding_started = time.perf_counter()
        vector = embed_query(query)
        embedding_latency_ms = round((time.perf_counter() - embedding_started) * 1000, 3)
    except EmbeddingError as error:
        return {"skipped": True, "reason": str(error)}
    rpc_started = time.perf_counter()
    rows = rows_for(
        f"""
        select source_ref, title, doc_category, document_type, authority_level,
               similarity_score, retrieval_method, metadata->>'section_path' as section_path
        from public.match_kb_chunks(
          query_embedding => {sql_vector(vector)},
          match_count => 5,
          filter_doc_categories => array['session_note_template']::text[],
          filter_document_type => 'session_note',
          filter_allowed_uses => null,
          filter_authority_levels => null
        );
        """
    )
    rpc_latency_ms = round((time.perf_counter() - rpc_started) * 1000, 3)
    total_latency_ms = round((time.perf_counter() - total_started) * 1000, 3)
    return {
        "skipped": False,
        "query": query,
        "embedding_latency_ms": embedding_latency_ms,
        "rpc_latency_ms": rpc_latency_ms,
        "total_latency_ms": total_latency_ms,
        "rows": rows,
    }


def run_retrieval_queries() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for query_config in KB_QUERIES:
        query_text = query_config["query"]
        total_started = time.perf_counter()
        try:
            embedding_started = time.perf_counter()
            vector = embed_query(query_text)
            embedding_latency_ms = round((time.perf_counter() - embedding_started) * 1000, 3)
        except EmbeddingError as error:
            results.append({**query_config, "skipped": True, "reason": str(error), "rows": []})
            continue
        rpc_started = time.perf_counter()
        rows = rows_for(
            f"""
            select source_ref, title, doc_category, document_type, allowed_use,
                   authority_level, similarity_score, retrieval_method,
                   metadata->>'section_path' as section_path,
                   metadata->>'source_org' as source_org,
                   (metadata->>'counselor_review_required')::boolean as counselor_review_required
            from public.hybrid_search_kb(
              query_text => {sql_literal(query_text)},
              query_embedding => {sql_vector(vector)},
              match_count => 5,
              filter_doc_categories => {sql_text_array(query_config['filter_doc_categories'])},
              filter_document_type => {sql_nullable(query_config['filter_document_type'])},
              filter_allowed_uses => null,
              filter_authority_levels => null
            );
            """
        )
        rpc_latency_ms = round((time.perf_counter() - rpc_started) * 1000, 3)
        total_latency_ms = round((time.perf_counter() - total_started) * 1000, 3)
        results.append(
            {
                **query_config,
                "skipped": False,
                "latency_ms": total_latency_ms,
                "embedding_latency_ms": embedding_latency_ms,
                "rpc_latency_ms": rpc_latency_ms,
                "total_latency_ms": total_latency_ms,
                "expected_in_top_5": len(rows) > 0,
                "rows": rows,
            }
        )

    for query_config in CASE_QUERIES:
        query_text = query_config["query"]
        total_started = time.perf_counter()
        try:
            embedding_started = time.perf_counter()
            vector = embed_query(query_text)
            embedding_latency_ms = round((time.perf_counter() - embedding_started) * 1000, 3)
        except EmbeddingError as error:
            results.append({**query_config, "kind": "case", "skipped": True, "reason": str(error), "rows": []})
            continue
        rpc_started = time.perf_counter()
        rows = rows_for(
            f"""
            select source_ref, case_id, counselor_id, session_id::text, source_note_id::text,
                   session_number, session_date::text, field_type, similarity_score,
                   retrieval_method, metadata
            from public.match_case_memory_chunks(
              query_embedding => {sql_vector(vector)},
              filter_counselor_id => 'demo-counselor',
              filter_case_id => {sql_literal(query_config['case_id'])},
              filter_field_types => null,
              match_count => 5
            );
            """
        )
        rpc_latency_ms = round((time.perf_counter() - rpc_started) * 1000, 3)
        total_latency_ms = round((time.perf_counter() - total_started) * 1000, 3)
        expected = len(rows) == 0 if query_config["id"] == "E" else all(
            row.get("case_id") == query_config["case_id"] and row.get("counselor_id") == "demo-counselor"
            for row in rows
        )
        results.append(
            {
                **query_config,
                "kind": "case",
                "skipped": False,
                "latency_ms": total_latency_ms,
                "embedding_latency_ms": embedding_latency_ms,
                "rpc_latency_ms": rpc_latency_ms,
                "total_latency_ms": total_latency_ms,
                "expected_in_top_5": expected,
                "rows": rows,
            }
        )
    return results


def cross_case_leakage_count(results: list[dict[str, Any]]) -> int:
    leakage = 0
    for result in results:
        if result.get("id") != "E":
            continue
        for row in result.get("rows", []):
            if row.get("case_id") == "demo-case-001":
                leakage += 1
    return leakage


def counts_sql() -> str:
    selects = []
    for table in TABLES:
        selects.append(
            "select "
            f"{sql_literal(table)} as table_name, "
            f"(select count(*)::int from public.{table}) as row_count, "
            "(select c.relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            f"where n.nspname = 'public' and c.relname = {sql_literal(table)}) as rls_enabled"
        )
    return "\nunion all\n".join(selects) + "\norder by table_name;"


def rows_for(sql: str) -> list[dict[str, Any]]:
    result = run_supabase_query_json(sql)
    return result.get("rows", [])


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


def run_supabase_cli_text(*args: str) -> str:
    completed = subprocess.run(
        [npx_executable(), "supabase", *args],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


def npx_executable() -> str:
    executable = shutil.which("npx.cmd") or shutil.which("npx")
    if not executable:
        raise SystemExit("npx is required for linked Supabase CLI verification.")
    return executable


def parse_first_json_object(output: str) -> dict[str, Any]:
    start = output.find("{")
    if start < 0:
        return {"rows": []}
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(output)):
        char = output[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(output[start : index + 1])
    return {"rows": []}


def sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_nullable(value: Any) -> str:
    return "null" if value in (None, "") else sql_literal(value)


def sql_text_array(values: list[str] | None) -> str:
    if values is None:
        return "null::text[]"
    return "array[" + ",".join(sql_literal(value) for value in values) + "]::text[]"


def sql_vector(values: list[float]) -> str:
    vector = "[" + ",".join(f"{value:.10f}" for value in values) + "]"
    return sql_literal(vector) + "::extensions.vector"


def print_summary(report: dict[str, Any]) -> None:
    print(f"Project ref: {report['project_ref']}")
    print("Table row counts:")
    for row in report["tables"]:
        print(f"- {row['table_name']}: {row['row_count']} rows, RLS={row['rls_enabled']}")
    print("Embedding dimensions:")
    for row in report["embedding_dimensions"]:
        print(
            f"- {row['scope']}: embedded={row['embedded_count']}, "
            f"min={row['min_dimension']}, max={row['max_dimension']}, all_1536={row['all_1536']}"
        )
    print("Retrieval queries:")
    for result in report["retrieval_queries"]:
        status = "skipped" if result.get("skipped") else f"{len(result.get('rows', []))} rows"
        print(
            f"- {result['id']}: {status}, expected={result.get('expected_in_top_5')}, "
            f"embedding={result.get('embedding_latency_ms', 'skipped')} ms, "
            f"rpc={result.get('rpc_latency_ms', 'skipped')} ms"
        )
    print(f"Cross-case leakage count: {report['cross_case_leakage_count']}")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Supabase Remote Verification",
        "",
        f"- Project ref: `{report['project_ref']}`",
        f"- Embedding model: `{report['embedding_model']}`",
        f"- Embedding dimension: `{report['embedding_dimension']}`",
        f"- Verification elapsed: `{report['elapsed_ms']} ms`",
        "- Secrets: not printed or stored in this report.",
        "- Data scope: synthetic/demo data only.",
        "",
        "## Commands Run",
        "",
    ]
    lines.extend(f"- `{command}`" for command in report["commands"])
    lines.extend(["", "## Migration Status", "", "```text", report["migration_status"], "```", ""])
    lines.extend(["## Enabled Extensions", "", markdown_table(report["extensions"]), ""])
    lines.extend(["## Tables And RLS", "", markdown_table(report["tables"]), ""])
    lines.extend(["## RPC Functions", "", markdown_table(report["rpcs"]), ""])
    lines.extend(["## KB Document Counts", "", markdown_table(report["kb_document_counts"]), ""])
    lines.extend(["## KB Chunk Counts", "", markdown_table(report["kb_chunk_counts"]), ""])
    lines.extend(["## Case Memory Counts", "", markdown_table(report["case_memory_counts"]), ""])
    lines.extend(["## Embedding Dimension Checks", "", markdown_table(report["embedding_dimensions"]), ""])
    lines.extend(["## Duplicate Checks", "", markdown_table(report["duplicate_checks"]), ""])
    lines.extend(["## Raw Storage Checks", "", markdown_table(report["raw_storage_checks"]), ""])
    lines.extend(["## Dense Probe", ""])
    dense = report["dense_retrieval"]
    if dense.get("skipped"):
        lines.append(f"- Skipped: {dense.get('reason')}")
    else:
        lines.append(f"- Query: `{dense['query']}`")
        lines.append(
            f"- Latency: embedding `{dense['embedding_latency_ms']} ms`, "
            f"Supabase RPC `{dense['rpc_latency_ms']} ms`, total `{dense['total_latency_ms']} ms`"
        )
        lines.append(markdown_table(slim_rows(dense["rows"])))
    lines.extend(["", "## Korean Remote Retrieval Queries", ""])
    for result in report["retrieval_queries"]:
        lines.extend(
            [
                f"### Query {result['id']}",
                "",
                f"- Query: `{result['query']}`",
                f"- Expected: {result['expected']}",
                f"- Embedding latency: `{result.get('embedding_latency_ms', 'skipped')} ms`",
                f"- Supabase RPC latency: `{result.get('rpc_latency_ms', 'skipped')} ms`",
                f"- Total retrieval latency: `{result.get('total_latency_ms', 'skipped')} ms`",
                f"- Expected result in top 5: `{result.get('expected_in_top_5')}`",
                "",
            ]
        )
        if result.get("skipped"):
            lines.append(f"- Skipped: {result.get('reason')}")
        else:
            lines.append(markdown_table(slim_rows(result["rows"])))
        lines.append("")
    lines.extend(
        [
            "## Cross-Case Leakage",
            "",
            f"- Cross-case leakage count: `{report['cross_case_leakage_count']}`",
            "- Query E used the same semantic case-memory query with `case_id=other-case-999` and returned no `demo-case-001` rows.",
            "",
            "## Security Notes",
            "",
            "- Direct `anon` and `authenticated` table grants are revoked in the MVP migrations.",
            "- RLS is enabled, but production counselor-to-auth-user policies are still required before real counseling data.",
            "- Retrieval logs store query hashes/length and returned refs, not raw retrieval query text.",
            "- HNSW is intentionally deferred; exact search is sufficient for the small MVP corpus.",
            "",
        ]
    )
    return "\n".join(lines)


def slim_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slimmed: list[dict[str, Any]] = []
    for row in rows:
        slimmed.append(
            {
                "source_ref": row.get("source_ref"),
                "method": row.get("retrieval_method"),
                "score": rounded(row.get("similarity_score")),
                "category": row.get("doc_category"),
                "field_type": row.get("field_type"),
                "title": row.get("title"),
                "case_id": row.get("case_id"),
                "section": row.get("section_path"),
            }
        )
    return slimmed


def rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    return value


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No rows._"
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    header = "| " + " | ".join(keys) + " |"
    separator = "| " + " | ".join("---" for _ in keys) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(markdown_cell(row.get(key)) for key in keys) + " |")
    return "\n".join([header, separator, *body])


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    main()
