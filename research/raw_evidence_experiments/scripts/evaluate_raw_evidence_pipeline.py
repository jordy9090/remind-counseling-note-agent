"""Offline PR2 evaluation: extraction quality and gold-corpus dense retrieval quality."""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
for import_root in (REPO_ROOT, BACKEND_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.core.config import settings  # noqa: E402
from app.schemas.evidence import TranscriptTurn  # noqa: E402
from app.services import transcript_storage  # noqa: E402
from app.services.embeddings import clear_embedding_cache  # noqa: E402
from research.raw_evidence_experiments import storage as evidence_storage  # noqa: E402
from research.raw_evidence_experiments.schemas import EvidenceEpisodeSpan, RetrievedEvidenceEpisode  # noqa: E402
from research.raw_evidence_experiments.services import evidence_extraction, evidence_retrieval  # noqa: E402

DEFAULT_FIXTURE = REPO_ROOT / "research" / "raw_evidence_experiments" / "fixtures" / "synthetic_raw_dialogue_longitudinal.json"
DEFAULT_OUTPUT = REPO_ROOT / "results" / "debug" / "raw_evidence_pipeline"


class LocalRawEvidenceStorage:
    def __init__(self, corpus: dict[str, Any]):
        self.sessions = [{
            "id": session["session_id"], "user_id": corpus["user_id"], "case_id": corpus["case_id"],
            "session_number": session["session_number"], "session_date": f'2026-03-{session["session_number"]:02d}',
        } for session in corpus["sessions"]]
        self.transcript_turns: list[dict[str, Any]] = []
        self.evidence_episodes: list[dict[str, Any]] = []

    def maybe_single(self, table, query):
        rows = self.select(table, query)
        return rows[0] if rows else None

    def select(self, table, query):
        rows = list(getattr(self, table))
        for key, condition in query.items():
            if key in {"select", "order", "limit"}:
                continue
            value = str(condition)
            if value.startswith("eq."):
                rows = [row for row in rows if str(row.get(key) or "") == value[3:]]
        if query.get("order") == "turn_index.asc":
            rows.sort(key=lambda row: row["turn_index"])
        return rows[: int(query.get("limit") or len(rows))]

    def upsert(self, table, rows, *, on_conflict):
        target = getattr(self, table)
        keys = on_conflict.split(",")
        result = []
        for incoming in rows:
            existing = next((row for row in target if all(row.get(key) == incoming.get(key) for key in keys)), None)
            if existing is None:
                existing = {"id": f"{table}-{len(target) + 1}", **incoming}
                target.append(existing)
            else:
                existing.update(incoming)
            result.append(existing)
        return result

    def update(self, table, values, *, query, return_representation=True):
        rows = self.select(table, query)
        for row in rows:
            row.update(values)
        return rows if return_representation else []

    def rpc(self, name, params):
        if name != "match_evidence_episodes":
            raise AssertionError(name)
        allowed = params.get("filter_episode_types")
        rows = [row for row in self.evidence_episodes if
                row["user_id"] == params["filter_user_id"] and row["case_id"] == params["filter_case_id"]
                and row.get("embedding") and (not allowed or row["episode_type"] in allowed)]
        for row in rows:
            row["_score"] = cosine(row["embedding"], params["query_embedding"])
        rows.sort(key=lambda row: row["_score"], reverse=True)
        sessions = {row["id"]: row for row in self.sessions}
        return [{
            "episode_id": row["id"], "session_id": row["session_id"],
            "session_number": sessions[row["session_id"]]["session_number"],
            "episode_type": row["episode_type"], "start_turn_index": row["start_turn_index"],
            "end_turn_index": row["end_turn_index"], "source_ref": row["source_ref"],
            "episode_text": row["episode_text"], "similarity_score": row["_score"],
            "retrieval_method": "evidence_episode_dense", "metadata": row.get("metadata_json") or {},
        } for row in rows[: min(max(int(params.get("match_count") or 12), 1), 50)]]


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        (math.sqrt(sum(x * x for x in left)) or 1) * (math.sqrt(sum(x * x for x in right)) or 1)
    )


