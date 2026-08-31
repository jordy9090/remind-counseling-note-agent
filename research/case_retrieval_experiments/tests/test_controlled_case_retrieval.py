import json
from pathlib import Path

from research.case_retrieval_experiments.scripts.evaluate_case_retrieval_controlled import (
    LocalEvaluationStorage,
    cosine_similarity,
    metrics,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "case_retrieval_controlled_corpus.json"


def test_controlled_corpus_has_eight_sessions_and_seven_fields_each():
    corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
    expected_fields = {
        "session_theme", "presenting_problem", "session_content", "counselor_intervention",
        "client_response", "reflection", "next_plan",
    }
    assert len(corpus["sessions"]) == 8
    assert all(set(session["sections"]) == expected_fields for session in corpus["sessions"])


def test_metrics_measure_session_redundancy_and_recall():
    rows = [
        {"session_number": 3, "field_type": "session_content"},
        {"session_number": 3, "field_type": "counselor_intervention"},
        {"session_number": 5, "field_type": "client_response"},
        {"session_number": 5, "field_type": "reflection"},
        {"session_number": 7, "field_type": "next_plan"},
    ]
    result = metrics(rows, [3, 5, 6])
    assert result["hit_at_5"] is True
    assert result["relevant_session_recall_at_5"] == 2 / 3
    assert result["unique_sessions_at_5"] == 3
    assert result["same_session_redundancy"] == 2 / 5


def test_local_storage_enforces_rpc_top_five():
    corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
    storage = LocalEvaluationStorage(corpus)
    storage.case_memory_chunks = [
        {"id": f"c{i}", "counselor_id": storage.actor, "case_id": storage.case_id, "embedding": [1.0, 0.0],
         "session_number": i, "created_at": str(i), "field_type": "reflection", "metadata_json": {}}
        for i in range(1, 9)
    ]
    rows = storage.rpc("match_case_memory_chunks", {
        "query_embedding": [1.0, 0.0], "filter_counselor_id": storage.actor,
        "filter_case_id": storage.case_id, "filter_field_types": None, "match_count": 99,
    })
    assert len(rows) == 5
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
