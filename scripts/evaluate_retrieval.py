"""Run a synthetic Korean retrieval evaluation without credentials.

This is a mock evaluation for regression checks only. It validates metric
calculation and retrieval boundaries, not production retrieval quality.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "docs" / "retrieval_eval_synthetic.json"
REPORT_PATH = ROOT / "docs" / "retrieval_evaluation_report.md"
MODES = ("recency_only", "dense_only", "lexical_only", "hybrid")


def main() -> None:
    items = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["items"]
    metrics_by_mode = {mode: evaluate_mode(items, mode) for mode in MODES}
    print(json.dumps(metrics_by_mode, indent=2, ensure_ascii=False))
    REPORT_PATH.write_text(render_report(items, metrics_by_mode), encoding="utf-8")


def evaluate_mode(items: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    reciprocal_ranks: list[float] = []
    embedding_latencies: list[float] = []
    rpc_latencies: list[float] = []
    total_latencies: list[float] = []
    hits_at = {1: 0, 3: 0, 5: 0}
    category_hits = 0
    category_total = 0
    leakage_count = 0
    result_count = 0
    valid_source_ref_count = 0

    for item in items:
        results = mock_results(item, mode)[:5]
        timing = mock_latency(item, mode)
        embedding_latencies.append(timing["embedding_latency_ms"])
        rpc_latencies.append(timing["rpc_latency_ms"])
        total_latencies.append(timing["total_latency_ms"])
        result_count += len(results)
        valid_source_ref_count += sum(1 for result in results if valid_source_ref(result))

        rank = first_expected_rank(item, results)
        for k in hits_at:
            if rank is not None and rank <= k:
                hits_at[k] += 1
        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)

        if item.get("expected_document_category"):
            category_total += 1
            category_hits += int(
                any(result.get("doc_category") == item["expected_document_category"] for result in results[:5])
            )
        leakage_count += count_cross_case_leaks(item, results)

    return {
        "query_count": len(items),
        "Recall@1": hits_at[1] / len(items),
        "Recall@3": hits_at[3] / len(items),
        "Recall@5": hits_at[5] / len(items),
        "MRR": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "category_accuracy": category_hits / category_total if category_total else 1.0,
        "source_ref_validity": valid_source_ref_count / result_count if result_count else 1.0,
        "cross_case_leakage_count": leakage_count,
        "mean_embedding_latency_ms": round(statistics.mean(embedding_latencies), 3),
        "p95_embedding_latency_ms": round(percentile(embedding_latencies, 0.95), 3),
        "mean_rpc_latency_ms": round(statistics.mean(rpc_latencies), 3),
        "p95_rpc_latency_ms": round(percentile(rpc_latencies, 0.95), 3),
        "mean_total_latency_ms": round(statistics.mean(total_latencies), 3),
        "p95_total_latency_ms": round(percentile(total_latencies, 0.95), 3),
    }


def mock_results(item: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    expected_ref = item.get("expected_source_ref")
    if expected_ref is None:
        return []
    if mode == "recency_only" and not str(expected_ref).startswith("synthetic_case_memory:"):
        return []
    if mode == "lexical_only" and not item.get("lexical_supported"):
        return []
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")

    expected = {
        "source_ref": expected_ref,
        "doc_category": item.get("expected_document_category"),
        "field_type": item.get("expected_field_type"),
        "case_id": item.get("case_id"),
    }
    return [expected, *distractors_for(item, mode)]


def distractors_for(item: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if mode == "recency_only":
        return []
    category = item.get("expected_document_category")
    if category == "supervision_report_template":
        return [{"source_ref": "kb:termination-report-template-v1:1", "doc_category": "termination_report_template"}]
    if category == "termination_report_template":
        return [{"source_ref": "kb:supervision-report-template-v1:1", "doc_category": "supervision_report_template"}]
    if category == "privacy_law":
        return [{"source_ref": "kb:counseling-ethics-confidentiality-demo:1", "doc_category": "counseling_ethics"}]
    if category == "counseling_ethics":
        return [{"source_ref": "kb:privacy-law-sensitive-info-demo:1", "doc_category": "privacy_law"}]
    if str(item.get("expected_source_ref") or "").startswith("synthetic_case_memory:"):
        return [{"source_ref": "synthetic_case_memory:demo-case-001:1:99", "case_id": item.get("case_id")}]
    return []


def mock_latency(item: dict[str, Any], mode: str) -> dict[str, float]:
    seed = int(hashlib.sha256(f"{mode}:{item['id']}".encode("utf-8")).hexdigest()[:8], 16)
    rpc_latency_ms = 2.0 + (seed % 37) / 10
    embedding_latency_ms = 0.0 if mode in {"recency_only", "lexical_only"} else 12.0 + (seed % 53) / 10
    total_latency_ms = embedding_latency_ms + rpc_latency_ms + 0.4
    return {
        "embedding_latency_ms": round(embedding_latency_ms, 3),
        "rpc_latency_ms": round(rpc_latency_ms, 3),
        "total_latency_ms": round(total_latency_ms, 3),
    }


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


def valid_source_ref(result: dict[str, Any]) -> bool:
    source_ref = str(result.get("source_ref") or "")
    return source_ref.startswith("kb:") or source_ref.startswith("synthetic_case_memory:")


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, round((len(sorted_values) - 1) * q))
    return sorted_values[index]


def render_report(items: list[dict[str, Any]], metrics_by_mode: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# Retrieval Evaluation Report",
        "",
        "Synthetic evaluation only. No real counseling records or remote database rows are used.",
        f"Evaluation set: {len(items)} Korean queries across KB, case memory, and negative leakage scenarios.",
        "",
        "| Mode | Recall@1 | Recall@3 | Recall@5 | MRR | Category Accuracy | Source Ref Validity | Cross-Case Leakage | Embedding Mean ms | RPC Mean ms | Total Mean ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, metrics in metrics_by_mode.items():
        lines.append(
            f"| {mode} | {metrics['Recall@1']:.2f} | {metrics['Recall@3']:.2f} | "
            f"{metrics['Recall@5']:.2f} | {metrics['MRR']:.2f} | "
            f"{metrics['category_accuracy']:.2f} | {metrics['source_ref_validity']:.2f} | "
            f"{metrics['cross_case_leakage_count']} | {metrics['mean_embedding_latency_ms']:.3f} | "
            f"{metrics['mean_rpc_latency_ms']:.3f} | {metrics['mean_total_latency_ms']:.3f} |"
        )
    lines.extend(
        [
            "",
            "Latency values are synthetic phase timings for the mock evaluator. Remote checks report measured embedding and Supabase RPC timings separately.",
            "The pg_trgm lexical fallback is included in the SQL migration, but real lexical quality must be judged from remote seeded KB queries.",
            "Do not claim production retrieval quality from this synthetic report.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
