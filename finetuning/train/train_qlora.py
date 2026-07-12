"""QLoRA supervised fine-tuning for the Re:mind session-note task.

Runs anywhere with a CUDA GPU (Colab T4/L4/A100, RunPod, etc.):

  pip install -r finetuning/requirements-train.txt
  python finetuning/train/train_qlora.py --config finetuning/configs/qlora_qwen25_7b.yaml

The dataset is the chat-format JSONL produced by data/build_sft_dataset.py.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch
import yaml
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    data_dir = Path(cfg["data_dir"])
    dataset = load_dataset(
        "json",
        data_files={
            "train": str(data_dir / "sft_train.jsonl"),
            "validation": str(data_dir / "sft_val.jsonl"),
        },
    )
    # SFTTrainer consumes the "messages" column; drop everything else.
    dataset = dataset.remove_columns([c for c in dataset["train"].column_names if c != "messages"])

    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        cfg["base_model"],
        quantization_config=quant_config,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation=cfg.get("attn_implementation", "sdpa"),
    )
    tokenizer = AutoTokenizer.from_pretrained(cfg["base_model"])

    # 20k 시퀀스에서는 loss 계산 시 logits(vocab 152k x seq)이 10GB+를 차지한다.
    # Liger 커널의 fused cross-entropy가 이를 제거하므로 긴 컨텍스트 학습에 사실상 필수.
    use_liger = cfg.get("use_liger", True)
    if use_liger:
        try:
            import liger_kernel  # noqa: F401
        except ImportError:
            use_liger = False
            print("WARNING: liger-kernel not installed; falling back (OOM risk at long seq). pip install liger-kernel")

    lora_config = LoraConfig(
        r=cfg["lora"]["r"],
        lora_alpha=cfg["lora"]["alpha"],
        lora_dropout=cfg["lora"]["dropout"],
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=cfg["lora"]["target_modules"],
    )

    training_args = SFTConfig(
        output_dir=cfg["output_dir"],
        num_train_epochs=cfg["epochs"],
        per_device_train_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["gradient_accumulation"],
        gradient_checkpointing=True,
        learning_rate=cfg["learning_rate"],
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        max_length=cfg["max_seq_length"],
        packing=False,
        bf16=True,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=cfg.get("eval_steps", 100),
        save_strategy="steps",
        save_steps=cfg.get("save_steps", 200),
        save_total_limit=2,
        report_to=cfg.get("report_to", "none"),
        seed=42,
        use_liger_kernel=use_liger,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        processing_class=tokenizer,
        peft_config=lora_config,
    )
    trainer.train()
    trainer.save_model(cfg["output_dir"])
    tokenizer.save_pretrained(cfg["output_dir"])
    print(f"LoRA adapter saved to {cfg['output_dir']}")


if __name__ == "__main__":
    main()
