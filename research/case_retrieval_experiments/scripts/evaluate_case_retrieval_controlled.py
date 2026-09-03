"""Run a production-free controlled evaluation of current case-memory dense retrieval."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
for import_root in (REPO_ROOT, BACKEND_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.core.config import settings  # noqa: E402
from app.schemas.note import ConfirmGeneratedNoteRequest  # noqa: E402
from app.services import retrieval, supabase_storage  # noqa: E402
from app.services.deidentification import deidentify_text  # noqa: E402
from app.services.embeddings import EmbeddingError, clear_embedding_cache  # noqa: E402
from research.case_retrieval_experiments.scripts.inspect_case_retrieval import dense_rows  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
DEFAULT_CORPUS = FIXTURE_DIR / "case_retrieval_controlled_corpus.json"
DEFAULT_QUERIES = FIXTURE_DIR / "case_retrieval_controlled_queries.json"
DEFAULT_OUTPUT = REPO_ROOT / "results" / "debug" / "controlled_case_retrieval"


class LocalEvaluationStorage:
    """Minimal in-memory Supabase substitute; no network or production writes."""

    def __init__(self, corpus: dict[str, Any]) -> None:
        self.case_id = corpus["case_id"]
        self.actor = corpus["actor"]
        self.cases = [{"id": self.case_id, "case_alias": self.case_id, "counselor_id": self.actor, "user_id": self.actor, "status": "synthetic"}]
        self.sessions: list[dict[str, Any]] = []
        self.generated_notes: list[dict[str, Any]] = []
        self.case_memory_chunks: list[dict[str, Any]] = []
        self.retrieval_logs: list[dict[str, Any]] = []
        for session in corpus["sessions"]:
            number = int(session["session_number"])
            session_id, note_id = f"synthetic-session-{number}", f"synthetic-note-{number}"
            self.sessions.append({
                "id": session_id, "case_id": self.case_id, "session_number": number,
                "session_date": session["session_date"], "session_title": session["stage"], "user_id": self.actor,
                "created_at": f'{session["session_date"]}T00:00:00Z',
            })
            self.generated_notes.append({
                "id": note_id, "case_id": self.case_id, "session_id": session_id, "note_type": "session_note",
                "draft_json": {"synthetic": True}, "confirmed_json": {}, "confirmation_status": "draft",
                "confirmed_by": None, "user_id": self.actor, "created_at": f'{session["session_date"]}T00:00:00Z',
            })

    @property
    def retrieval_enabled(self) -> bool:
        return True

    def maybe_single(self, table: str, query: dict[str, str | int]) -> dict[str, Any] | None:
        rows = self.select(table, query)
        return rows[0] if rows else None

    def select(self, table: str, query: dict[str, str | int]) -> list[dict[str, Any]]:
        source = {
            "cases": self.cases, "sessions": self.sessions, "generated_notes": self.generated_notes,
            "case_memory_chunks": self.case_memory_chunks, "evidence_items": [],
        }.get(table, [])
        rows = list(source)
        for key, condition in query.items():
            if key in {"select", "order", "limit"}:
                continue
            value = str(condition)
            if value.startswith("eq."):
                rows = [row for row in rows if str(row.get(key) or "") == value[3:]]
            elif value.startswith("neq."):
                rows = [row for row in rows if str(row.get(key) or "") != value[4:]]
            elif value.startswith("in.("):
                allowed = set(value[4:-1].split(","))
                rows = [row for row in rows if str(row.get(key) or "") in allowed]
        order = str(query.get("order") or "")
        if order.startswith("session_number.desc"):
            rows.sort(key=lambda row: (int(row.get("session_number") or 0), str(row.get("created_at") or "")), reverse=True)
        elif order.startswith("created_at.desc"):
            rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows[: int(query.get("limit") or len(rows))]

    def update(self, table: str, values: dict[str, Any], *, query: dict[str, str | int], return_representation: bool = True) -> list[dict[str, Any]]:
        rows = self.select(table, query)
        for row in rows:
            row.update(values)
        return rows if return_representation else []

    def upsert(self, table: str, rows: list[dict[str, Any]], *, on_conflict: str) -> list[dict[str, Any]]:
        if table != "case_memory_chunks" or on_conflict != "source_note_id,field_type":
            raise AssertionError("Controlled evaluation only permits case-memory upserts.")
        stored: list[dict[str, Any]] = []
        for incoming in rows:
            existing = next((row for row in self.case_memory_chunks if row["source_note_id"] == incoming["source_note_id"] and row["field_type"] == incoming["field_type"]), None)
            if existing is None:
                existing = {"id": f"synthetic-chunk-{len(self.case_memory_chunks) + 1}", "created_at": datetime.now(UTC).isoformat(), **incoming}
                self.case_memory_chunks.append(existing)
            else:
                existing.update(incoming)
            stored.append(existing)
        return stored

    def insert(self, table: str, rows: list[dict[str, Any]], **_: Any) -> list[dict[str, Any]]:
        if table != "retrieval_logs":
            raise AssertionError("Controlled evaluation only permits retrieval log inserts.")
        self.retrieval_logs.extend(rows)
        return rows

    def rpc(self, function_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if function_name == "log_retrieval_event":
            return []
        if function_name != "match_case_memory_chunks":
            raise AssertionError(f"Unexpected RPC: {function_name}")
        query_vector = params["query_embedding"]
        allowed_fields = params.get("filter_field_types")
        candidates = [
            row for row in self.case_memory_chunks
            if row["counselor_id"] == params["filter_counselor_id"]
            and row["case_id"] == params["filter_case_id"]
            and row.get("embedding")
            and (not allowed_fields or row["field_type"] in allowed_fields)
        ]
        for row in candidates:
            row["_score"] = cosine_similarity(row["embedding"], query_vector)
        candidates.sort(key=lambda row: (row["_score"], int(row.get("session_number") or 0), str(row.get("created_at") or "")), reverse=True)
        limit = min(max(int(params.get("match_count") or 5), 1), 5)
        return [{
            **row, "chunk_id": row["id"], "similarity_score": row["_score"],
            "retrieval_method": "case_memory_dense", "metadata": row.get("metadata_json") or {},
        } for row in candidates[:limit]]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return numerator / (left_norm * right_norm)


@contextmanager
def local_test_mode(storage: LocalEvaluationStorage) -> Iterator[None]:
    original_storage = supabase_storage.storage, retrieval.storage
    setting_names = (
        "enable_persistence", "enable_case_memory", "enable_rag", "enable_dense_retrieval",
        "supabase_url", "supabase_service_role_key",
    )
    originals = {name: getattr(settings, name) for name in setting_names}
    try:
        settings.enable_persistence = True
        settings.enable_case_memory = True
        settings.enable_rag = True
        settings.enable_dense_retrieval = True
        settings.supabase_url = "http://synthetic-local.invalid"
        settings.supabase_service_role_key = "synthetic-local-key"
        supabase_storage.storage = storage
        retrieval.storage = storage
        clear_embedding_cache()
        yield
    finally:
        supabase_storage.storage, retrieval.storage = original_storage
        for name, value in originals.items():
            setattr(settings, name, value)
        clear_embedding_cache()


def index_corpus(corpus: dict[str, Any], storage: LocalEvaluationStorage) -> list[dict[str, Any]]:
    reports = []
    by_number = {int(item["session_number"]): item for item in corpus["sessions"]}
    for note in storage.generated_notes:
        session = next(row for row in storage.sessions if row["id"] == note["session_id"])
        source = by_number[int(session["session_number"])]
        response = supabase_storage.confirm_generated_note(
            ConfirmGeneratedNoteRequest(
                note_id=note["id"], confirmed_note={"sections": source["sections"]},
                counselor_edited=True, create_case_memory=True,
            ),
            actor=storage.actor,
        )
        reports.append(response.model_dump(mode="json"))
    return reports


def metrics(rows: list[dict[str, Any]], expected: list[int]) -> dict[str, Any]:
    sessions = [int(row["session_number"]) for row in rows if row["session_number"] is not None]
    unique_sessions = sorted(set(sessions))
    retrieved_relevant = sorted(set(expected) & set(sessions))
    return {
        "hit_at_5": bool(retrieved_relevant),
        "relevant_session_recall_at_5": len(retrieved_relevant) / len(expected) if expected else None,
        "retrieved_relevant_sessions": retrieved_relevant,
        "unique_sessions_at_5": len(unique_sessions),
        "same_session_redundancy": (len(sessions) - len(unique_sessions)) / len(sessions) if sessions else 0.0,
        "field_distribution": dict(Counter(str(row["field_type"]) for row in rows)),
    }


def review_markdown(query: dict[str, Any], rows: list[dict[str, Any]], query_metrics: dict[str, Any]) -> str:
    lines = [
        f'# Human review: {query["id"]}', "", f'- Query: {query["query"]}',
        f'- Expected relevant sessions: {query["expected_relevant_sessions"]}',
        f'- Automated diagnostics: `{json.dumps(query_metrics, ensure_ascii=False)}`', "",
        "GOOD: 판단에 실제 필요한 과거 정보 · PARTIAL: 관련 있으나 일반적/중복 · BAD: 불필요하거나 잘못된 근거", "",
        "| Rank | Session | Field | Score | Evidence | Human label | Note |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in rows:
        evidence = str(row["chunk_text"]).replace("|", "\\|").replace("\n", "<br>")
        lines.append(f'| {row["rank"]} | {row["session_number"]} | {row["field_type"]} | {row["similarity_score"]:.6f} | {evidence} | GOOD / PARTIAL / BAD | |')
    return "\n".join(lines) + "\n"


def run(corpus_path: Path, queries_path: Path, output_dir: Path) -> dict[str, Any]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    queries = json.loads(queries_path.read_text(encoding="utf-8"))["queries"]
    storage = LocalEvaluationStorage(corpus)
    output_dir.mkdir(parents=True, exist_ok=True)
    with local_test_mode(storage):
        index_reports = index_corpus(corpus, storage)
        if len(storage.case_memory_chunks) != len(corpus["sessions"]) * 7:
            raise RuntimeError(f'Expected {len(corpus["sessions"]) * 7} indexed chunks, got {len(storage.case_memory_chunks)}')
        evaluations = []
        for query in queries:
            safe_query = deidentify_text(query["query"], source=query["id"])[0]
            chunks = retrieval.retrieve_case_memory_chunks(
                query_text=safe_query, counselor_id=storage.actor, case_id=storage.case_id, max_chunks=5,
            )
            rows = dense_rows(chunks)
            query_metrics = metrics(rows, query["expected_relevant_sessions"])
            recent_sessions = [8, 7, 6]
            recent_relevant = sorted(set(recent_sessions) & set(query["expected_relevant_sessions"]))
            comparison = {
                "recent_3_hit": bool(recent_relevant),
                "recent_3_recall": len(recent_relevant) / len(query["expected_relevant_sessions"]),
                "recent_3_relevant_sessions": recent_relevant,
            }
            evaluation = {**query, "results": rows, "metrics": query_metrics, "recent_3_comparison": comparison}
            evaluations.append(evaluation)
            (output_dir / f'{query["id"]}.json').write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
            (output_dir / f'{query["id"]}_review.md').write_text(review_markdown(query, rows, query_metrics), encoding="utf-8")

    aggregate = {
        "query_count": len(evaluations),
        "mean_hit_at_5": sum(item["metrics"]["hit_at_5"] for item in evaluations) / len(evaluations),
        "mean_relevant_session_recall_at_5": sum(item["metrics"]["relevant_session_recall_at_5"] for item in evaluations) / len(evaluations),
        "mean_unique_sessions_at_5": sum(item["metrics"]["unique_sessions_at_5"] for item in evaluations) / len(evaluations),
        "mean_same_session_redundancy": sum(item["metrics"]["same_session_redundancy"] for item in evaluations) / len(evaluations),
        "field_distribution": dict(Counter(row["field_type"] for item in evaluations for row in item["results"])),
        "recent_3_mean_hit": sum(item["recent_3_comparison"]["recent_3_hit"] for item in evaluations) / len(evaluations),
        "recent_3_mean_recall": sum(item["recent_3_comparison"]["recent_3_recall"] for item in evaluations) / len(evaluations),
    }
    report = {
        "description": corpus["description"], "case_id": corpus["case_id"],
        "embedding_model": settings.embedding_model, "session_count": len(corpus["sessions"]),
        "indexed_chunk_count": len(storage.case_memory_chunks), "index_reports": index_reports,
        "aggregate": aggregate, "evaluations": evaluations,
    }
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    print(f"Artifacts: {output_dir}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        run(args.corpus, args.queries, args.output_dir)
    except EmbeddingError as error:
        raise SystemExit(f"Controlled evaluation requires the currently configured dense embedding provider: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
