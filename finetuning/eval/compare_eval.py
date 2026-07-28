"""Compare base model vs LoRA adapter on the same held-out test set.

Runs the constrained quick-eval twice (base, then base+adapter), writes
per-example JSONL for each run plus a side-by-side summary, and prints a
comparison table. Hallucination inspection uses each result's
`reference_note` + `generated_note` against the source transcript
(look up `example_id` in the test JSONL).

  python finetuning/eval/compare_eval.py \
      --base Qwen/Qwen3-14B \
      --adapter finetuning/output/qwen3-14b-remind-note-qlora-v2 \
      --limit 30
"""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

try:
    from .quick_eval import (
        build_constraint_factory,
        evaluate_text,
        extract_json,
        generate_note_text,
        generation_error_result,
        load_model_and_tokenizer,
        prepare_prompt_messages,
        summarize_results,
    )
except ImportError:
    from quick_eval import (  # type: ignore[no-redef]
        build_constraint_factory,
        evaluate_text,
        extract_json,
        generate_note_text,
        generation_error_result,
        load_model_and_tokenizer,
        prepare_prompt_messages,
        summarize_results,
    )

METRIC_ROWS = (
    ("json_valid_rate", "JSON-valid"),
    ("schema_valid_rate", "Schema-valid"),
    ("repetition_rate", "Repetition"),
    ("truncated_rate", "Truncated"),
    ("missing_section_rate", "Missing section"),
    ("korean_ratio", "Korean ratio"),
)


def run_eval(
    tag: str,
    base: str,
    adapter: str | None,
    examples: list[dict],
    max_new_tokens: int,
    out_dir: Path,
) -> dict:
    print(f"\n=== evaluating [{tag}] base={base} adapter={adapter or '-'} ===")
    model, tokenizer = load_model_and_tokenizer(base, adapter)
    constraint_factory = build_constraint_factory(tokenizer)
    results = []
    results_path = out_dir / f"compare_{tag}.jsonl"
    with results_path.open("w", encoding="utf-8") as output_file:
        for index, example in enumerate(examples, 1):
            try:
                text, truncated = generate_note_text(
                    model,
                    tokenizer,
                    prepare_prompt_messages(example),
                    max_new_tokens=max_new_tokens,
                    prefix_allowed_tokens_fn=constraint_factory(),
                )
                result = evaluate_text(text, truncated)
            except Exception as error:
                result = generation_error_result(error)
            meta = example.get("meta") or {}
            result = {
                "example_index": index,
                "example_id": meta.get("id"),
                "case_id": meta.get("case_id"),
                "reference_note": extract_json(example["messages"][-1]["content"]),
                **result,
            }
            results.append(result)
            output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
            output_file.flush()
            status = result["error"] or "ok"
            print(f"[{tag} {index}/{len(examples)}] {status}")

    # free VRAM before the next run
    del model
    gc.collect()
    try:
        import torch

        torch.cuda.empty_cache()
    except Exception:
        pass
    return summarize_results(results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--test", default="finetuning/data/processed/sft_test.jsonl")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--out-dir", default="finetuning/eval/results")
    args = parser.parse_args()

    examples = [
        json.loads(line)
        for line in Path(args.test).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][: args.limit]
    if not examples:
        raise SystemExit("No test examples found.")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = {
        "base": run_eval("base", args.base, None, examples, args.max_new_tokens, out_dir),
        "adapter": run_eval("adapter", args.base, args.adapter, examples, args.max_new_tokens, out_dir),
    }

    summary_path = out_dir / "compare_summary.json"
    summary_path.write_text(
        json.dumps(
            {"base_model": args.base, "adapter": args.adapter, "n": len(examples), **summaries},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{'metric':<18}{'base':>10}{'adapter':>10}")
    for key, label in METRIC_ROWS:
        print(f"{label:<18}{summaries['base'][key]:>10.1%}{summaries['adapter'][key]:>10.1%}")
    print(f"\nSummary: {summary_path}")
    print(f"Per-example: {out_dir / 'compare_base.jsonl'}, {out_dir / 'compare_adapter.jsonl'}")


if __name__ == "__main__":
    main()
