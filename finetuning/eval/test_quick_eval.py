"""Lightweight quick-eval tests; no model or checkpoint downloads."""
from __future__ import annotations

import copy
import json
import unittest

from lmformatenforcer import CharacterLevelParserConfig, JsonSchemaParser

from finetuning.eval.note_schema import COUNSELING_NOTE_SCHEMA, NOTE_SECTIONS
from finetuning.eval.quick_eval import (
    GENERATION_INSTRUCTION,
    check_note,
    detect_repetition,
    evaluate_text,
    extract_json,
    generate_note_text,
    json_string_alphabet,
    prepare_prompt_messages,
    summarize_results,
)


def valid_note() -> dict:
    section = {
        "text": "내담자는 최근 불안 상황과 대처 경험을 설명했다.",
        "evidence_type": "direct",
        "source_refs": ["transcript_text"],
        "requires_review": False,
    }
    note = {
        "session_info": {
            "case_id": "CASE-001",
            "session_number": 3,
            "session_date": "2026-07-18",
            "counselor_name": "박상담사",
        },
        **{name: copy.deepcopy(section) for name in NOTE_SECTIONS},
    }
    note["reflection"] = {
        "text": "상담자가 직접 작성하거나 확인해야 합니다.",
        "evidence_type": "counselor_input",
        "source_refs": [],
        "requires_review": True,
    }
    return note


class FakeTensor:
    def __init__(self, values: list[int]) -> None:
        self.values = values
        self.shape = (1, len(values))
        self.device = None

    def to(self, device: str) -> "FakeTensor":
        self.device = device
        return self


class FakeTokenizer:
    eos_token_id = 2
    pad_token_id = None

    def __init__(self) -> None:
        self.template_kwargs = None
        self.input_ids = FakeTensor([1, 2, 3])
        self.attention_mask = FakeTensor([1, 1, 1])

    def apply_chat_template(self, messages, **kwargs):
        self.template_kwargs = kwargs
        return "rendered prompt"

    def __call__(self, text, return_tensors):
        return {"input_ids": self.input_ids, "attention_mask": self.attention_mask}

    def decode(self, token_ids, skip_special_tokens):
        return '{"ok": true}'


class FakeModel:
    device = "cuda:0"

    def __init__(self) -> None:
        self.generate_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return [[1, 2, 3, 99]]


class SchemaTests(unittest.TestCase):
    def test_json_string_alphabet_keeps_korean_and_removes_raw_controls(self) -> None:
        self.assertEqual(json_string_alphabet("A한\n\t\x00글"), "A한글")

    def test_schema_is_accepted_by_lm_format_enforcer(self) -> None:
        parser = JsonSchemaParser(COUNSELING_NOTE_SCHEMA)
        self.assertIn("{", parser.get_allowed_characters())

    def test_lm_format_enforcer_accepts_a_complete_korean_note(self) -> None:
        payload = json.dumps(valid_note(), ensure_ascii=False, separators=(",", ":"))
        parser = JsonSchemaParser(
            COUNSELING_NOTE_SCHEMA,
            config=CharacterLevelParserConfig(alphabet="".join(sorted(set(payload)))),
        )
        for character in payload:
            self.assertIn(character, parser.get_allowed_characters())
            parser = parser.add_character(character)
        self.assertTrue(parser.can_end())

    def test_complete_note_is_schema_valid(self) -> None:
        self.assertEqual(check_note(valid_note()), [])

    def test_invalid_evidence_and_missing_key_are_rejected(self) -> None:
        note = valid_note()
        note["session_theme"]["evidence_type"] = "invented"
        del note["next_plan"]["source_refs"]
        problems = " ".join(check_note(note))
        self.assertIn("session_theme", problems)
        self.assertIn("next_plan", problems)

    def test_maximum_text_length_is_enforced(self) -> None:
        note = valid_note()
        note["session_theme"]["text"] = "가" * 201
        self.assertTrue(check_note(note))

    def test_reflection_must_remain_counselor_input(self) -> None:
        note = valid_note()
        note["reflection"]["evidence_type"] = "direct"
        note["reflection"]["requires_review"] = False
        self.assertTrue(check_note(note))


class EvaluationTests(unittest.TestCase):
    def test_strict_json_parse_rejects_extra_closing_bracket(self) -> None:
        payload = json.dumps(valid_note(), ensure_ascii=False)
        self.assertIsNotNone(extract_json(payload))
        self.assertIsNone(extract_json(payload + "]"))

    def test_repetition_detection_finds_repeated_korean_sentence(self) -> None:
        repeated = "같은 문장을 계속 반복하고 있습니다. " * 4
        self.assertTrue(detect_repetition(repeated))
        self.assertFalse(detect_repetition("첫 문장입니다. 이어지는 내용은 서로 다릅니다."))

    def test_evaluation_result_and_metrics(self) -> None:
        valid = evaluate_text(json.dumps(valid_note(), ensure_ascii=False))
        invalid = evaluate_text('{"broken": ]')
        metrics = summarize_results([valid, invalid])
        self.assertEqual(valid["parse_status"], "valid")
        self.assertEqual(valid["schema_status"], "valid")
        self.assertEqual(invalid["parse_status"], "invalid")
        self.assertEqual(metrics["json_valid_rate"], 0.5)
        self.assertEqual(metrics["schema_valid_rate"], 0.5)

    def test_prompt_instruction_is_appended_without_mutating_example(self) -> None:
        example = {
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "input"},
                {"role": "assistant", "content": "target"},
            ]
        }
        messages = prepare_prompt_messages(example)
        self.assertIn(GENERATION_INSTRUCTION, messages[-1]["content"])
        self.assertEqual(example["messages"][1]["content"], "input")

    def test_generation_passes_attention_mask_and_disables_thinking(self) -> None:
        model = FakeModel()
        tokenizer = FakeTokenizer()
        prefix_function = object()
        text = generate_note_text(
            model,
            tokenizer,
            [{"role": "user", "content": "input"}],
            max_new_tokens=128,
            prefix_allowed_tokens_fn=prefix_function,
        )
        self.assertEqual(text, '{"ok": true}')
        self.assertFalse(tokenizer.template_kwargs["enable_thinking"])
        self.assertIs(model.generate_kwargs["input_ids"], tokenizer.input_ids)
        self.assertIs(model.generate_kwargs["attention_mask"], tokenizer.attention_mask)
        self.assertIs(model.generate_kwargs["prefix_allowed_tokens_fn"], prefix_function)


if __name__ == "__main__":
    unittest.main()
