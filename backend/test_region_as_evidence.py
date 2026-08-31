import json
import unittest
from pathlib import Path

from scripts.evaluate_region_as_evidence import TOP_K_VALUES, evaluate, evaluate_units


SOURCE = Path(__file__).parents[1] / "results" / "debug" / "raw_window_selection" / "evaluation.json"


class RegionAsEvidenceTests(unittest.TestCase):
    def test_top_k_metric_uses_full_span_containment_and_all_gold_query_success(self):
        queries = [{
            "id": "q", "gold_episodes": [
                {"session_number": 1, "start_turn_index": 1, "end_turn_index": 3},
                {"session_number": 2, "start_turn_index": 0, "end_turn_index": 2},
            ],
            "regions": [
                {"session_number": 1, "start_turn_index": 1, "end_turn_index": 3},
                {"session_number": 2, "start_turn_index": 1, "end_turn_index": 2},
                {"session_number": 2, "start_turn_index": 0, "end_turn_index": 2},
            ],
        }]
        at_one = evaluate_units(queries, unit_key="regions", k=1)
        at_three = evaluate_units(queries, unit_key="regions", k=3)
        self.assertEqual(at_one["contained_gold_span_count"], 1)
        self.assertEqual(at_one["successful_query_count"], 0)
        self.assertEqual(at_three["contained_gold_span_count"], 2)
        self.assertEqual(at_three["successful_query_count"], 1)

    def test_precision_proxy_is_explicitly_not_human_precision(self):
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        metrics = evaluate_units(source["queries"], unit_key="regions", k=5)
        self.assertIn("not human relevance precision", metrics["precision_proxy"]["description"])

    def test_saved_artifact_evaluation_has_all_k_examples_and_no_selector_rerun(self):
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        report = evaluate(source)
        self.assertEqual(set(report["top_k_region_metrics"]), {str(item) for item in TOP_K_VALUES})
        self.assertEqual(len(report["representative_top_5_raw_regions"]), 4)
        self.assertEqual(report["llm_calls"], 0)
        self.assertFalse(report["selector_used"])
        self.assertFalse(report["selector_reference_only"]["selector_rerun"])


if __name__ == "__main__":
    unittest.main()
