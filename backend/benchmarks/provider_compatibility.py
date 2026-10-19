"""Run the synthetic summary contract against an OpenAI-compatible endpoint.

The command prints metadata and validation flags only. It never prints the
synthetic transcript, provider response, API key, or endpoint URL.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from app.core.config import settings
from app.graph.summary_core import AUTHENTICATED_FULL_POLICY, run_summary_core
from app.schemas.note import SessionInput
from app.services.llm import observe_llm_request
from benchmarks.long_transcript_benchmark import generate_synthetic_transcript


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="LOCAL_LLM_API_KEY")
    parser.add_argument("--minutes", type=int, choices=(10, 20, 50, 60), default=10)
    parser.add_argument("--style", choices=("memo", "speakers", "timestamps"), default="speakers")
    args = parser.parse_args()

    settings.use_stub = False
    settings.llm_provider = "openai_compatible"
    settings.openai_compatible_base_url = args.base_url
    settings.openai_compatible_api_key = os.environ.get(args.api_key_env)
    settings.openai_model = args.model
    settings.openai_reasoning_effort = None

    transcript = generate_synthetic_transcript(args.minutes, args.style)
    started = time.perf_counter()
    try:
        with observe_llm_request("provider_compatibility_benchmark", max_calls=10) as observation:
            result = run_summary_core(
                {
                    "session_input": SessionInput(
                        case_id="synthetic-provider-benchmark",
                        session_number=1,
                        counselor_memo="",
                        transcript_text=transcript,
                        persist=False,
                        insight_lens="none",
                    )
                },
                policy=AUTHENTICATED_FULL_POLICY,
            )
    except Exception as error:
        print(json.dumps({
            "success": False,
            "error_type": type(error).__name__,
            "external_model_executed": True,
        }))
        raise SystemExit(1) from None

    summary = result["session_summary_draft"]
    sections = (
        summary.presenting_problem,
        summary.session_theme,
        summary.session_content,
        summary.counselor_intervention,
        summary.client_response,
        summary.reflection,
        summary.next_plan,
    )
    refs = [ref for section in sections for ref in section.source_refs]
    print(json.dumps({
        "success": True,
        "minutes": args.minutes,
        "style": args.style,
        "characters": len(transcript),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "provider_calls": len(observation.calls),
        "input_tokens": observation.summary()["input_tokens"],
        "output_tokens": observation.summary()["output_tokens"],
        "estimated_cost_usd": observation.summary()["estimated_cost_usd"],
        "all_sections_nonempty": all(section.text.strip() for section in sections),
        "source_reference_count": len(refs),
        "position_reference_count": sum(".chars_" in ref for ref in refs),
        "review_required_count": sum(section.requires_review for section in sections),
        "external_model_executed": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
