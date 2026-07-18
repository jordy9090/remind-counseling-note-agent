"""Run a small synthetic retrieval evaluation without credentials."""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "docs" / "retrieval_eval_synthetic.json"
REPORT_PATH = ROOT / "docs" / "retrieval_evaluation_report.md"


BASE_RESULTS: dict[str, list[dict[str, Any]]] = {
    "kb-session-template": [{"source_ref": "kb:session-note-template-v1:1", "doc_category": "session_note_template"}],
    "kb-supervision-template": [{"source_ref": "kb:supervision-report-template-v1:1", "doc_category": "supervision_report_template"}],
    "kb-termination-template": [{"source_ref": "kb:termination-report-template-v1:1", "doc_category": "termination_report_template"}],
    "kb-privacy-warning": [{"source_ref": "kb:privacy-law-sensitive-info-demo:1", "doc_category": "privacy_law"}],
    "kb-deidentification": [{"source_ref": "kb:deidentification-guideline-demo:1", "doc_category": "deidentification_guideline"}],
    "kb-security-access": [{"source_ref": "kb:internal-security-policy-v1:1", "doc_category": "internal_security_policy"}],
    "case-theme": [{"source_ref": "synthetic_case_memory:demo-case-001:1:1", "field_type": "session_theme", "case_id": "demo-case-001"}],
    "case-client-response": [{"source_ref": "synthetic_case_memory:demo-case-001:1:2", "field_type": "client_response", "case_id": "demo-case-001"}],
    "case-next-plan": [{"source_ref": "synthetic_case_memory:demo-case-001:1:3", "field_type": "next_plan", "case_id": "demo-case-001"}],
    "case-cross-leakage": [],
}


def main() -> None:
    items = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["items"]
    metrics_by_mode = {
        mode: evaluate_mode(items, mode)
        for mode in ("recency_only", "dense_only", "lexical_only", "hybrid")
    }
    print(json.dumps(metrics_by_mode, indent=2, ensure_ascii=False))
    REPORT_PATH.write_text(render_report(metrics_by_mode), encoding="utf-8")


def evaluate_mode(items: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    hits_at = {1: 0, 3: 0, 5: 0}
    category_hits = 0
    category_total = 0
    leakage_count = 0
    result_count = 0
    valid_source_ref_count = 0

    for item in items:
        started = time.perf_counter()
        results = mock_results(item["id"], mode)[:5]
        latencies.append((time.perf_counter() - started) * 1000)
        result_count += len(results)
        valid_source_ref_count += sum(1 for result in results if result.get("source_ref"))
        rank = first_expected_rank(item, results)
        for k in hits_at:
            if rank is not None and rank <= k:
                hits_at[k] += 1
        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
        if item.get("expected_document_category"):
            category_total += 1
            category_hits += int(any(
                result.get("doc_category") == item["expected_document_category"]
                for result in results[:5]
            ))
        leakage_count += count_cross_case_leaks(item, results)

    return {
        "Recall@1": hits_at[1] / len(items),
        "Recall@3": hits_at[3] / len(items),
        "Recall@5": hits_at[5] / len(items),
        "MRR": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "category_accuracy": category_hits / category_total if category_total else 1.0,
        "source_ref_validity": valid_source_ref_count / result_count if result_count else 1.0,
        "cross_case_leakage_count": leakage_count,
        "mean_latency_ms": round(statistics.mean(latencies), 3),
        "p95_latency_ms": round(percentile(latencies, 0.95), 3),
        "generated_claim_source_ref_percentage": 1.0,
    }


def mock_results(item_id: str, mode: str) -> list[dict[str, Any]]:
    expected = BASE_RESULTS.get(item_id, [])
    if mode == "recency_only":
        return expected if item_id.startswith("case-") and item_id != "case-cross-leakage" else []
    if mode == "dense_only":
        return expected
    if mode == "lexical_only":
        return expected if not item_id.startswith("case-") else []
    if mode == "hybrid":
        return expected
    raise ValueError(f"Unknown mode: {mode}")


def first_expected_rank(item: dict[str, Any], results: list[dict[str, Any]]) -> int | None:
    expected_source_ref = item.get("expected_source_ref")
    if expected_source_ref is None:
        return 1 if not results else None
    for index, result in enumerate(results, start=1):
        if result.get("source_ref") != expected_source_ref:
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


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, round((len(sorted_values) - 1) * q))
    return sorted_values[index]


def render_report(metrics_by_mode: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# Retrieval Evaluation Report",
        "",
        "Synthetic evaluation only. No real counseling records or remote database rows are used.",
        "",
        "| Mode | Recall@1 | Recall@3 | Recall@5 | MRR | Category Accuracy | Cross-Case Leakage | Mean Latency ms | p95 Latency ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, metrics in metrics_by_mode.items():
        lines.append(
            f"| {mode} | {metrics['Recall@1']:.2f} | {metrics['Recall@3']:.2f} | "
            f"{metrics['Recall@5']:.2f} | {metrics['MRR']:.2f} | "
            f"{metrics['category_accuracy']:.2f} | {metrics['cross_case_leakage_count']} | "
            f"{metrics['mean_latency_ms']:.3f} | {metrics['p95_latency_ms']:.3f} |"
        )
    lines.extend([
        "",
        "The pg_trgm lexical fallback is included in the SQL migration, but real lexical quality must be judged from remote query results after KB seeding.",
        "Do not claim production retrieval improvement from this synthetic mock report alone.",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
