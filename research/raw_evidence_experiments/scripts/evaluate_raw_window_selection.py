"""Controlled PR2.8 candidate-ceiling, selector, and end-to-end evaluation."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
for import_root in (REPO_ROOT, BACKEND_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.schemas.evidence import TranscriptTurn  # noqa: E402
from app.services import raw_evidence_retrieval, transcript_windows  # noqa: E402
from research.raw_evidence_experiments import storage as evidence_storage  # noqa: E402
from research.raw_evidence_experiments.schemas import EvidenceEpisodeSpan, SelectedEvidenceSpan  # noqa: E402
from research.raw_evidence_experiments.services import (  # noqa: E402
    evidence_extraction,
    evidence_retrieval,
    query_evidence_selection,
)
from research.raw_evidence_experiments.scripts.evaluate_episode_boundary_stabilization import span_iou  # noqa: E402
from research.raw_evidence_experiments.scripts.evaluate_raw_evidence_pipeline import (  # noqa: E402
    DEFAULT_FIXTURE, LocalRawEvidenceStorage, cosine, patched_storage,
)

DEFAULT_DIRECT_ARTIFACT = REPO_ROOT / "results" / "debug" / "simplified_scene_extraction" / "three_run_ablation.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "debug" / "raw_window_selection"


class LocalWindowEvaluationStorage(LocalRawEvidenceStorage):
    def __init__(self, corpus):
        super().__init__(corpus)
        self.transcript_windows = []

    def rpc(self, name, params):
        if name != "match_transcript_windows":
            return super().rpc(name, params)
        rows = [row for row in self.transcript_windows if
                row["user_id"] == params["filter_user_id"] and row["case_id"] == params["filter_case_id"]
                and row.get("embedding")]
        for row in rows:
            row["_score"] = cosine(row["embedding"], params["query_embedding"])
        rows.sort(key=lambda row: row["_score"], reverse=True)
        sessions = {row["id"]: row for row in self.sessions}
        return [{
            "window_id": row["id"], "session_id": row["session_id"],
            "session_number": sessions[row["session_id"]]["session_number"],
            "start_turn_index": row["start_turn_index"], "end_turn_index": row["end_turn_index"],
            "source_ref": row["source_ref"], "window_text": row["window_text"],
            "similarity_score": row["_score"], "retrieval_method": "transcript_window_dense",
        } for row in rows[: min(max(int(params.get("match_count") or 12), 1), 50)]]


def _matches(item, gold):
    return (
        item.session_number == gold["session_number"]
        and span_iou(item.start_turn_index, item.end_turn_index,
                     gold["start_turn_index"], gold["end_turn_index"]) >= .5
    )


def _contains(region, gold):
    return (
        region.session_number == gold["session_number"]
        and region.start_turn_index <= gold["start_turn_index"]
        and region.end_turn_index >= gold["end_turn_index"]
    )


def _end_to_end_metrics(query_rows, result_key):
    per_query = []
    matched_gold_total = matched_sessions_total = gold_total = 0
    for row in query_rows:
        results = row[result_key][:5]
        golds = row["gold_episodes"]
        matched = [gold for gold in golds if any(_matches(item, gold) for item in results)]
        gold_sessions = {gold["session_number"] for gold in golds}
        result_sessions = {item.session_number for item in results}
        matched_gold_total += len(matched)
        matched_sessions_total += len(gold_sessions & result_sessions)
        gold_total += len(golds)
        per_query.append({
            "id": row["id"], "hit_at_1": bool(results and any(_matches(results[0], gold) for gold in golds)),
            "hit_at_5": bool(matched), "matched_gold_count": len(matched), "gold_count": len(golds),
            "session_recall_at_5": len(gold_sessions & result_sessions) / len(gold_sessions),
        })
    return {
        "evidence_hit_at_1": sum(item["hit_at_1"] for item in per_query) / len(per_query),
        "evidence_hit_at_5": sum(item["hit_at_5"] for item in per_query) / len(per_query),
        "evidence_recall_at_5": matched_gold_total / gold_total,
        "session_recall_at_5": matched_sessions_total / gold_total,
        "matched_gold_count": matched_gold_total, "gold_count": gold_total,
        "queries": per_query,
    }


def _candidate_metrics(query_rows):
    gold_total = contained_total = session_total = retrieved_session_total = 0
    all_contained_queries = all_session_queries = 0
    for row in query_rows:
        golds, regions = row["gold_episodes"], row["regions"]
        contained = [gold for gold in golds if any(_contains(region, gold) for region in regions)]
        gold_sessions = {gold["session_number"] for gold in golds}
        candidate_sessions = {item.session_number for item in row["window_candidates"]}
        contained_total += len(contained)
        gold_total += len(golds)
        retrieved_session_total += len(gold_sessions & candidate_sessions)
        session_total += len(gold_sessions)
        all_contained_queries += len(contained) == len(golds)
        all_session_queries += gold_sessions <= candidate_sessions
    return {
        "gold_span_candidate_containment": contained_total / gold_total,
        "contained_gold_span_count": contained_total, "gold_span_count": gold_total,
        "gold_session_recall_at_k": retrieved_session_total / session_total,
        "retrieved_gold_session_count": retrieved_session_total, "gold_session_count": session_total,
        "queries_with_all_gold_spans_contained": all_contained_queries,
        "queries_with_all_gold_sessions_retrieved": all_session_queries,
        "query_count": len(query_rows),
        "mean_candidate_regions_per_query": sum(len(row["regions"]) for row in query_rows) / len(query_rows),
        "mean_unique_sessions_at_k": sum(len({item.session_id for item in row["window_candidates"]})
                                         for row in query_rows) / len(query_rows),
    }


def _selector_metrics(query_rows):
    matched_queries = 0
    contained_gold = matched_gold = exact_gold = 0
    best_ious = []
    negative_regions = false_positive_regions = 0
    per_query = []
    for row in query_rows:
        query_all_matched = True
        query_contained = 0
        query_matched = 0
        for gold in row["gold_episodes"]:
            relevant_region_outputs = [item for item in row["region_outputs"] if _contains(item["region"], gold)]
            if not relevant_region_outputs:
                query_all_matched = False
                continue
            query_contained += 1
            contained_gold += 1
            candidates = [span for item in relevant_region_outputs for span in item["selected"]]
            ious = [span_iou(span.start_turn_index, span.end_turn_index,
                             gold["start_turn_index"], gold["end_turn_index"])
                    if span.session_number == gold["session_number"] else 0.0 for span in candidates]
            best = max(ious, default=0.0)
            best_ious.append(best)
            if best >= .5:
                matched_gold += 1
                query_matched += 1
            else:
                query_all_matched = False
            if best == 1.0:
                exact_gold += 1
        matched_queries += query_all_matched and query_contained == len(row["gold_episodes"])
        gold_sessions = {gold["session_number"] for gold in row["gold_episodes"]}
        for item in row["region_outputs"]:
            if item["region"].session_number not in gold_sessions:
                negative_regions += 1
                false_positive_regions += bool(item["selected"])
        per_query.append({
            "id": row["id"], "contained_gold_count": query_contained,
            "matched_gold_count": query_matched, "all_gold_matched": bool(query_all_matched),
        })
    return {
        "query_span_match_at_iou_0_5": matched_queries / len(query_rows),
        "queries_with_all_gold_spans_matched": matched_queries, "query_count": len(query_rows),
        "conditional_gold_span_recall": matched_gold / max(1, contained_gold),
        "matched_gold_span_count": matched_gold, "contained_gold_span_count": contained_gold,
        "mean_best_iou": sum(best_ious) / max(1, len(best_ious)),
        "exact_span_match_rate": exact_gold / max(1, contained_gold),
        "no_evidence_false_positive_rate": false_positive_regions / max(1, negative_regions),
        "false_positive_region_count": false_positive_regions, "negative_region_count": negative_regions,
        "queries": per_query,
    }


def _serialize_query_row(row):
    return {
        "id": row["id"], "query": row["query"], "gold_episodes": row["gold_episodes"],
        "window_candidates": [item.model_dump(mode="json") for item in row["window_candidates"]],
        "regions": [item.model_dump(mode="json") for item in row["regions"]],
        "region_outputs": [{
            "region": item["region"].model_dump(mode="json"),
            "selected": [span.model_dump(mode="json") for span in item["selected"]],
            "diagnostics": [diag.model_dump(mode="json") for diag in item["diagnostics"]],
        } for item in row["region_outputs"]],
        "raw_window_results": [item.model_dump(mode="json") for item in row["raw_window_results"]],
        "global_direct_results": [item.model_dump(mode="json") for item in row["global_direct_results"]],
    }


def _markdown(report):
    a, b, c = report["stage_a_candidate_retrieval"], report["stage_b_selector"], report["stage_c_end_to_end"]
    return "\n".join([
        "# PR2.8 Raw-window retrieval evaluation", "",
        "| Stage | Metric | Result |", "|---|---|---:|",
        f"| A | Gold span containment | {a['gold_span_candidate_containment']:.3f} |",
        f"| A | Gold session recall | {a['gold_session_recall_at_k']:.3f} |",
        f"| B | Query span match@IoU>=0.5 | {b['query_span_match_at_iou_0_5']:.3f} |",
        f"| B | Mean best IoU | {b['mean_best_iou']:.3f} |",
        f"| B | No-evidence false positive | {b['no_evidence_false_positive_rate']:.3f} |",
        f"| C | Evidence Hit@1 | {c['raw_window_pipeline']['evidence_hit_at_1']:.3f} |",
        f"| C | Evidence Hit@5 | {c['raw_window_pipeline']['evidence_hit_at_5']:.3f} |",
        f"| C | Evidence Recall@5 | {c['raw_window_pipeline']['evidence_recall_at_5']:.3f} |",
        f"| C | Session Recall@5 | {c['raw_window_pipeline']['session_recall_at_5']:.3f} |",
        "", "## Decision", "", f"**{report['architecture_decision']}**", "",
    ])


def run(fixture_path=DEFAULT_FIXTURE, direct_path=DEFAULT_DIRECT_ARTIFACT, output_dir=DEFAULT_OUTPUT_DIR):
    corpus = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    direct_artifact = json.loads(Path(direct_path).read_text(encoding="utf-8"))
    local = LocalWindowEvaluationStorage(corpus)

    with ExitStack() as stack:
        stack.enter_context(patched_storage(local))
        stack.enter_context(patch.object(transcript_windows, "storage", local))
        stack.enter_context(patch.object(raw_evidence_retrieval, "storage", local))

        for session in corpus["sessions"]:
            evidence_storage.store_transcript_turns(
                user_id=corpus["user_id"], counselor_id=corpus["counselor_id"], case_id=corpus["case_id"],
                session_id=session["session_id"], turns=[TranscriptTurn.model_validate(item) for item in session["turns"]],
            )
            transcript_windows.index_transcript_windows(
                user_id=corpus["user_id"], counselor_id=corpus["counselor_id"], case_id=corpus["case_id"],
                session_id=session["session_id"],
            )

        # Index the saved PR2.6 direct-span run as a query-level comparison baseline.
        direct_run = direct_artifact["prompt_only"]["runs"][0]
        for session in corpus["sessions"]:
            source_row = next(item for item in direct_run["episodes"] if item["session_number"] == session["session_number"])
            seen = set()
            for raw_span in source_row["predicted_spans"]:
                span = EvidenceEpisodeSpan.model_validate(raw_span)
                key = (span.episode_type, span.start_turn_index, span.end_turn_index)
                if key in seen:
                    continue
                seen.add(key)
                episode = evidence_storage.create_evidence_episode_from_span(
                    user_id=corpus["user_id"], counselor_id=corpus["counselor_id"], case_id=corpus["case_id"],
                    session_id=session["session_id"], span=span,
                )
                evidence_extraction._ensure_episode_embedding(episode.model_dump(mode="json"))

        def evaluate_query(query):
            candidates = raw_evidence_retrieval.retrieve_transcript_window_candidates(
                query_text=query["query"], user_id=corpus["user_id"], case_id=corpus["case_id"], candidate_k=12,
            )
            regions = raw_evidence_retrieval.build_candidate_regions(
                windows=candidates, user_id=corpus["user_id"], case_id=corpus["case_id"],
                turn_loader=evidence_storage.get_transcript_turns,
            )
            region_outputs = []
            all_selected = []
            for region in regions:
                turns = evidence_storage.get_transcript_turns(
                    user_id=corpus["user_id"], case_id=corpus["case_id"], session_id=region.session_id,
                )
                region_turns = [item for item in turns if region.start_turn_index <= item.turn_index <= region.end_turn_index]
                selected, diagnostics = query_evidence_selection.select_evidence_spans_with_diagnostics(
                    query_text=query["query"], region_turns=region_turns,
                    session_number=region.session_number, retrieval_score=region.retrieval_score,
                    retrieval_rank=region.retrieval_rank,
                )
                region_outputs.append({"region": region, "selected": selected, "diagnostics": diagnostics})
                all_selected.extend(selected)
            all_selected.sort(key=lambda item: (
                item.retrieval_rank if item.retrieval_rank is not None else 10**9,
                -(item.retrieval_score if item.retrieval_score is not None else -1), item.session_id,
            ))
            deduped = []
            seen_refs = set()
            for item in all_selected:
                if item.source_ref not in seen_refs:
                    seen_refs.add(item.source_ref)
                    deduped.append(item)
            direct_candidates = evidence_retrieval.retrieve_evidence_episodes(
                query_text=query["query"], user_id=corpus["user_id"], case_id=corpus["case_id"], candidate_k=12,
            )
            direct_results = evidence_retrieval.diversify_evidence_episodes(direct_candidates, max_results=5)
            return {
                "id": query["id"], "query": query["query"], "gold_episodes": query["gold_episodes"],
                "window_candidates": candidates, "regions": regions, "region_outputs": region_outputs,
                "raw_window_results": deduped[:5], "global_direct_results": direct_results,
            }

        with ThreadPoolExecutor(max_workers=6) as executor:
            query_rows = list(executor.map(evaluate_query, corpus["queries"]))

    stage_a = _candidate_metrics(query_rows)
    stage_b = _selector_metrics(query_rows)
    stage_c = {
        "raw_window_pipeline": _end_to_end_metrics(query_rows, "raw_window_results"),
        "global_direct_span_baseline": _end_to_end_metrics(query_rows, "global_direct_results"),
    }
    if stage_a["queries_with_all_gold_spans_contained"] < 5 or stage_a["queries_with_all_gold_sessions_retrieved"] < 6:
        decision = "Candidate retrieval insufficient"
    elif stage_b["queries_with_all_gold_spans_matched"] < 5:
        decision = "Query-conditioned selector insufficient"
    else:
        decision = "Architecture viable — expand evaluation"
    serialized = [_serialize_query_row(row) for row in query_rows]
    examples = {item["id"]: item for item in serialized if item["id"] in {
        "intervention_rehearsal", "first_behavioral_attempt", "setback", "academic_stress_negative_control",
    }}
    report = {
        "description": corpus["description"], "embedding_model": "text-embedding-3-small",
        "selector_model": direct_artifact["model"], "window_size_turns": 6, "window_stride_turns": 3,
        "candidate_k": 12, "context_expansion_turns": 2,
        "global_direct_span_baseline_source": "saved PR2.6 prompt-only run 1",
        "corpus": {"sessions": 8, "turns": 64, "queries": 6, "gold_spans": 7,
                   "indexed_windows": len(local.transcript_windows)},
        "stage_a_candidate_retrieval": stage_a, "stage_b_selector": stage_b,
        "stage_c_end_to_end": stage_c, "representative_raw_examples": examples,
        "queries": serialized, "architecture_decision": decision,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "evaluation.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "corpus": report["corpus"], "stage_a": stage_a, "stage_b": stage_b,
        "stage_c": stage_c, "architecture_decision": decision,
    }, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
