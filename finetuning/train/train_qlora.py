"""QLoRA supervised fine-tuning for the Re:mind session-note task.

Loss is computed on the assistant note JSON only ("assistant-only loss"):
the prompt (system + user transcript) is tokenized exactly as at inference
time (`add_generation_prompt=True, enable_thinking=False`) and fully masked
with -100; the target is the assistant JSON + <|im_end|>.

trl's `assistant_only_loss=True` is NOT used on purpose — the Qwen3 chat
template has no `{% generation %}` markers, so trl cannot build an assistant
token mask for it. This script depends only on transformers + peft.

  python finetuning/train/train_qlora.py --config finetuning/configs/qlora_qwen3_14b.yaml
  python finetuning/train/train_qlora.py --config finetuning/configs/qlora_qwen3_smoke.yaml --smoke 15

Verify masking before any training run:
  python -m unittest finetuning.tests.test_masking -v
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def render_prompt(tokenizer: Any, messages: list[dict[str, str]]) -> str:
    """Render the inference-time prompt (system+user, generation prefix, no thinking)."""
    kwargs: dict[str, Any] = {"tokenize": False, "add_generation_prompt": True}
    if "enable_thinking" in (tokenizer.chat_template or ""):
        kwargs["enable_thinking"] = False
    return tokenizer.apply_chat_template(messages, **kwargs)


def build_features(
    example: dict[str, Any], tokenizer: Any, max_len: int
) -> dict[str, list[int]] | None:
    """Tokenize one chat example into input_ids/labels with the prompt masked.

    Prompt tokens are labeled -100 so loss covers only the assistant JSON and
    the closing <|im_end|>. Returns None when the sequence exceeds max_len
    (overlong examples are dropped, never truncated — truncation would cut the
    training target).
    """
    messages = example["messages"]
    assert messages[-1]["role"] == "assistant", "last message must be the assistant target"
    prompt_text = render_prompt(tokenizer, messages[:-1])
    target_text = messages[-1]["content"] + tokenizer.eos_token

    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    target_ids = tokenizer(target_text, add_special_tokens=False)["input_ids"]
    input_ids = prompt_ids + target_ids
    if len(input_ids) > max_len:
        return None
    return {
        "input_ids": input_ids,
        "attention_mask": [1] * len(input_ids),
        "labels": [-100] * len(prompt_ids) + target_ids,
    }


def load_examples(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def featurize(
    examples: list[dict[str, Any]], tokenizer: Any, max_len: int, name: str
) -> list[dict[str, list[int]]]:
    features = []
    dropped = 0
    for example in examples:
        feature = build_features(example, tokenizer, max_len)
        if feature is None:
            dropped += 1
            continue
        features.append(feature)
    print(f"{name}: {len(features)} examples ({dropped} dropped over {max_len} tokens)")
    if not features:
        raise SystemExit(f"FATAL: no {name} examples fit within max_seq_length={max_len}")
    return features


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--smoke",
        type=int,
        default=0,
        help="N이면 가장 짧은 N개 train 예시로 스모크 학습 (val은 최대 4개)",
    )
    args = parser.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    use_liger = cfg.get("use_liger", True)
    if use_liger:
        try:
            import liger_kernel  # noqa: F401
        except ImportError:
            use_liger = False
            print("WARNING: liger-kernel not installed; long-sequence training may OOM. pip install liger-kernel")

    tokenizer = AutoTokenizer.from_pretrained(cfg["base_model"])
    data_dir = Path(cfg["data_dir"])
    max_len = int(cfg["max_seq_length"])

    train_examples = load_examples(data_dir / "sft_train.jsonl")
    val_examples = load_examples(data_dir / "sft_val.jsonl")
    if args.smoke:
        train_examples.sort(key=lambda e: sum(len(m["content"]) for m in e["messages"]))
        train_examples = train_examples[: args.smoke]
        val_examples = sorted(
            val_examples, key=lambda e: sum(len(m["content"]) for m in e["messages"])
        )[:4]
        print(f"SMOKE MODE: {len(train_examples)} train / {len(val_examples)} val examples")

    train_features = featurize(train_examples, tokenizer, max_len, "train")
    val_features = featurize(val_examples, tokenizer, max_len, "val")
    train_dataset = Dataset.from_list(train_features)
    val_dataset = Dataset.from_list(val_features)

    # 마스킹 sanity check: 첫 예시에서 unmask 토큰이 JSON으로 시작하는지 확인
    first = train_features[0]
    target_ids = [t for t, l in zip(first["input_ids"], first["labels"]) if l != -100]
    decoded_target = tokenizer.decode(target_ids, skip_special_tokens=True).lstrip()
    masked_ratio = sum(1 for l in first["labels"] if l == -100) / len(first["labels"])
    print(f"sanity: masked {masked_ratio:.1%} of first example; target starts with {decoded_target[:20]!r}")
    if not decoded_target.startswith("{"):
        raise SystemExit("FATAL: unmasked target does not start with JSON — masking is broken.")

    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        cfg["base_model"],
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        ),
        torch_dtype=compute_dtype,
        device_map="auto",
        attn_implementation=cfg.get("attn_implementation", "sdpa"),
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(
        model,
        LoraConfig(
            r=cfg["lora"]["r"],
            lora_alpha=cfg["lora"]["alpha"],
            lora_dropout=cfg["lora"]["dropout"],
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=cfg["lora"]["target_modules"],
        ),
    )
    model.print_trainable_parameters()

    output_dir = cfg["output_dir"]
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=cfg.get("epochs", 2),
        max_steps=cfg.get("max_steps", -1),
        per_device_train_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["gradient_accumulation"],
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        learning_rate=float(cfg["learning_rate"]),
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=compute_dtype is torch.bfloat16,
        fp16=compute_dtype is torch.float16,
        logging_steps=cfg.get("logging_steps", 5),
        eval_strategy="steps",
        eval_steps=cfg.get("eval_steps", 100),
        save_strategy="steps",
        save_steps=cfg.get("save_steps", 200),
        save_total_limit=2,
        report_to=cfg.get("report_to", "none"),
        seed=42,
        use_liger_kernel=use_liger,
        remove_unused_columns=False,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        processing_class=tokenizer,
        data_collator=DataCollatorForSeq2Seq(
            tokenizer, padding=True, label_pad_token_id=-100, return_tensors="pt"
        ),
    )

    has_checkpoint = any(Path(output_dir).glob("checkpoint-*"))
    trainer.train(resume_from_checkpoint=has_checkpoint or None)
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"LoRA adapter saved to {output_dir}")


if __name__ == "__main__":
    main()
