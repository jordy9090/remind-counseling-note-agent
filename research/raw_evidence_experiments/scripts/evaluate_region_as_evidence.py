"""Evaluate saved deterministic raw regions as final evidence units without LLM calls."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
for import_root in (REPO_ROOT, BACKEND_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

DEFAULT_SOURCE = REPO_ROOT / "results" / "debug" / "raw_window_selection" / "evaluation.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "debug" / "region_as_evidence"
TOP_K_VALUES = (1, 3, 5, 8, 12)
EXAMPLE_QUERY_IDS = (
    "intervention_rehearsal", "first_behavioral_attempt", "setback", "academic_stress_negative_control",
)


def _contains(unit, gold):
    return (
        unit.get("session_number") == gold["session_number"]
        and unit["start_turn_index"] <= gold["start_turn_index"]
        and unit["end_turn_index"] >= gold["end_turn_index"]
    )


def _length(unit):
    return unit["end_turn_index"] - unit["start_turn_index"] + 1


def evaluate_units(queries, *, unit_key, k):
    contained_gold = retrieved_gold_sessions = gold_count = gold_session_count = query_success = 0
    unique_sessions = unit_counts = gold_unit_counts = non_gold_unit_counts = 0
    lengths = []
    query_rows = []
    for query in queries:
        units = query[unit_key][:k]
        golds = query["gold_episodes"]
        contained = [gold for gold in golds if any(_contains(unit, gold) for unit in units)]
        gold_sessions = {gold["session_number"] for gold in golds}
        retrieved_sessions = {unit.get("session_number") for unit in units}
        gold_units = [unit for unit in units if any(_contains(unit, gold) for gold in golds)]
        non_gold_units = len(units) - len(gold_units)
        contained_gold += len(contained)
        gold_count += len(golds)
        retrieved_gold_sessions += len(gold_sessions & retrieved_sessions)
        gold_session_count += len(gold_sessions)
        query_success += len(contained) == len(golds)
        unique_sessions += len(retrieved_sessions)
        unit_counts += len(units)
        gold_unit_counts += len(gold_units)
        non_gold_unit_counts += non_gold_units
        lengths.extend(_length(unit) for unit in units)
        query_rows.append({
            "id": query["id"], "contained_gold_count": len(contained), "gold_count": len(golds),
            "all_required_gold_contained": len(contained) == len(golds),
            "missing_gold": [gold for gold in golds if gold not in contained],
        })
    query_count = len(queries)
    return {
        "k": k,
        "gold_span_containment": contained_gold / gold_count,
        "contained_gold_span_count": contained_gold, "gold_span_count": gold_count,
        "gold_session_recall": retrieved_gold_sessions / gold_session_count,
        "retrieved_gold_session_count": retrieved_gold_sessions, "gold_session_count": gold_session_count,
        "query_success_rate": query_success / query_count,
        "successful_query_count": query_success, "query_count": query_count,
        "precision_proxy": {
            "description": "Controlled-gold coverage proxy; not human relevance precision.",
            "mean_unique_sessions": unique_sessions / query_count,
            "mean_units_per_query": unit_counts / query_count,
            "mean_gold_containing_units_per_query": gold_unit_counts / query_count,
            "mean_non_gold_units_per_query": non_gold_unit_counts / query_count,
            "non_gold_unit_proportion": non_gold_unit_counts / max(1, unit_counts),
        },
        "length_statistics": {
            "mean_turns_per_unit": sum(lengths) / max(1, len(lengths)),
            "median_turns_per_unit": statistics.median(lengths) if lengths else 0,
            "max_turns_per_unit": max(lengths, default=0),
        },
        "queries": query_rows,
    }


def _examples(queries):
    examples = {}
    for query in queries:
        if query["id"] not in EXAMPLE_QUERY_IDS:
            continue
        rows = []
        for rank, region in enumerate(query["regions"][:5], start=1):
            containing = [gold for gold in query["gold_episodes"] if _contains(region, gold)]
            rows.append({
                "rank": rank, "retrieval_rank": region["retrieval_rank"],
                "session_number": region["session_number"],
                "start_turn_index": region["start_turn_index"], "end_turn_index": region["end_turn_index"],
                "similarity_score": region["retrieval_score"],
                "gold_containment": bool(containing), "contained_gold_spans": containing,
                "source_ref": region["source_ref"], "raw_region_text": region["region_text"],
            })
        examples[query["id"]] = {"query": query["query"], "gold_episodes": query["gold_episodes"], "top_5": rows}
    return examples


def evaluate(source):
    queries = source["queries"]
    region_metrics = {str(k): evaluate_units(queries, unit_key="regions", k=k) for k in TOP_K_VALUES}
    window_metrics = {str(k): evaluate_units(queries, unit_key="window_candidates", k=k) for k in TOP_K_VALUES}
    comparison = {}
    for k in TOP_K_VALUES:
        region, window = region_metrics[str(k)], window_metrics[str(k)]
        comparison[str(k)] = {
            "k": k,
            "raw_windows": {
                "gold_span_containment": window["gold_span_containment"],
                "contained_gold_span_count": window["contained_gold_span_count"],
                "mean_unique_sessions": window["precision_proxy"]["mean_unique_sessions"],
                "mean_region_length_turns": window["length_statistics"]["mean_turns_per_unit"],
            },
            "merged_expanded_regions": {
                "gold_span_containment": region["gold_span_containment"],
                "contained_gold_span_count": region["contained_gold_span_count"],
                "mean_unique_sessions": region["precision_proxy"]["mean_unique_sessions"],
                "mean_region_length_turns": region["length_statistics"]["mean_turns_per_unit"],
            },
        }

    top5 = region_metrics["5"]
    local_length = 4 <= top5["length_statistics"]["mean_turns_per_unit"] <= 12
    product_gate = {
        "gold_session_recall_at_5_gte_6_of_7": top5["retrieved_gold_session_count"] >= 6,
        "gold_span_containment_at_5_gte_6_of_7": top5["contained_gold_span_count"] >= 6,
        "query_success_at_5_gte_5_of_6": top5["successful_query_count"] >= 5,
        "mean_region_length_between_4_and_12_turns": local_length,
    }
    top12 = region_metrics["12"]
    if all(product_gate.values()):
        decision = "Ready for PR4 — use raw regions as evidence units"
    elif top12["contained_gold_span_count"] == 7 and top12["retrieved_gold_session_count"] == 7:
        decision = "Candidate ceiling sufficient, ranking needs improvement"
    else:
        decision = "Raw region construction needs revision"
    return {
        "description": "Region-as-evidence evaluation using saved deterministic raw-window retrieval only.",
        "source_artifact": str(DEFAULT_SOURCE.resolve()),
        "llm_calls": 0, "selector_used": False, "query_count": 6, "gold_span_count": 7,
        "top_k_region_metrics": region_metrics,
        "window_vs_merged_region": comparison,
        "representative_top_5_raw_regions": _examples(queries),
        "failed_queries_at_5": [item for item in top5["queries"] if not item["all_required_gold_contained"]],
        "selector_reference_only": {"existing_selector_hit_at_5": 0.0, "selector_rerun": False},
        "product_gate": {"passed": all(product_gate.values()), "checks": product_gate},
        "decision": decision,
    }


def _markdown(report):
    lines = [
        "# Region-as-evidence baseline", "",
        "> Precision fields below are controlled-gold coverage proxies, not human relevance precision.", "",
        "| k | Containment | Session recall | Query success | Unique sessions | Regions/query | Gold regions/query | Non-gold regions/query | Non-gold proportion | Mean turns | Median | Max |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for k in TOP_K_VALUES:
        item = report["top_k_region_metrics"][str(k)]
        proxy, length = item["precision_proxy"], item["length_statistics"]
        lines.append(
            f"| {k} | {item['contained_gold_span_count']}/7 | {item['retrieved_gold_session_count']}/7 "
            f"| {item['successful_query_count']}/6 | {proxy['mean_unique_sessions']:.2f} "
            f"| {proxy['mean_units_per_query']:.2f} | {proxy['mean_gold_containing_units_per_query']:.2f} "
            f"| {proxy['mean_non_gold_units_per_query']:.2f} | {proxy['non_gold_unit_proportion']:.1%} "
            f"| {length['mean_turns_per_unit']:.2f} | {length['median_turns_per_unit']:.1f} "
            f"| {length['max_turns_per_unit']} |"
        )
    lines.extend(["", "## Raw windows vs merged + expanded regions", "",
                  "| k | Window containment | Region containment | Window unique sessions | Region unique sessions | Window mean turns | Region mean turns |",
                  "|---:|---:|---:|---:|---:|---:|---:|"])
    for k in TOP_K_VALUES:
        row = report["window_vs_merged_region"][str(k)]
        window, region = row["raw_windows"], row["merged_expanded_regions"]
        lines.append(
            f"| {k} | {window['contained_gold_span_count']}/7 | {region['contained_gold_span_count']}/7 "
            f"| {window['mean_unique_sessions']:.2f} | {region['mean_unique_sessions']:.2f} "
            f"| {window['mean_region_length_turns']:.2f} | {region['mean_region_length_turns']:.2f} |"
        )
    lines.extend(["", "## Four query top-5 raw regions", ""])
    for query_id in EXAMPLE_QUERY_IDS:
        example = report["representative_top_5_raw_regions"][query_id]
        lines.extend([f"### {query_id}", "", example["query"], ""])
        for item in example["top_5"]:
            lines.extend([
                f"#### Rank {item['rank']} — S{item['session_number']} "
                f"{item['start_turn_index']}-{item['end_turn_index']}", "",
                f"Similarity: {item['similarity_score']:.6f}; gold containment: {item['gold_containment']}", "",
                "```text", item["raw_region_text"], "```", "",
            ])
    lines.extend(["## Decision", "", f"**{report['decision']}**", ""])
    return "\n".join(lines)


def run(source_path=DEFAULT_SOURCE, output_dir=DEFAULT_OUTPUT_DIR):
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    report = evaluate(source)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "evaluation.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "top_k_region_metrics": report["top_k_region_metrics"],
        "window_vs_merged_region": report["window_vs_merged_region"],
        "failed_queries_at_5": report["failed_queries_at_5"],
        "selector_reference_only": report["selector_reference_only"],
        "product_gate": report["product_gate"], "decision": report["decision"],
    }, ensure_ascii=True, indent=2))
    return report


if __name__ == "__main__":
    run()
