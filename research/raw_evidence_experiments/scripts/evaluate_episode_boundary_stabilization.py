"""Compare legacy and scene-level episode extraction on the same synthetic corpus."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
for import_root in (REPO_ROOT, BACKEND_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.core.config import settings  # noqa: E402
from app.schemas.evidence import TranscriptTurn  # noqa: E402
from research.raw_evidence_experiments import storage as evidence_storage  # noqa: E402
from research.raw_evidence_experiments.services import evidence_extraction  # noqa: E402
from research.raw_evidence_experiments.scripts.evaluate_raw_evidence_pipeline import (  # noqa: E402
    DEFAULT_FIXTURE, LocalRawEvidenceStorage, patched_storage,
)

DEFAULT_OUTPUT = REPO_ROOT / "results" / "debug" / "episode_boundary_stabilization"


def span_iou(start_a, end_a, start_b, end_b):
    intersection = max(0, min(end_a, end_b) - max(start_a, start_b) + 1)
    union = max(end_a, end_b) - min(start_a, start_b) + 1
    return intersection / union if union else 0.0


def _intersection_coverage(predicted, gold):
    intersection = max(0, min(predicted.end_turn_index, gold["end_turn_index"]) - max(predicted.start_turn_index, gold["start_turn_index"]) + 1)
    return intersection / (gold["end_turn_index"] - gold["start_turn_index"] + 1)


def analyze_session(session: dict[str, Any], predicted, diagnostics):
    gold_rows = []
    for gold in session["gold_episodes"]:
        ranked = sorted(
            ((span_iou(item.start_turn_index, item.end_turn_index, gold["start_turn_index"], gold["end_turn_index"]), item) for item in predicted),
            key=lambda pair: pair[0], reverse=True,
        )
        best_iou, best = ranked[0] if ranked else (0.0, None)
        correct = [item for iou, item in ranked if iou >= .5 and item.episode_type == gold["episode_type"]]
        any_half = [item for iou, item in ranked if iou >= .5]
        fragments = [item for item in predicted if item.episode_type == gold["episode_type"] and _intersection_coverage(item, gold) >= .2]
        over_segmented = len(fragments) >= 2 and sum(_intersection_coverage(item, gold) for item in fragments) >= .5
        best_length = best.end_turn_index - best.start_turn_index + 1 if best else 0
        gold_length = gold["end_turn_index"] - gold["start_turn_index"] + 1
        under_segmented = bool(best and best_iou >= .5 and best_length > gold_length * 1.5)
        taxonomy = []
        if not correct:
            taxonomy.append("missed_episode")
        if over_segmented:
            taxonomy.append("over_segmentation")
        if under_segmented:
            taxonomy.append("under_segmentation")
        if any_half and not correct:
            taxonomy.append("wrong_episode_type")
        if correct and best_iou < 1.0 and not under_segmented:
            taxonomy.append("boundary_shift")
        gold_rows.append({
            "session_number": session["session_number"], "gold": gold,
            "predicted_spans": [item.model_dump(mode="json") for item in predicted],
            "best_predicted_span": best.model_dump(mode="json") if best else None,
            "best_span_iou": best_iou, "matched_at_iou_0_5_with_type": bool(correct),
            "over_segmented": over_segmented, "taxonomy": taxonomy,
        })
    invalid = [item for item in diagnostics if item.code == "invalid_episode"]
    removed_by_merge = sum(item.code == "fragments_consolidated" for item in diagnostics)
    removed_duplicates = sum(item.code == "duplicate_episode" for item in diagnostics)
    llm_candidate_count = len(predicted) + removed_by_merge + removed_duplicates + len(invalid)
    return gold_rows, len(invalid), len(predicted), llm_candidate_count


def aggregate(rows, invalid_count, predicted_count, llm_candidate_count, gold_count):
    any_half = [row for row in rows if row["best_span_iou"] >= .5]
    taxonomy = {}
    for label in ("missed_episode", "over_segmentation", "under_segmentation", "wrong_episode_type", "boundary_shift"):
        taxonomy[label] = sum(label in row["taxonomy"] for row in rows)
    taxonomy["invalid_candidates"] = invalid_count
    return {
        "gold_episode_match_at_iou_0_5": sum(row["matched_at_iou_0_5_with_type"] for row in rows) / gold_count,
        "mean_best_span_iou": sum(row["best_span_iou"] for row in rows) / gold_count,
        "episode_type_accuracy": sum(row["matched_at_iou_0_5_with_type"] for row in any_half) / len(any_half) if any_half else 0.0,
        "invalid_candidate_rate": invalid_count / max(1, llm_candidate_count),
        "over_segmentation_rate": taxonomy["over_segmentation"] / gold_count,
        "under_segmentation_rate": taxonomy["under_segmentation"] / gold_count,
        "boundary_shift_rate": taxonomy["boundary_shift"] / gold_count,
        "missed_episode_rate": taxonomy["missed_episode"] / gold_count,
        "predicted_to_gold_ratio": predicted_count / gold_count,
        "predicted_episode_count": predicted_count, "gold_episode_count": gold_count,
        "error_taxonomy": taxonomy,
    }


def markdown_table(before_rows, after_rows):
    lines = [
        "# Gold episode boundary analysis", "",
        "| Session | Gold span/type | Before predicted spans | Before best IoU | Before errors | After predicted spans | After best IoU | After errors |",
        "|---:|---|---|---:|---|---|---:|---|",
    ]
    for before, after in zip(before_rows, after_rows, strict=True):
        def spans(row):
            return "; ".join(f'{item["start_turn_index"]}-{item["end_turn_index"]}/{item["episode_type"]}' for item in row["predicted_spans"])
        gold = before["gold"]
        lines.append(
            f'| {before["session_number"]} | {gold["start_turn_index"]}-{gold["end_turn_index"]}/{gold["episode_type"]} '
            f'| {spans(before)} | {before["best_span_iou"]:.3f} | {", ".join(before["taxonomy"]) or "-"} '
            f'| {spans(after)} | {after["best_span_iou"]:.3f} | {", ".join(after["taxonomy"]) or "-"} |'
        )
    return "\n".join(lines) + "\n"


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

        def task(mode_session):
            mode, session = mode_session
            turns = evidence_storage.get_transcript_turns(
                user_id=corpus["user_id"], case_id=corpus["case_id"], session_id=session["session_id"],
            )
            extractor = evidence_extraction._invoke_legacy_structured_extractor if mode == "before" else None
            spans, diagnostics = evidence_extraction._extract_with_diagnostics(
                turns=turns, extractor=extractor, consolidate_fragments=mode == "after",
            )
            return mode, session["session_number"], spans, diagnostics

        jobs = [(mode, session) for mode in ("before", "after") for session in corpus["sessions"]]
        with ThreadPoolExecutor(max_workers=16) as executor:
            outputs = list(executor.map(task, jobs))

    indexed = {(mode, number): (spans, diagnostics) for mode, number, spans, diagnostics in outputs}
    analyzed = {"before": [], "after": []}
    counts = {
        "before": {"invalid": 0, "predicted": 0, "llm_candidates": 0},
        "after": {"invalid": 0, "predicted": 0, "llm_candidates": 0},
    }
    for mode in ("before", "after"):
        for session in corpus["sessions"]:
            rows, invalid, predicted, llm_candidates = analyze_session(session, *indexed[(mode, session["session_number"])])
            analyzed[mode].extend(rows)
            counts[mode]["invalid"] += invalid
            counts[mode]["predicted"] += predicted
            counts[mode]["llm_candidates"] += llm_candidates
    gold_count = sum(len(session["gold_episodes"]) for session in corpus["sessions"])
    report = {
        "description": corpus["description"], "model": settings.openai_model, "gold_episode_count": gold_count,
        "before": {"metrics": aggregate(analyzed["before"], counts["before"]["invalid"], counts["before"]["predicted"], counts["before"]["llm_candidates"], gold_count), "episodes": analyzed["before"]},
        "after": {"metrics": aggregate(analyzed["after"], counts["after"]["invalid"], counts["after"]["predicted"], counts["after"]["llm_candidates"], gold_count), "episodes": analyzed["after"]},
    }
    (output_dir / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "gold_episode_table.md").write_text(markdown_table(analyzed["before"], analyzed["after"]), encoding="utf-8")
    print(json.dumps({"before": report["before"]["metrics"], "after": report["after"]["metrics"]}, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    run()
