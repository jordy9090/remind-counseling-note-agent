"""Run the authorized three-call comparison on one pinned synthetic fixture.

Credentials come only from the process environment. No .env, storage, deployed
endpoint, implicit repair, or automatic retry is used. Default is preflight.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SHA256 = "288ac1bb50e076efd68e791ba373afb0885c54258391d7bb3056ac8e7ffd4d4e"
MODEL = "gpt-5.4-2026-03-05"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-response", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    data = args.baseline_response.read_bytes()
    if hashlib.sha256(data).hexdigest() != FIXTURE_SHA256:
        parser.error("The input must be the previously validated synthetic response fixture")
    key = os.environ.get("OPENAI_API_KEY")
    preflight = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "model": MODEL,
        "fixture_sha256": FIXTURE_SHA256, "maximum_calls": 3,
        "max_completion_tokens_per_call": 6000, "reasoning_effort": "low",
        "provider_key_available": bool(key), "new_model_calls": 0,
        "result": "READY" if key else "BLOCKED", "executed": False,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "live-preflight.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
    if not key or not args.execute:
        print(json.dumps(preflight))
        return int(not key)

    ledger_path = args.output / "live-comparison.json"
    if ledger_path.exists():
        parser.error("A live ledger already exists; refusing an automatic repeat")
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
    for name in list(os.environ):
        if name.startswith(("OPENAI", "SUPABASE", "ENABLE_", "SAVE_", "REMIND_", "LANGCHAIN", "LANGSMITH")):
            os.environ.pop(name, None)
    from pydantic_settings import BaseSettings
    original_init = BaseSettings.__init__

    def isolated_init(self, **kwargs):
        return original_init(self, **{**kwargs, "_env_file": None})

    BaseSettings.__init__ = isolated_init
    from app.core.config import settings
    from app.graph import nodes
    from app.schemas.note import SanitizedInput
    from app.services.llm import get_llm
    from app.services import summary_skill

    settings.openai_api_key = key
    settings.openai_model = MODEL
    settings.openai_reasoning_effort = "low"
    settings.openai_timeout_seconds = 90
    settings.use_stub = False
    sanitized = SanitizedInput.model_validate(json.loads(data)["sanitized_input"])
    ledger = {
        **preflight, "result": "RUNNING", "executed": True, "calls": [], "arms": {},
        "scope": "extraction+summary only; identical already-deidentified synthetic input",
        "excluded": ["upstream masking", "verifier", "insights", "auth", "storage"],
    }
    lock = threading.Lock()
    counts = {"baseline": 0, "skill": 0}

    def save():
        ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    save()

    class Transport:
        def __init__(self, arm):
            self.arm = arm

        def with_structured_output(self, schema, *, include_raw=False):
            client = get_llm(max_retries=0)
            client.max_tokens = 6000
            runnable = client.with_structured_output(schema, include_raw=True)
            arm = self.arm

            class Call:
                def invoke(self, prompt):
                    with lock:
                        if counts[arm] >= (2 if arm == "baseline" else 1):
                            raise RuntimeError("Authorized call limit reached; repair refused")
                        counts[arm] += 1
                        entry = {"arm": arm, "sequence": counts[arm], "schema": schema.__name__, "result": "STARTED"}
                        ledger["calls"].append(entry)
                        ledger["new_model_calls"] += 1
                        save()
                    start = time.perf_counter()
                    try:
                        result = runnable.invoke(prompt)
                        raw = result.get("raw")
                        usage = getattr(raw, "usage_metadata", None) or {}
                        safe_usage = {k: usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")}
                        cached = (usage.get("input_token_details") or {}).get("cache_read", 0)
                        safe_usage["cached_input_tokens"] = cached
                        with lock:
                            entry.update(result="RECEIVED", seconds=round(time.perf_counter() - start, 3), usage=safe_usage)
                            metadata = getattr(raw, "response_metadata", {}) or {}
                            entry["response_model"] = metadata.get("model_name")
                            save()
                        if result.get("parsing_error") or result.get("parsed") is None:
                            raise RuntimeError("Structured output was not usable")
                        parsed = result["parsed"]
                        (args.output / f"{arm}-{counts[arm]}-output.json").write_text(
                            parsed.model_dump_json(indent=2), encoding="utf-8",
                        )
                        return result if include_raw else parsed
                    except Exception as error:
                        with lock:
                            entry.update(result="FAIL", error_type=type(error).__name__, seconds=round(time.perf_counter() - start, 3))
                            save()
                        raise RuntimeError("Comparison call failed; see value-free ledger") from None
            return Call()

    def run_arm(arm):
        start = time.perf_counter()
        try:
            if arm == "baseline":
                state = {"sanitized_input": sanitized.model_copy(deep=True)}
                state.update(nodes.structure_session(state))
                state.update(nodes.map_evidence(state))
                state.update(nodes.generate_summary(state))
                summary = state["session_summary_draft"]
            else:
                summary = summary_skill.run_summary_skill(sanitized.model_copy(deep=True)).summary
            (args.output / f"{arm}-summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
            outcome = {"result": "PASS", "seconds": round(time.perf_counter() - start, 3)}
        except Exception as error:
            outcome = {"result": "FAIL", "seconds": round(time.perf_counter() - start, 3), "error_type": type(error).__name__}
        with lock:
            ledger["arms"][arm] = outcome
            save()

    with patch.object(nodes, "get_structured_llm", side_effect=lambda schema, **kwargs: Transport("baseline").with_structured_output(schema)), patch.object(
        summary_skill, "get_llm", side_effect=lambda **kwargs: Transport("skill"),
    ), ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_arm, arm) for arm in ("baseline", "skill")]
        for future in futures:
            future.result()
    ledger["result"] = "PASS" if all(arm["result"] == "PASS" for arm in ledger["arms"].values()) else "FAIL"
    ledger["finished_at"] = datetime.now(timezone.utc).isoformat()
    for arm, outcome in ledger["arms"].items():
        usages = [item.get("usage") for item in ledger["calls"] if item["arm"] == arm]
        if all(usage and isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int) for usage in usages):
            outcome["input_tokens"] = sum(usage["input_tokens"] for usage in usages)
            outcome["output_tokens"] = sum(usage["output_tokens"] for usage in usages)
            outcome["cost_usd_at_standard_rates"] = round(sum(
                ((usage["input_tokens"] - usage["cached_input_tokens"]) * 2.5 + usage["cached_input_tokens"] * 0.25 + usage["output_tokens"] * 15) / 1_000_000
                for usage in usages
            ), 6)
    save()
    settings.openai_api_key = None
    print(json.dumps(ledger))
    return int(ledger["result"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
