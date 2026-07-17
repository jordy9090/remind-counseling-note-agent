"""Run a small synthetic retrieval evaluation.

Default mode uses mock results, so it needs no Supabase or OpenAI credentials.
It reports Recall@5, MRR, cross-case leakage count, latency, and source-ref
coverage for the retrieval result contract.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "docs" / "retrieval_eval_synthetic.json"

MOCK_RESULTS: dict[str, list[dict[str, Any]]] = {
    "kb-session-template": [
        {
            "source_ref": "kb:session-note-template-v1:1",
            "doc_category": "session_note_template",
            "field_type": None,
            "case_id": None,
            "similarity_score": 0.91,
        }
    ],
    "kb-privacy-warning": [
        {
            "source_ref": "kb:privacy-law-sensitive-info-demo:1",
            "doc_category": "privacy_law",
            "field_type": None,
            "case_id": None,
            "similarity_score": 0.88,
        }
    ],
    "case-memory-next-plan": [
        {
            "source_ref": "synthetic_case_memory:demo-case-001:1:3",
            "doc_category": None,
            "field_type": "next_plan",
            "case_id": "demo-case-001",
            "similarity_score": 0.84,
        }
    ],
}


def main() -> None:
    items = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["items"]
    started = time.perf_counter()
    reciprocal_ranks: list[float] = []
    recall_hits = 0
    leakage_count = 0
    result_count = 0
    valid_source_ref_count = 0

    for item in items:
        results = MOCK_RESULTS.get(item["id"], [])[:5]
        result_count += len(results)
        valid_source_ref_count += sum(1 for result in results if result.get("source_ref"))
        rank = first_expected_rank(item, results)
        if rank is not None:
            recall_hits += 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)
        leakage_count += count_cross_case_leaks(item, results)

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    print(json.dumps(
        {
            "Recall@5": recall_hits / len(items),
            "MRR": sum(reciprocal_ranks) / len(reciprocal_ranks),
            "cross_case_leakage_count": leakage_count,
            "retrieval_latency_ms": latency_ms,
            "valid_source_ref_percentage": (
                valid_source_ref_count / result_count if result_count else 0.0
            ),
        },
        indent=2,
    ))


def first_expected_rank(item: dict[str, Any], results: list[dict[str, Any]]) -> int | None:
    for index, result in enumerate(results, start=1):
        if result.get("source_ref") != item.get("expected_source_ref"):
            continue
        expected_category = item.get("expected_document_category")
        expected_field = item.get("expected_field_type")
        if expected_category and result.get("doc_category") != expected_category:
            continue
        if expected_field and result.get("field_type") != expected_field:
            continue
        return index
    return None


def count_cross_case_leaks(item: dict[str, Any], results: list[dict[str, Any]]) -> int:
    expected_case_id = item.get("case_id")
    forbidden = set(item.get("forbidden_case_ids") or [])
    leaks = 0
    for result in results:
        case_id = result.get("case_id")
        if case_id in forbidden:
            leaks += 1
        elif expected_case_id and case_id and case_id != expected_case_id:
            leaks += 1
    return leaks


if __name__ == "__main__":
    main()

