"""Three-run span-only extraction stability and consolidation ablation."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.schemas.evidence import TranscriptTurn  # noqa: E402
from app.services import evidence_extraction, evidence_storage  # noqa: E402
from scripts.evaluate_episode_boundary_stabilization import aggregate, analyze_session, span_iou  # noqa: E402
from scripts.evaluate_raw_evidence_pipeline import DEFAULT_FIXTURE, LocalRawEvidenceStorage, patched_storage  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "results" / "debug" / "simplified_scene_extraction"
METRIC_NAMES = (
    "gold_episode_match_at_iou_0_5", "mean_best_span_iou", "episode_type_accuracy",
    "invalid_candidate_rate", "over_segmentation_rate", "under_segmentation_rate",
    "boundary_shift_rate", "missed_episode_rate", "predicted_to_gold_ratio",
)


def _evaluate_path(corpus, outputs, *, consolidate):
    runs = []
    gold_count = sum(len(session["gold_episodes"]) for session in corpus["sessions"])
    for run_index in range(3):
        rows, invalid_count, predicted_count, candidate_count = [], 0, 0, 0
        for session in corpus["sessions"]:
            turns, spans, diagnostics = outputs[(run_index, session["session_number"])]
            if consolidate:
                spans, merge_diagnostics = evidence_extraction.consolidate_episode_fragments(spans, turns=turns)
                diagnostics = [*diagnostics, *merge_diagnostics]
            analyzed, invalid, predicted, candidates = analyze_session(session, spans, diagnostics)
            rows.extend(analyzed)
            invalid_count += invalid
            predicted_count += predicted
            candidate_count += candidates
        runs.append({
            "run": run_index + 1,
            "metrics": aggregate(rows, invalid_count, predicted_count, candidate_count, gold_count),
            "episodes": rows,
        })
    means = {name: sum(run["metrics"][name] for run in runs) / len(runs) for name in METRIC_NAMES}
    stability = _stability(runs)
    return {"mean_metrics": means, "stability": stability, "runs": runs}


def _stability(runs):
    gold_count = len(runs[0]["episodes"])
    exact, consistent = 0, 0
    for index in range(gold_count):
        matches = []
        for run in runs:
            row = run["episodes"][index]
            gold = row["gold"]
            correct = [item for item in row["predicted_spans"] if
                       item["episode_type"] == gold["episode_type"] and
                       span_iou(item["start_turn_index"], item["end_turn_index"], gold["start_turn_index"], gold["end_turn_index"]) >= .5]
            correct.sort(key=lambda item: span_iou(
                item["start_turn_index"], item["end_turn_index"], gold["start_turn_index"], gold["end_turn_index"]
            ), reverse=True)
            matches.append((correct[0]["episode_type"], correct[0]["start_turn_index"], correct[0]["end_turn_index"]) if correct else None)
        if all(match is not None for match in matches):
            consistent += 1
            if len(set(matches)) == 1:
                exact += 1
    return {
        "exact_same_span_rate": exact / gold_count,
        "consistent_iou_0_5_match_rate": consistent / gold_count,
        "gold_episode_count": gold_count,
    }


def run(fixture_path=DEFAULT_FIXTURE, output_dir=DEFAULT_OUTPUT):
    corpus = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    local = LocalRawEvidenceStorage(corpus)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with patched_storage(local):
        for session in corpus["sessions"]:
            evidence_storage.store_transcript_turns(
                user_id=corpus["user_id"], counselor_id=corpus["counselor_id"], case_id=corpus["case_id"],
                session_id=session["session_id"], turns=[TranscriptTurn.model_validate(turn) for turn in session["turns"]],
            )

        def task(job):
            run_index, session = job
            turns = evidence_storage.get_transcript_turns(
                user_id=corpus["user_id"], case_id=corpus["case_id"], session_id=session["session_id"],
            )
            spans, diagnostics = evidence_extraction._extract_with_diagnostics(
                turns=turns, extractor=None, consolidate_fragments=False,
            )
            return run_index, session["session_number"], turns, spans, diagnostics

        jobs = [(run_index, session) for run_index in range(3) for session in corpus["sessions"]]
        with ThreadPoolExecutor(max_workers=24) as executor:
            raw_outputs = list(executor.map(task, jobs))
    outputs = {(run_index, number): (turns, spans, diagnostics) for run_index, number, turns, spans, diagnostics in raw_outputs}
    prompt_only = _evaluate_path(corpus, outputs, consolidate=False)
    prompt_plus_consolidation = _evaluate_path(corpus, outputs, consolidate=True)
    report = {
        "description": corpus["description"], "model": settings.openai_model, "temperature": 0,
        "runs": 3, "gold_episode_count": 16,
        "prompt_only": prompt_only, "prompt_plus_consolidation": prompt_plus_consolidation,
        "pr2_5_reference": {
            "gold_episode_match_at_iou_0_5": 0.75, "mean_best_span_iou": 0.589,
            "episode_type_accuracy": 1.0, "invalid_candidate_rate": 0.20,
            "over_segmentation_rate": 0.0, "missed_episode_rate": 0.25,
            "predicted_to_gold_ratio": 0.75,
        },
    }
    (output_dir / "three_run_ablation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "prompt_only": {"mean_metrics": prompt_only["mean_metrics"], "stability": prompt_only["stability"]},
        "prompt_plus_consolidation": {"mean_metrics": prompt_plus_consolidation["mean_metrics"], "stability": prompt_plus_consolidation["stability"]},
    }, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