@contextmanager
def patched_storage(local) -> Iterator[None]:
    originals = (
        evidence_storage.storage,
        transcript_storage.storage,
        evidence_extraction.storage,
        evidence_retrieval.storage,
    )
    try:
        evidence_storage.storage = transcript_storage.storage = evidence_extraction.storage = evidence_retrieval.storage = local
        clear_embedding_cache()
        yield
    finally:
        evidence_storage.storage, transcript_storage.storage, evidence_extraction.storage, evidence_retrieval.storage = originals
        clear_embedding_cache()


def span_overlap(start_a, end_a, start_b, end_b):
    intersection = max(0, min(end_a, end_b) - max(start_a, start_b) + 1)
    shorter = min(end_a - start_a + 1, end_b - start_b + 1)
    return intersection / shorter if shorter else 0.0


def gold_match(item, gold, threshold=.7):
    return (item.session_number == gold["session_number"] and item.episode_type == gold["episode_type"]
            and span_overlap(item.start_turn_index, item.end_turn_index, gold["start_turn_index"], gold["end_turn_index"]) >= threshold)


def result_metrics(results, golds):
    matched = {i for i, gold in enumerate(golds) if any(gold_match(item, gold) for item in results)}
    relevant_sessions = {gold["session_number"] for gold in golds}
    retrieved_sessions = {item.session_number for item in results}
    redundant = 0
    for index, item in enumerate(results):
        if any((item.source_ref == previous.source_ref and item.episode_type == previous.episode_type)
               or evidence_retrieval.span_overlap_ratio(item, previous) >= .7 for previous in results[:index]):
            redundant += 1
    return {
        "direct_episode_hit_at_1": bool(results and any(gold_match(results[0], gold) for gold in golds)),
        "episode_hit_at_5": bool(matched), "episode_recall_at_5": len(matched) / len(golds),
        "session_recall_at_5": len(relevant_sessions & retrieved_sessions) / len(relevant_sessions),
        "unique_sessions_at_5": len(retrieved_sessions),
        "duplicate_overlap_rate": redundant / len(results) if results else 0.0,
        "episode_type_distribution": dict(Counter(item.episode_type for item in results)),
    }


def aggregate(evaluations, key):
    metrics = [item[key]["metrics"] for item in evaluations]
    names = ("direct_episode_hit_at_1", "episode_hit_at_5", "episode_recall_at_5", "session_recall_at_5", "unique_sessions_at_5", "duplicate_overlap_rate")
    result = {name: sum(row[name] for row in metrics) / len(metrics) for name in names}
    result["episode_type_distribution"] = dict(Counter(
        episode_type
        for row in metrics
        for episode_type, count in row["episode_type_distribution"].items()
        for _ in range(count)
    ))
    return result


