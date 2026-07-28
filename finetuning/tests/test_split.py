"""Split integrity tests over the generated sft_*.jsonl files.

Run after data/build_sft_dataset.py:
  python -m unittest finetuning.tests.test_split -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"
SPLITS = ("train", "val", "test")


def load_split(name: str) -> list[dict]:
    path = PROCESSED / f"sft_{name}.jsonl"
    if not path.exists():
        raise unittest.SkipTest(f"{path} not found — run data/build_sft_dataset.py first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class SplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.splits = {name: load_split(name) for name in SPLITS}

    def test_no_case_overlap_between_splits(self) -> None:
        """같은 내담자(case)의 회기가 두 split에 걸치면 leakage — 반드시 0이어야 한다."""
        case_sets = {
            name: {example["meta"]["case_id"] for example in examples}
            for name, examples in self.splits.items()
        }
        for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
            overlap = case_sets[a] & case_sets[b]
            self.assertEqual(overlap, set(), f"case overlap between {a} and {b}: {sorted(overlap)[:5]}")

    def test_no_duplicate_example_ids(self) -> None:
        ids = [e["meta"]["id"] for examples in self.splits.values() for e in examples]
        duplicates = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(len(ids), len(set(ids)), f"duplicate example ids: {sorted(duplicates)[:5]}")

    def test_every_example_has_case_id_and_three_messages(self) -> None:
        for name, examples in self.splits.items():
            for example in examples:
                self.assertTrue(example["meta"].get("case_id"), f"{name}: missing case_id")
                self.assertEqual(len(example["messages"]), 3, f"{name}: expected 3 messages")
                self.assertEqual(example["messages"][2]["role"], "assistant")

    def test_assistant_targets_are_valid_json_notes(self) -> None:
        for name, examples in self.splits.items():
            for example in examples:
                note = json.loads(example["messages"][2]["content"])
                self.assertIn("session_info", note, f"{name}: target missing session_info")

    def test_split_ratios_are_roughly_80_10_10(self) -> None:
        total = sum(len(v) for v in self.splits.values())
        self.assertGreater(total, 0)
        self.assertGreater(len(self.splits["train"]) / total, 0.7)
        for name in ("val", "test"):
            self.assertGreater(len(self.splits[name]) / total, 0.05)


if __name__ == "__main__":
    unittest.main()
