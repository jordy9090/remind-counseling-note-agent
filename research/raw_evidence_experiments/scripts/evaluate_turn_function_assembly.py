"""Three-run PR2.7 turn-function labeling and deterministic assembly evaluation."""
from __future__ import annotations

import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
for import_root in (REPO_ROOT, BACKEND_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.schemas.evidence import StoredTranscriptTurn  # noqa: E402
from research.raw_evidence_experiments.schemas import TurnFunctionLabel  # noqa: E402
from research.raw_evidence_experiments.services.evidence_turn_functions import (  # noqa: E402
    assemble_evidence_episodes_with_diagnostics, extract_evidence_episode_spans_from_turn_functions,
)
from research.raw_evidence_experiments.scripts.evaluate_episode_boundary_stabilization import aggregate, analyze_session  # noqa: E402
from research.raw_evidence_experiments.scripts.evaluate_raw_evidence_pipeline import DEFAULT_FIXTURE  # noqa: E402
from research.raw_evidence_experiments.scripts.evaluate_simplified_scene_extraction import METRIC_NAMES, _stability  # noqa: E402

DEFAULT_DIRECT_ARTIFACT = REPO_ROOT / "results" / "debug" / "simplified_scene_extraction" / "three_run_ablation.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "debug" / "turn_function_assembly"
INVALID_LABEL_CODES = {
    "invalid_turn_function", "nonexistent_turn_label", "duplicate_turn_label", "invalid_speaker_function",
}


def _turns(corpus, session):
    return [StoredTranscriptTurn(
        id=f'synthetic-{session["session_number"]}-{turn["turn_index"]}',
        user_id=corpus["user_id"], counselor_id=corpus["counselor_id"], case_id=corpus["case_id"],
        session_id=session["session_id"], **turn,
    ) for turn in session["turns"]]


def _label_counts(labels, diagnostics):
    invalid = sum(item.code in INVALID_LABEL_CODES for item in diagnostics)
    return invalid, len(labels) + invalid


def _turn_metrics(sessions, outputs, run_index):
    correct = total = invalid = candidates = 0
    gold_counts = Counter()
    true_positive = Counter()
    confusion = Counter()
    for session in sessions:
        _, labels, _, diagnostics = outputs[(run_index, session["session_number"])]
        predicted = {item.turn_index: item.function for item in labels}
        gold = {item["turn_index"]: item["function"] for item in session["turn_function_gold"]}
        for turn_index, expected in gold.items():
            actual = predicted.get(turn_index)
            total += 1
            gold_counts[expected] += 1
            confusion[(expected, actual or "missing_or_invalid")] += 1
            if actual == expected:
                correct += 1
                true_positive[expected] += 1
        invalid_here, candidates_here = _label_counts(labels, diagnostics)
        invalid += invalid_here
        candidates += candidates_here
    return {
        "turn_function_accuracy": correct / total,
        "client_report_recall": true_positive["client_report"] / gold_counts["client_report"],
        "counselor_intervention_recall": true_positive["counselor_intervention"] / gold_counts["counselor_intervention"],
        "client_response_recall": true_positive["client_response"] / gold_counts["client_response"],
        # Class-specific accuracy: correctly identified gold clarification turns / all gold clarification turns.
        "counselor_clarification_accuracy": (
            true_positive["counselor_clarification"] / gold_counts["counselor_clarification"]
        ),
        "invalid_speaker_function_rate": (
            sum(item.code == "invalid_speaker_function" for session in sessions
                for item in outputs[(run_index, session["session_number"])][3]) / max(1, candidates)
        ),
        "invalid_label_candidate_rate": invalid / max(1, candidates),
        "correct_turn_count": correct, "turn_count": total,
        "confusion": {f"{expected}->{actual}": count for (expected, actual), count in sorted(confusion.items())},
    }


def _turn_label_stability(corpus, outputs):
    exact = 0
    total = sum(len(session["turns"]) for session in corpus["sessions"])
    for session in corpus["sessions"]:
        run_maps = []
        for run_index in range(3):
            labels = outputs[(run_index, session["session_number"])][1]
            run_maps.append({item.turn_index: item.function for item in labels})
        for turn in session["turns"]:
            values = [mapping.get(turn["turn_index"]) for mapping in run_maps]
            if all(value is not None for value in values) and len(set(values)) == 1:
                exact += 1
    return {"turn_label_exact_agreement_rate": exact / total, "agreed_turn_count": exact, "turn_count": total}


def _evaluate_episode_runs(corpus, outputs):
    gold_count = sum(len(session["gold_episodes"]) for session in corpus["sessions"])
    runs = []
    for run_index in range(3):
        rows = []
        invalid = candidates = predicted = 0
        for session in corpus["sessions"]:
            _, _, spans, diagnostics = outputs[(run_index, session["session_number"])]
            analyzed, _, predicted_here, _ = analyze_session(session, spans, diagnostics)
            rows.extend(analyzed)
            predicted += predicted_here
            invalid_here = sum(item.code == "invalid_assembled_episode" for item in diagnostics)
            candidates_here = predicted_here + invalid_here
            invalid += invalid_here
            candidates += candidates_here
        metrics = aggregate(rows, invalid, predicted, candidates, gold_count)
        metrics["matched_gold_count"] = sum(item["matched_at_iou_0_5_with_type"] for item in rows)
        metrics["error_taxonomy"]["invalid_candidates"] = invalid
        runs.append({"run": run_index + 1, "metrics": metrics, "episodes": rows})
    means = {name: sum(item["metrics"][name] for item in runs) / len(runs) for name in METRIC_NAMES}
    means["mean_matched_gold_count"] = sum(item["metrics"]["matched_gold_count"] for item in runs) / len(runs)
    return {"mean_metrics": means, "stability": _stability(runs), "runs": runs}


def _oracle_assembly(corpus):
    rows = []
    predicted = 0
    details = []
    for session in corpus["sessions"]:
        turns = _turns(corpus, session)
        labels = [TurnFunctionLabel.model_validate(item) for item in session["turn_function_gold"]]
        spans, diagnostics = assemble_evidence_episodes_with_diagnostics(turns, labels)
        analyzed, _, count, _ = analyze_session(session, spans, diagnostics)
        rows.extend(analyzed)
        predicted += count
        details.append({
            "session_number": session["session_number"],
            "spans": [item.model_dump(mode="json") for item in spans],
            "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
        })
    gold_count = len(rows)
    metrics = aggregate(rows, 0, predicted, sum(len(item["turns"]) for item in corpus["sessions"]), gold_count)
    metrics["matched_gold_count"] = sum(item["matched_at_iou_0_5_with_type"] for item in rows)
    return {"metrics": metrics, "sessions": details}


def _case_details(corpus, outputs):
    details = []
    for session in corpus["sessions"][:4]:
        item = {
            "session_number": session["session_number"], "stage": session["stage"],
            "turns": session["turns"], "gold_turn_functions": session["turn_function_gold"],
            "gold_episodes": session["gold_episodes"], "runs": [],
        }
        for run_index in range(3):
            _, labels, spans, diagnostics = outputs[(run_index, session["session_number"])]
            item["runs"].append({
                "run": run_index + 1,
                "predicted_labels": [label.model_dump(mode="json") for label in labels],
                "assembled_spans": [span.model_dump(mode="json") for span in spans],
                "diagnostics": [diagnostic.model_dump(mode="json") for diagnostic in diagnostics],
            })
        details.append(item)
    return details


def _acceptance_gate(episode_evaluation):
    metrics = episode_evaluation["mean_metrics"]
    stability = episode_evaluation["stability"]
    run_matches = [item["metrics"]["matched_gold_count"] for item in episode_evaluation["runs"]]
    checks = {
        "at_least_14_of_16_each_run": min(run_matches) >= 14,
        "mean_match_rate_gte_0_875": metrics["gold_episode_match_at_iou_0_5"] >= .875,
        "episode_type_accuracy_gte_0_90": metrics["episode_type_accuracy"] >= .90,
        "missed_episode_rate_lte_0_125": metrics["missed_episode_rate"] <= .125,
        "invalid_candidate_rate_lte_0_05": metrics["invalid_candidate_rate"] <= .05,
        "predicted_to_gold_ratio_in_0_8_1_25": .8 <= metrics["predicted_to_gold_ratio"] <= 1.25,
        "consistent_iou_0_5_match_rate_gte_0_80": stability["consistent_iou_0_5_match_rate"] >= .80,
    }
    return {"passed": all(checks.values()), "checks": checks, "matched_gold_counts_by_run": run_matches}


def evaluate(corpus, direct_artifact, outputs):
    turn_runs = [{"run": index + 1, "metrics": _turn_metrics(corpus["sessions"], outputs, index)} for index in range(3)]
    metric_names = (
        "turn_function_accuracy", "client_report_recall", "counselor_intervention_recall",
        "client_response_recall", "counselor_clarification_accuracy", "invalid_speaker_function_rate",
        "invalid_label_candidate_rate",
    )
    turn_mean = {name: sum(item["metrics"][name] for item in turn_runs) / 3 for name in metric_names}
    episode_evaluation = _evaluate_episode_runs(corpus, outputs)
    gate = _acceptance_gate(episode_evaluation)
    mean_matches = episode_evaluation["mean_metrics"]["mean_matched_gold_count"]
    if gate["passed"]:
        judgment = "Ready for PR3"
    elif mean_matches >= 13:
        judgment = "Needs broader evaluation corpus"
    else:
        judgment = "Architecture still insufficient"
    return {
        "description": corpus["description"], "model": direct_artifact.get("model", "gpt-4o-mini"),
        "temperature": 0, "runs": 3, "session_count": len(corpus["sessions"]),
        "turn_count": sum(len(item["turns"]) for item in corpus["sessions"]),
        "gold_episode_count": sum(len(item["gold_episodes"]) for item in corpus["sessions"]),
        "direct_span_baseline": direct_artifact["prompt_only"],
        "gold_label_oracle_assembly": _oracle_assembly(corpus),
        "turn_function_labeling": {
            "mean_metrics": turn_mean, "stability": _turn_label_stability(corpus, outputs), "runs": turn_runs,
        },
        "function_labeling_episode_assembly": episode_evaluation,
        "required_case_details": _case_details(corpus, outputs),
        "acceptance_gate": gate, "judgment": judgment,
    }


def _markdown(report):
    direct = report["direct_span_baseline"]["mean_metrics"]
    new = report["function_labeling_episode_assembly"]["mean_metrics"]
    lines = [
        "# PR2.7 Turn-function labeling evaluation", "",
        "| Episode metric | Direct span | Function labels + deterministic assembly |", "|---|---:|---:|",
    ]
    for key in METRIC_NAMES:
        lines.append(f"| {key} | {direct[key]:.4f} | {new[key]:.4f} |")
    lines.extend(["", "## Required S1-S4 cases", ""])
    for case in report["required_case_details"]:
        lines.append(f"### S{case['session_number']} — {case['stage']}")
        lines.append("")
        for run in case["runs"]:
            labels = ", ".join(f"{item['turn_index']}:{item['function']}" for item in run["predicted_labels"])
            spans = ", ".join(
                f"{item['episode_type']}:{item['start_turn_index']}-{item['end_turn_index']}"
                for item in run["assembled_spans"]
            )
            lines.append(f"- Run {run['run']} labels: {labels}")
            lines.append(f"- Run {run['run']} spans: {spans or '(none)'}")
        lines.append("")
    lines.extend(["## Judgment", "", f"**{report['judgment']}**", ""])
    return "\n".join(lines)


def run(fixture_path=DEFAULT_FIXTURE, direct_path=DEFAULT_DIRECT_ARTIFACT, output_dir=DEFAULT_OUTPUT_DIR):
    corpus = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    direct = json.loads(Path(direct_path).read_text(encoding="utf-8"))

    def task(job):
        run_index, session = job
        turns = _turns(corpus, session)
        spans, labels, diagnostics = extract_evidence_episode_spans_from_turn_functions(turns=turns)
        return run_index, session["session_number"], (turns, labels, spans, diagnostics)

    jobs = [(run_index, session) for run_index in range(3) for session in corpus["sessions"]]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(task, jobs))
    outputs = {(run_index, session_number): output for run_index, session_number, output in results}
    report = evaluate(corpus, direct, outputs)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "three_run_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (output_dir / "three_run_comparison.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "turn_function_labeling": report["turn_function_labeling"],
        "direct_span_baseline": {
            "mean_metrics": report["direct_span_baseline"]["mean_metrics"],
            "stability": report["direct_span_baseline"]["stability"],
        },
        "gold_label_oracle_assembly": report["gold_label_oracle_assembly"]["metrics"],
        "function_labeling_episode_assembly": {
            "mean_metrics": report["function_labeling_episode_assembly"]["mean_metrics"],
            "stability": report["function_labeling_episode_assembly"]["stability"],
        },
        "acceptance_gate": report["acceptance_gate"], "judgment": report["judgment"],
    }, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