def run(fixture_path: Path, output_dir: Path):
    corpus = json.loads(fixture_path.read_text(encoding="utf-8"))
    local = LocalRawEvidenceStorage(corpus)
    output_dir.mkdir(parents=True, exist_ok=True)
    extraction_rows = []
    with patched_storage(local):
        # Store all sanitized raw turns through PR1.
        for session in corpus["sessions"]:
            evidence_storage.store_transcript_turns(
                user_id=corpus["user_id"], counselor_id=corpus["counselor_id"], case_id=corpus["case_id"],
                session_id=session["session_id"], turns=[TranscriptTurn.model_validate(turn) for turn in session["turns"]],
            )
        def evaluate_extraction(session):
            turns = evidence_storage.get_transcript_turns(
                user_id=corpus["user_id"], case_id=corpus["case_id"], session_id=session["session_id"],
            )
            try:
                spans, diagnostics = evidence_extraction._extract_with_diagnostics(
                    turns=turns, extractor=None, consolidate_fragments=False,
                )
                overlapped_gold_count = sum(any(
                    span_overlap(predicted.start_turn_index, predicted.end_turn_index, gold["start_turn_index"], gold["end_turn_index"]) >= .7
                    for predicted in spans
                ) for gold in session["gold_episodes"])
                matched = sum(any(
                    predicted.episode_type == gold["episode_type"] and
                    span_overlap(predicted.start_turn_index, predicted.end_turn_index, gold["start_turn_index"], gold["end_turn_index"]) >= .7
                    for predicted in spans
                ) for gold in session["gold_episodes"])
                return {
                    "session_number": session["session_number"], "predicted": [span.model_dump() for span in spans],
                    "gold_count": len(session["gold_episodes"]), "matched_gold_count": matched,
                    "gold_recall": matched / len(session["gold_episodes"]),
                    "invalid_span_count": sum(item.code == "invalid_episode" for item in diagnostics),
                    "invalid_span_rate": sum(item.code == "invalid_episode" for item in diagnostics) / max(1, len(spans) + sum(item.code == "invalid_episode" for item in diagnostics)),
                    "episode_type_correctness": matched / overlapped_gold_count if overlapped_gold_count else None,
                    "diagnostics": [item.model_dump() for item in diagnostics],
                }
            except Exception as error:
                return {"session_number": session["session_number"], "error": str(error), "gold_recall": 0.0, "invalid_span_count": 0, "invalid_span_rate": 0.0, "episode_type_correctness": None}

        # Extraction quality is independent of retrieval and can be evaluated concurrently.
        with ThreadPoolExecutor(max_workers=8) as executor:
            extraction_rows = sorted(executor.map(evaluate_extraction, corpus["sessions"]), key=lambda row: row["session_number"])

        # Retrieval quality uses only gold/confirmed episodes, never extractor output.
        for session in corpus["sessions"]:
            for raw_span in session["gold_episodes"]:
                episode = evidence_storage.create_evidence_episode_from_span(
                    user_id=corpus["user_id"], counselor_id=corpus["counselor_id"], case_id=corpus["case_id"],
                    session_id=session["session_id"], span=EvidenceEpisodeSpan.model_validate(raw_span),
                )
                evidence_extraction._ensure_episode_embedding(episode.model_dump(mode="json"))

        evaluations = []
        for query in corpus["queries"]:
            candidates = evidence_retrieval.retrieve_evidence_episodes(
                query_text=query["query"], user_id=corpus["user_id"], case_id=corpus["case_id"], candidate_k=12,
            )
            raw = candidates[:5]
            diversified = evidence_retrieval.diversify_evidence_episodes(candidates, max_results=5, max_per_session=2)
            row = {
                "id": query["id"], "query": query["query"], "gold_episodes": query["gold_episodes"],
                "raw_dense_top_5": {"results": [item.model_dump() for item in raw], "metrics": result_metrics(raw, query["gold_episodes"])},
                "diversified_dense_top_5": {"results": [item.model_dump() for item in diversified], "metrics": result_metrics(diversified, query["gold_episodes"])},
            }
            evaluations.append(row)
            (output_dir / f'{query["id"]}.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")

    extraction_summary = {
        "session_count": len(extraction_rows),
        "mean_gold_span_recall": sum(row["gold_recall"] for row in extraction_rows) / len(extraction_rows),
        "invalid_span_count": sum(row["invalid_span_count"] for row in extraction_rows),
        "mean_invalid_span_rate": sum(row["invalid_span_rate"] for row in extraction_rows) / len(extraction_rows),
        "mean_episode_type_correctness": sum(row["episode_type_correctness"] for row in extraction_rows if row["episode_type_correctness"] is not None) / max(1, sum(row["episode_type_correctness"] is not None for row in extraction_rows)),
        "sessions_with_errors": sum("error" in row for row in extraction_rows),
    }
    summary = {
        "description": corpus["description"], "extraction_model": settings.openai_model,
        "embedding_model": settings.embedding_model,
        "corpus": {"sessions": len(corpus["sessions"]), "turns": len(local.transcript_turns),
                   "gold_episodes": len(local.evidence_episodes),
                   "episode_type_distribution": dict(Counter(row["episode_type"] for row in local.evidence_episodes))},
        "extraction_evaluation": {"summary": extraction_summary, "sessions": extraction_rows},
        "retrieval_evaluation": {
            "raw_dense_top_5": aggregate(evaluations, "raw_dense_top_5"),
            "diversified_dense_top_5": aggregate(evaluations, "diversified_dense_top_5"),
            "queries": evaluations,
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"corpus": summary["corpus"], "extraction": extraction_summary,
                      "retrieval": summary["retrieval_evaluation"] | {"queries": f"{len(evaluations)} query artifacts"}}, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run(DEFAULT_FIXTURE, DEFAULT_OUTPUT)
