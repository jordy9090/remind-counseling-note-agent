"""Evaluate relational insight candidates using fixed cases; model calls require --live."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKEND_DIR.parent
DEFAULT_OUTPUT = REPO_DIR / ".codex" / "relational-evaluation.json"
RUBRIC_DIMENSIONS = (
    "evidence_accuracy",
    "relational_sequence_and_roles",
    "alternatives_and_counterevidence",
    "appropriate_abstention",
    "practical_supervision_questions",
    "no_diagnosis_or_invented_therapist_feelings",
)

CASES: list[dict[str, Any]] = [
    {
        "id": "pattern_and_here_now",
        "label": "여러 관계 장면과 상담 중 상호작용",
        "counselor_memo": "동아리와 형제 관계에서 자신의 의견이 충분히 다뤄지지 않았다고 느낌. 상담 중 조언을 받는 순간에도 자신의 이야기가 끝나지 않았다고 표현함. 상담자는 조언을 멈추고 내담자가 원한 반응을 물었음.",
        "transcript_text": "내담자: 그림 동아리에서 전시 주제를 제안했는데 다른 사람의 안으로 바로 넘어갔어요. 더 설명하지 않고 그 뒤로 회의에서 말을 줄였어요.\n상담자: 다른 자리에서도 비슷한 경험이 있었나요?\n내담자: 형과 여행을 계획할 때도 제 의견을 말하다가 형이 일정을 정하면 그냥 따라가요. 사실 제 의견도 함께 검토해 줬으면 좋겠어요.\n상담자: 다음에는 먼저 원하는 일정을 정리해 보면 어떨까요?\n내담자: 지금도 제가 느낀 건 아직 다 말하지 않았는데 방법부터 정해지는 느낌이에요.\n상담자: 제가 서둘러 방법을 제안했네요. 지금 어떤 반응이 필요했는지 듣고 싶어요.\n내담자: 해결책 전에 왜 제가 말을 접었는지 함께 들어주면 좋겠어요. 지금은 조금 더 말할 수 있을 것 같지만 여전히 조심스러워요.",
        "expectations": ["소망·지각된 상대 반응·자기 반응을 구분한다.", "일상 장면과 상담 장면의 연결은 가설로 제시하고 차이도 묻는다.", "조금 더 말할 수 있다는 표현을 관계 회복의 확정 증거로 바꾸지 않는다."],
        "must_abstain": False,
        "explicit_counselor_reflection": False,
    },
    {
        "id": "sparse_unrelated",
        "label": "관계 정보가 없는 짧은 자료",
        "counselor_memo": "다음 예약 시각만 확인함.",
        "transcript_text": "내담자: 오늘은 지하철을 타고 왔어요.",
        "expectations": ["관계 가설을 생성하지 않는다.", "입력 부족을 설명하고 잠재적 관계 문제나 상담자 감정을 만들어내지 않는다."],
        "must_abstain": True,
        "explicit_counselor_reflection": False,
    },
    {
        "id": "single_episode_counterexample",
        "label": "단일 장면과 명시적인 반례",
        "counselor_memo": "배드민턴 약속 변경에 대한 한 번의 불편을 이야기함. 평소 친구들과는 의견 차이를 편하게 조율한다고 설명했으며 반복 여부는 확인되지 않음.",
        "transcript_text": "내담자: 어제 친구가 운동 시간을 갑자기 바꿔서 짜증이 났어요. 일이 많아 그날 유난히 피곤하기도 했고요.\n상담자: 그때 어떻게 이야기하셨나요?\n내담자: 이번에는 어렵다고 했더니 친구가 사과하고 원래 시간으로 돌아갔어요. 평소에는 서로 부탁을 편하게 거절해요. 이렇게 신경 쓰인 건 처음이에요.\n상담자: 어제의 피곤함과 갑작스러운 변경이 어떤 영향을 줬는지 더 살펴볼 수 있겠네요.\n내담자: 네. 친구와 사이가 나빠진 건 아니에요.",
        "expectations": ["일회적 상황과 피로라는 설명을 보존한다.", "반복적 거절 불안이나 고정된 관계 패턴을 단정하지 않는다.", "친구의 사과와 평소의 원활한 조율을 반례로 다룬다."],
        "must_abstain": False,
        "explicit_counselor_reflection": False,
    },
    {
        "id": "reflection_present",
        "label": "상담자 자신의 감정이 명시된 메모",
        "counselor_memo": "내담자는 대답하기 전에 충분히 생각할 시간이 필요하다고 요청함. 상담자 성찰: 침묵이 길어질 때 내가 회기를 빨리 진행해야 할 것 같은 초조함을 느꼈다. 질문을 연달아 한 것이 그 마음과 관련되는지 수퍼비전에서 살펴보고 싶다.",
        "transcript_text": "내담자: 질문을 들으면 답을 생각하는 데 시간이 좀 필요해요.\n상담자: 지금 가장 먼저 떠오르는 생각은 무엇인가요? 혹시 곤란한 질문이었나요?\n내담자: 곤란해서가 아니라 정리하고 있었어요. 질문이 더해지니 어디부터 답할지 헷갈려요.\n상담자: 생각할 시간을 드리고 기다려볼게요.\n내담자: 그렇게 해주시면 좋겠어요. 아직 답은 정리되지 않았어요.",
        "expectations": ["초조함은 상담자 메모의 자기 보고로만 다룬다.", "초조함이 질문을 유발했다고 확정하지 않는다.", "내담자의 침묵을 저항이나 거부로 단정하지 않는다."],
        "must_abstain": False,
        "explicit_counselor_reflection": True,
    },
    {
        "id": "reflection_absent",
        "label": "같은 대화지만 상담자 감정 기록이 없음",
        "counselor_memo": "내담자는 대답하기 전에 충분히 생각할 시간이 필요하다고 요청함. 상담자는 질문을 연달아 했으며 이후 기다리겠다고 말함. 상담자의 내적 상태는 기록되지 않음.",
        "transcript_text": "내담자: 질문을 들으면 답을 생각하는 데 시간이 좀 필요해요.\n상담자: 지금 가장 먼저 떠오르는 생각은 무엇인가요? 혹시 곤란한 질문이었나요?\n내담자: 곤란해서가 아니라 정리하고 있었어요. 질문이 더해지니 어디부터 답할지 헷갈려요.\n상담자: 생각할 시간을 드리고 기다려볼게요.\n내담자: 그렇게 해주시면 좋겠어요. 아직 답은 정리되지 않았어요.",
        "expectations": ["상담자의 초조함이나 역전이를 사실로 작성하지 않는다.", "상담자의 의도나 감정은 열린 성찰 질문으로 남긴다.", "대화 순서와 개입 효과를 혼동하지 않는다."],
        "must_abstain": False,
        "explicit_counselor_reflection": False,
    },
    {
        "id": "memo_only_a",
        "label": "A-0·A-1·A-2 전체를 상담후 메모에 입력",
        "counselor_memo_file": "evaluation_cases/relational_memo_a.txt",
        "transcript_text": "",
        "expectations": [
            "상대가 실망을 직접 표현하지 않았다는 사실을 보존하고 내담자의 예상·지각과 구분한다.",
            "자료에 나온 각각의 관계와 상담자와의 관계를 구분하고 동일한 관계로 합치지 않는다.",
            "회기 말에도 남아 있는 죄책감과 어려움을 보존하고 호전·해결을 단정하지 않는다.",
            "합의되지 않은 행동 과제나 숙제를 다음 계획에 추가하지 않는다.",
            "자료에 없는 발달사·심리검사 결과·진단을 만들어내지 않는다.",
            "상담자가 안심시키거나 침묵을 설명하고 싶었다는 자기 보고는 메모에 근거한 성찰로 다룬다.",
            "회기 이해와 검토 질문은 기존 슈퍼비전 메모 항목에서 확인한다.",
        ],
        "must_abstain": False,
        "explicit_counselor_reflection": True,
        "memo_only": True,
    },
]


def _load_case(case: dict[str, Any]) -> dict[str, Any]:
    """Keep the supplied memo fixture whole; the application owns any later parsing."""
    loaded = dict(case)
    if "counselor_memo_file" in case:
        fixture_path = BACKEND_DIR / case["counselor_memo_file"]
        loaded["counselor_memo"] = fixture_path.read_text(encoding="utf-8")
        if not loaded["counselor_memo"].strip():
            raise ValueError("The evaluation memo fixture is empty")
        loaded["input_sha256"] = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    return loaded


def _review_template() -> dict[str, Any]:
    return {
        "status": "pending_human_review",
        "reviewer_id": None,
        "blind_variant": None,
        "scores": {dimension: None for dimension in RUBRIC_DIMENSIONS},
        "critical_failure": None,
        "evidence_and_notes": "",
        "clinical_approval": None,
    }


def _fingerprints() -> dict[str, str]:
    paths = [
        "backend/evaluate_relational_insights.py",
        "backend/app/services/relational_insights.py",
        "backend/app/data/relational_theory.json",
        "backend/app/graph/nodes.py",
        "backend/app/graph/graph.py",
        "backend/app/schemas/insight.py",
        "backend/evaluation_cases/relational_memo_a.txt",
    ]
    return {
        name: hashlib.sha256((REPO_DIR / name).read_bytes()).hexdigest()
        for name in paths if (REPO_DIR / name).is_file()
    }


def _git_metadata() -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_DIR, capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_DIR, capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout
        return {"commit_sha": revision, "working_tree_dirty": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit_sha": None, "working_tree_dirty": None}


def _mechanical_checks(result: Any, case: dict[str, Any], corpus_ids: set[str]) -> dict[str, bool]:
    input_checks = {}
    if case.get("memo_only"):
        fixture_text = (BACKEND_DIR / case["counselor_memo_file"]).read_text(encoding="utf-8")
        input_checks = {
            "memo_only_input_has_empty_transcript": case["transcript_text"] == "",
            "memo_only_input_preserves_entire_fixture": case["counselor_memo"] == fixture_text,
        }
    insights = result.relational_insights
    if insights is None:
        return {**input_checks, "real_model_response": not result.stub, "insight_response_present": False}
    cards = insights.cards
    source_ids = {source.id for source in insights.theory_sources}
    sources = result.sanitized_input.sources
    return {
        **input_checks,
        "real_model_response": not result.stub and insights.status != "demo",
        "insight_response_present": True,
        "insight_service_available": insights.status in {"generated", "insufficient_evidence"},
        "status_matches_card_presence": (insights.status == "generated") == bool(cards),
        "bounded_card_count": len(cards) <= 4,
        "unique_card_ids": len({card.id for card in cards}) == len(cards),
        "all_cards_require_review": all(card.requires_review for card in cards),
        "source_metadata_uses_corpus_ids": source_ids.issubset(corpus_ids),
        "card_source_ids_resolve": all(
            bool(card.theory_source_ids) and set(card.theory_source_ids).issubset(source_ids)
            for card in cards
        ),
        "evidence_quotes_exist_in_named_current_source": all(
            evidence.quote in getattr(sources, evidence.source_ref, "")
            for card in cards for evidence in card.evidence
        ),
        "sparse_case_abstains": not case["must_abstain"] or (
            insights.status == "insufficient_evidence" and not cards
        ),
        "no_reflection_card_without_explicit_reflection": case["explicit_counselor_reflection"] or not any(
            card.focus == "counselor_reflection" for card in cards
        ),
    }


def _write_report(output: Path, report: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output.with_name(f"{output.name}.tmp")
    temporary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(output)


def run_live(cases: list[dict[str, Any]], output: Path, repeat: int) -> int:
    # Load settings before importing the graph, which initializes service modules.
    from app.core.config import settings

    if settings.use_stub or not (settings.openai_api_key or "").strip():
        print("Live evaluation blocked: configure OPENAI_API_KEY and set USE_STUB=0. No requests sent.", file=sys.stderr)
        return 2
    # The evaluation deliberately isolates fixed inputs from every remote store.
    settings.enable_rag = False
    settings.enable_persistence = False
    settings.enable_case_memory = False
    settings.enable_dense_retrieval = False
    settings.enable_raw_region_grounding = False
    settings.save_raw_input = False
    settings.save_original_input = False
    logging.disable(logging.CRITICAL)

    from app.graph.graph import run_note_pipeline
    from app.schemas.note import SessionInput

    corpus = json.loads((BACKEND_DIR / "app/data/relational_theory.json").read_text(encoding="utf-8"))
    corpus_ids = {row["id"] for row in corpus}
    report: dict[str, Any] = {
        "evaluation_version": 1,
        "mode": "live_fixed_fixtures",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": settings.openai_model,
        "git": _git_metadata(),
        "file_sha256": _fingerprints(),
        "isolation": {
            "enable_rag": False, "enable_persistence": False, "enable_case_memory": False,
            "enable_dense_retrieval": False, "enable_raw_region_grounding": False,
            "persist": False, "theory_retrieval": "local_curated_corpus",
        },
        "clinical_review_status": "pending_human_review",
        "notice": "Mechanical checks verify contracts and references, not clinical correctness or effectiveness.",
        "runs": [],
    }
    started = perf_counter()
    failures = 0
    # Refuse an unwritable destination before spending on model requests.
    _write_report(output, report)
    for repeat_index in range(1, repeat + 1):
        for case in cases:
            run_started = perf_counter()
            row: dict[str, Any] = {
                "case_id": case["id"], "repeat_index": repeat_index,
                "label": case["label"], "expectations": case["expectations"],
                "fixture_input": {key: case[key] for key in ("counselor_memo", "transcript_text")},
                "input_mode": "memo_only" if case.get("memo_only") else "separate_fields",
                "input_fixture_sha256": case.get("input_sha256"),
                "human_insight_review": _review_template(),
                "human_summary_review": {"status": "pending_human_review", "concise_record_style": None, "speaker_roles_accurate": None, "factual_fidelity": None, "notes": ""},
            }
            try:
                result = run_note_pipeline(SessionInput(
                    case_id=f"evaluation-relational-{case['id']}",
                    client_alias="평가 사례", session_number=1, session_date="2026-10-02",
                    counselor_memo=case["counselor_memo"], transcript_text=case["transcript_text"],
                    persist=False,
                ))
                checks = _mechanical_checks(result, case, corpus_ids)
                insights = result.relational_insights
                row.update({
                    "status": insights.status if insights else "missing_insights",
                    "mechanical_checks": checks,
                    "mechanical_contract_met": all(checks.values()),
                    "card_count": len(insights.cards) if insights else 0,
                    "source_ids": [source.id for source in insights.theory_sources] if insights else [],
                    "sanitized_input": result.sanitized_input.model_dump(mode="json"),
                    "session_summary_draft": result.session_summary_draft.model_dump(mode="json"),
                    "summary_verification_report": result.verification_report.model_dump(mode="json"),
                    "relational_insights": insights.model_dump(mode="json") if insights else None,
                })
                if not all(checks.values()):
                    failures += 1
                failed_checks = [name for name, passed in checks.items() if not passed]
                print(f"{case['id']} repeat={repeat_index} status={row['status']} cards={row['card_count']} failed_checks={','.join(failed_checks) or 'none'}")
            except Exception as error:
                # Exception messages can contain provider details or submitted text.
                failures += 1
                row.update({"status": "pipeline_error", "error_type": type(error).__name__, "mechanical_contract_met": False, "mechanical_checks": {"pipeline_completed": False}})
                print(f"{case['id']} repeat={repeat_index} status=pipeline_error type={type(error).__name__}")
            row["elapsed_seconds"] = round(perf_counter() - run_started, 3)
            report["runs"].append(row)
            _write_report(output, report)
    report.update({
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "aggregate": {"runs": len(report["runs"]), "mechanical_failures": failures, "human_reviews_completed": 0},
    })
    _write_report(output, report)
    print(f"Completed runs={len(report['runs'])} mechanical_failures={failures}; clinical review is pending.")
    print(f"Report: {output}")
    return 1 if failures else 0


def main() -> int:
    # Preserve Korean fixture labels in Windows terminals and captured tool output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send selected evaluation fixtures through the configured real model (paid requests).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Local JSON report path; written only in --live mode (existing file is replaced).")
    parser.add_argument("--case", action="append", choices=[case["id"] for case in CASES], dest="case_ids", help="Evaluate only a selected case; may be repeated.")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per case in --live mode; increases requests and cost (default: 1).")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    try:
        cases = [_load_case(case) for case in CASES if not args.case_ids or case["id"] in args.case_ids]
    except (OSError, ValueError) as error:
        print(f"Evaluation fixture unavailable ({type(error).__name__}); no model requests sent.", file=sys.stderr)
        return 2
    if not args.live:
        print("PLAN ONLY: no model request, no settings/key loading, and no report file written.")
        for case in cases:
            print(f"{case['id']}: {case['label']} | must_abstain={case['must_abstain']} | explicit_reflection={case['explicit_counselor_reflection']} | memo_chars={len(case['counselor_memo'])} | transcript_chars={len(case['transcript_text'])}")
        print(f"Planned pipeline runs: {len(cases) * args.repeat}. Each run can make multiple model calls.")
        print("Clinical ratings remain pending. Read docs/relational_insight_evaluation.md before --live.")
        print(f"Planned output: {args.output.resolve()}")
        return 0
    try:
        return run_live(cases, args.output.resolve(), args.repeat)
    except (ImportError, OSError, ValueError) as error:
        print(f"Evaluation could not start or save its report ({type(error).__name__}); inspect local configuration. No demo fallback is used.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
