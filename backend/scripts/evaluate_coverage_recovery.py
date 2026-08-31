"""Evaluate a limited uncovered-span coverage pass on saved first-pass outputs."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.evidence import EvidenceEpisodeSpan, StoredTranscriptTurn  # noqa: E402
from app.services import evidence_extraction  # noqa: E402
from scripts.evaluate_episode_boundary_stabilization import aggregate, analyze_session  # noqa: E402
from scripts.evaluate_raw_evidence_pipeline import DEFAULT_FIXTURE  # noqa: E402
from scripts.evaluate_simplified_scene_extraction import METRIC_NAMES, _stability  # noqa: E402

DEFAULT_SOURCE = REPO_ROOT / "results" / "debug" / "simplified_scene_extraction" / "three_run_ablation.json"
DEFAULT_OUTPUT = REPO_ROOT / "results" / "debug" / "simplified_scene_extraction" / "coverage_recovery.json"


def _first_pass_spans(run: dict, session_number: int) -> list[EvidenceEpisodeSpan]:
    row = next(item for item in run["episodes"] if item["session_number"] == session_number)
    return [EvidenceEpisodeSpan.model_validate(item) for item in row["predicted_spans"]]


def _turns(corpus: dict, session: dict) -> list[StoredTranscriptTurn]:
    return [StoredTranscriptTurn(
        id=f'synthetic-{session["session_number"]}-{turn["turn_index"]}',
        user_id=corpus["user_id"], counselor_id=corpus["counselor_id"], case_id=corpus["case_id"],
        session_id=session["session_id"], **turn,
    ) for turn in session["turns"]]


def _gate(metrics: dict, stability: dict) -> dict:
    checks = {
        "match_at_iou_0_5_gte_0_85": metrics["gold_episode_match_at_iou_0_5"] >= .85,
        "episode_type_accuracy_gte_0_85": metrics["episode_type_accuracy"] >= .85,
        "missed_episode_rate_lte_0_15": metrics["missed_episode_rate"] <= .15,
        "over_segmentation_rate_lte_0_10": metrics["over_segmentation_rate"] <= .10,
        "invalid_candidate_rate_lte_0_05": metrics["invalid_candidate_rate"] <= .05,
        "predicted_to_gold_ratio_in_0_85_1_25": .85 <= metrics["predicted_to_gold_ratio"] <= 1.25,
        "consistent_iou_0_5_match_rate_gte_0_80": stability["consistent_iou_0_5_match_rate"] >= .80,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run(fixture_path=DEFAULT_FIXTURE, source_path=DEFAULT_SOURCE, output_path=DEFAULT_OUTPUT):
    corpus = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    prompt_runs = source["prompt_only"]["runs"]
    jobs = []
    for run_index, first_run in enumerate(prompt_runs):
        for session in corpus["sessions"]:
            turns = _turns(corpus, session)
            first_spans = _first_pass_spans(first_run, session["session_number"])
            ranges = evidence_extraction._substantive_uncovered_client_ranges(turns, first_spans)
            jobs.append((run_index, session, turns, first_spans, ranges))

    def task(job):
        run_index, session, turns, first_spans, ranges = job
        recovered, diagnostics = evidence_extraction.extract_uncovered_client_event_spans(
            turns=turns, first_pass_spans=first_spans,
        )
        combined = list(first_spans)
        seen = {(item.episode_type, item.start_turn_index, item.end_turn_index) for item in combined}
        for item in recovered:
            key = (item.episode_type, item.start_turn_index, item.end_turn_index)
            if key not in seen:
                combined.append(item)
                seen.add(key)
        return run_index, session, ranges, first_spans, recovered, combined, diagnostics

    with ThreadPoolExecutor(max_workers=8) as executor:
        outputs = list(executor.map(task, jobs))

    indexed = {(item[0], item[1]["session_number"]): item for item in outputs}
    gold_count = sum(len(session["gold_episodes"]) for session in corpus["sessions"])
    recovery_runs = []
    extra_calls = extra_input_turns = recovered_count = rejected_count = 0
    for run_index, first_run in enumerate(prompt_runs):
        rows = []
        run_recovered = run_rejected = run_candidates = run_input_turns = run_calls = run_combined = 0
        first_invalid = first_run["metrics"]["error_taxonomy"]["invalid_candidates"]
        first_predicted = first_run["metrics"]["predicted_episode_count"]
        session_details = []
        for session in corpus["sessions"]:
            _, _, ranges, first_spans, recovered, combined, diagnostics = indexed[(run_index, session["session_number"])]
            analyzed, _, _, _ = analyze_session(session, combined, diagnostics)
            rows.extend(analyzed)
            invalid = sum(item.code in {"invalid_episode", "invalid_coverage_episode"} for item in diagnostics)
            duplicates = sum(item.code == "duplicate_episode" for item in diagnostics)
            candidate_count = len(recovered) + invalid + duplicates
            input_turns = sum(end - start + 1 for start, end in ranges)
            run_calls += bool(ranges)
            run_input_turns += input_turns
            run_recovered += len(recovered)
            run_combined += len(combined)
            run_rejected += invalid
            run_candidates += candidate_count
            session_details.append({
                "session_number": session["session_number"],
                "uncovered_ranges": [list(item) for item in ranges],
                "coverage_input_turn_count": input_turns,
                "first_pass_spans": [item.model_dump(mode="json") for item in first_spans],
                "recovered_spans": [item.model_dump(mode="json") for item in recovered],
                "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            })
        metrics = aggregate(
            rows,
            first_invalid + run_rejected,
            run_combined,
            first_predicted + first_invalid + run_candidates,
            gold_count,
        )
        recovery_runs.append({
            "run": run_index + 1, "metrics": metrics, "episodes": rows,
            "cost": {"extra_llm_calls": run_calls, "extra_input_turns": run_input_turns,
                     "recovered_episode_count": run_recovered, "rejected_candidate_count": run_rejected},
            "sessions": session_details,
        })
        extra_calls += run_calls
        extra_input_turns += run_input_turns
        recovered_count += run_recovered
        rejected_count += run_rejected

    means = {name: sum(item["metrics"][name] for item in recovery_runs) / len(recovery_runs)
             for name in METRIC_NAMES}
    stability = _stability(recovery_runs)
    gate = _gate(means, stability)
    report = {
        "description": "Conditional limited coverage recovery on controlled synthetic data only.",
        "source_first_pass_artifact": str(Path(source_path).resolve()),
        "model": source["model"], "temperature": source["temperature"], "runs": len(recovery_runs),
        "single_pass": {
            "mean_metrics": source["prompt_only"]["mean_metrics"],
            "stability": source["prompt_only"]["stability"],
        },
        "with_limited_coverage_recovery": {
            "mean_metrics": means, "stability": stability, "runs": recovery_runs,
        },
        "cost": {
            "extra_llm_calls_total": extra_calls,
            "extra_llm_calls_mean_per_session_run": extra_calls / (len(recovery_runs) * len(corpus["sessions"])),
            "extra_input_turns_total": extra_input_turns,
            "extra_input_turns_mean_per_call": extra_input_turns / max(1, extra_calls),
            "recovered_episode_count_total": recovered_count,
            "rejected_candidate_count_total": rejected_count,
        },
        "acceptance_gate": gate,
        "adoption_decision": (
            "eligible_for_adoption_review" if gate["passed"] else "do_not_adopt_needs_another_extraction_iteration"
        ),
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "single_pass": report["single_pass"],
        "with_limited_coverage_recovery": {"mean_metrics": means, "stability": stability},
        "cost": report["cost"], "acceptance_gate": gate,
        "adoption_decision": report["adoption_decision"],
    }, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
