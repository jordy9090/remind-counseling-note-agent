"""Local-only inspector for the current case-history retrieval behavior.

This script deliberately calls the production retrieval service without changing
the graph or API. It prints deidentified query/results and writes review artifacts.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.nodes import sanitize_input  # noqa: E402
from app.schemas.note import SessionInput  # noqa: E402
from app.services.deidentification import deidentify_text  # noqa: E402
from app.services.retrieval import (  # noqa: E402
    RetrievalChunk,
    retrieval_query_from_input,
    retrieve_case_context,
    retrieve_case_memory_chunks,
)


DEFAULT_INPUT = REPO_ROOT / "tests" / "fixtures" / "legacy" / "session_input_005_synthetic.json"
COLUMNS = (
    "rank", "session_number", "session_date", "field_type", "similarity_score",
    "retrieval_method", "source_ref", "chunk_text",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect current case-memory top-k retrieval (local/debug only).")
    parser.add_argument("--case-id", required=True, help="Case boundary passed to the existing retrieval service.")
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help=f"Current-session JSON (default synthetic fixture: {DEFAULT_INPUT.relative_to(REPO_ROOT)}).",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Requested dense result count (current RPC caps this at 5).")
    parser.add_argument("--compare-recent", action="store_true", help="Also print the current recent-3 fallback.")
    parser.add_argument(
        "--output-dir", type=Path, default=REPO_ROOT / "results" / "debug",
        help="Directory for JSON and Markdown review artifacts.",
    )
    return parser.parse_args(argv)


def load_session_input(path: Path, case_id: str) -> SessionInput:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["case_id"] = case_id
    return SessionInput.model_validate(payload)


def build_query(session_input: SessionInput) -> str:
    sanitized = sanitize_input({"session_input": session_input})["sanitized_input"]
    query = retrieval_query_from_input(session_input.target_document_type, sanitized.sources)
    # Defense in depth for debug output; the graph input has already been deidentified.
    return deidentify_text(query, source="retrieval_query")[0]


def dense_rows(chunks: list[RetrievalChunk]) -> list[dict[str, Any]]:
    return [
        {
            "rank": rank,
            "session_number": chunk.session_number,
            "session_date": chunk.session_date,
            "field_type": chunk.field_type,
            "similarity_score": chunk.similarity_score,
            "retrieval_method": chunk.retrieval_method,
            "source_ref": chunk.source_ref,
            "chunk_text": deidentify_text(chunk.chunk_text, source=chunk.source_ref)[0],
        }
        for rank, chunk in enumerate(chunks, 1)
    ]


def recent_rows(context: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(context, 1):
        text = item.summary or json.dumps(item.confirmed_note, ensure_ascii=False)
        rows.append(
            {
                "rank": rank,
                "session_number": item.session_number,
                "session_date": item.session_date,
                "field_type": "confirmed_session_note",
                "similarity_score": None,
                "retrieval_method": "recent_3_fallback",
                "source_ref": item.source_ref,
                "chunk_text": deidentify_text(text, source=item.source_ref)[0],
            }
        )
    return rows


def print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n{title}")
    print("\t".join(COLUMNS))
    for row in rows:
        values = [row.get(column) for column in COLUMNS]
        print("\t".join("" if value is None else str(value).replace("\t", " ").replace("\n", " ") for value in values))
    if not rows:
        print("(no results)")


def artifact_payload(query: str, case_id: str, dense: list[dict[str, Any]], recent: list[dict[str, Any]]) -> dict[str, Any]:
    def external(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["score"] = result.pop("similarity_score")
        result["text"] = result.pop("chunk_text")
        return result

    payload: dict[str, Any] = {"query": query, "case_id": case_id, "results": [external(row) for row in dense]}
    if recent:
        payload["recent_3"] = [external(row) for row in recent]
    return payload


def markdown_review(query: str, case_id: str, dense: list[dict[str, Any]], recent: list[dict[str, Any]]) -> str:
    lines = [
        "# Case retrieval human review", "", f"- Case ID: `{case_id}`", f"- Query: `{query}`", "",
    ]
    groups = [("Dense top-k", dense)] + ([("Recent-3 fallback", recent)] if recent else [])
    for title, rows in groups:
        lines.extend([
            f"## {title}", "",
            "| Rank | Session | Field | Score | Evidence | Human label | Note |",
            "|---|---|---|---:|---|---|---|",
        ])
        for row in rows:
            evidence = str(row["chunk_text"]).replace("|", "\\|").replace("\n", "<br>")
            score = "" if row["similarity_score"] is None else f'{row["similarity_score"]:.6f}'
            lines.append(f'| {row["rank"]} | {row["session_number"] or ""} | {row["field_type"]} | {score} | {evidence} | GOOD / PARTIAL / BAD | |')
        if not rows:
            lines.append("| - | - | - | - | No results | GOOD / PARTIAL / BAD | |")
        lines.append("")
    return "\n".join(lines)


def write_artifacts(output_dir: Path, query: str, case_id: str, dense: list[dict[str, Any]], recent: list[dict[str, Any]]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"retrieval_topk_{timestamp}.json"
    md_path = output_dir / f"retrieval_topk_{timestamp}_review.md"
    json_path.write_text(json.dumps(artifact_payload(query, case_id, dense, recent), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_review(query, case_id, dense, recent), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.top_k < 1:
        raise SystemExit("--top-k must be at least 1")
    session_input = load_session_input(args.input, args.case_id)
    query = build_query(session_input)
    print(f"retrieval_query (deidentified): {query}")

    from app.core.config import settings
    chunks = retrieve_case_memory_chunks(
        query_text=query, counselor_id=settings.remind_preview_actor, case_id=args.case_id, max_chunks=args.top_k,
    )
    dense = dense_rows(chunks)
    recent = recent_rows(retrieve_case_context(args.case_id, max_sessions=3)) if args.compare_recent else []
    print_table(f"A. dense top-{args.top_k} (RPC maximum: 5)", dense)
    if args.compare_recent:
        print_table("B. recent-3 fallback", recent)
    json_path, md_path = write_artifacts(args.output_dir, query, args.case_id, dense, recent)
    print(f"\nJSON: {json_path}")
    print(f"Review template: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
