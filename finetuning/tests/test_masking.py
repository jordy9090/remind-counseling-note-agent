"""Assistant-only loss masking tests (CPU, tokenizer only — no model download).

Run before every training run:
  python -m unittest finetuning.tests.test_masking -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from transformers import AutoTokenizer

from finetuning.train.train_qlora import build_features, render_prompt

TOKENIZER_ID = "Qwen/Qwen3-0.6B"  # same family/template as the 14B target

SAMPLE = {
    "messages": [
        {"role": "system", "content": "당신은 상담 문서화 보조 AI입니다."},
        {
            "role": "user",
            "content": "다음 회기 자료로 회기요약 초안을 생성하세요.\n\n축어록:\n상담사: 오늘 기분이 어떠셨나요?\n내담자: 요즘 잠을 잘 못 자요.",
        },
        {
            "role": "assistant",
            "content": json.dumps(
                {"session_info": {"case_id": "c1"}, "presenting_problem": {"text": "수면 문제 호소"}},
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]
}


def load_sample() -> dict:
    """Use a real training example when available, else the synthetic sample."""
    path = Path(__file__).resolve().parents[1] / "data" / "processed" / "sft_train.jsonl"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.loads(f.readline())
    return SAMPLE


class MaskingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_ID)
        cls.example = load_sample()
        cls.features = build_features(cls.example, cls.tokenizer, max_len=1_000_000)

    def test_transcript_tokens_are_fully_masked(self) -> None:
        """system prompt와 user 축어록 구간의 label은 전부 -100이어야 한다."""
        prompt_ids = self.tokenizer(
            render_prompt(self.tokenizer, self.example["messages"][:-1]),
            add_special_tokens=False,
        )["input_ids"]
        prompt_labels = self.features["labels"][: len(prompt_ids)]
        self.assertTrue(all(label == -100 for label in prompt_labels))

    def test_assistant_json_tokens_are_unmasked(self) -> None:
        """unmask된 label을 디코드하면 정확히 assistant JSON + eos여야 한다."""
        target_ids = [label for label in self.features["labels"] if label != -100]
        decoded = self.tokenizer.decode(target_ids, skip_special_tokens=False)
        expected = self.example["messages"][-1]["content"] + self.tokenizer.eos_token
        self.assertEqual(decoded, expected)
        self.assertTrue(decoded.lstrip().startswith("{"))

    def test_labels_align_with_input_ids(self) -> None:
        """unmask 위치의 label은 input_ids와 완전히 일치해야 한다 (shift는 모델 내부 처리)."""
        for input_id, label in zip(self.features["input_ids"], self.features["labels"]):
            if label != -100:
                self.assertEqual(input_id, label)

    def test_loss_covers_target_only(self) -> None:
        """전체 시퀀스 중 loss 대상은 타깃 토큰 수와 같고, 프롬프트가 대부분 마스킹된다."""
        n_unmasked = sum(1 for label in self.features["labels"] if label != -100)
        target_ids = self.tokenizer(
            self.example["messages"][-1]["content"] + self.tokenizer.eos_token,
            add_special_tokens=False,
        )["input_ids"]
        self.assertEqual(n_unmasked, len(target_ids))
        self.assertLess(n_unmasked, len(self.features["labels"]))

    def test_prompt_matches_inference_format(self) -> None:
        """학습 프롬프트는 eval의 생성 프롬프트와 동일해야 한다 (Qwen3 non-thinking)."""
        prompt_text = render_prompt(self.tokenizer, self.example["messages"][:-1])
        if "enable_thinking" in (self.tokenizer.chat_template or ""):
            self.assertTrue(prompt_text.endswith("<think>\n\n</think>\n\n"))
        else:
            self.assertTrue(prompt_text.rstrip("\n").endswith("<|im_start|>assistant"))

    def test_qwen3_template_has_no_generation_marker(self) -> None:
        """trl assistant_only_loss가 Qwen3에서 동작하지 않는 이유를 고정해 두는 테스트."""
        template = self.tokenizer.chat_template or ""
        self.assertNotIn("{% generation %}", template)
        self.assertNotIn("{%- generation %}", template)

    def test_overlong_example_is_dropped_not_truncated(self) -> None:
        self.assertIsNone(build_features(self.example, self.tokenizer, max_len=10))


if __name__ == "__main__":
    unittest.main()
