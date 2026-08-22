"""Build a counselor-facing two-candidate package from ChatGPT selection IDs."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "eval_outputs_v4"
DEFAULT_OUTPUT = ROOT / "counselor_demo_ready"
DOCUMENTS = {
    "01_session_summary.txt": "회기요약.txt",
    "02_session_note.txt": "상담일지.txt",
    "03_supervision_report.txt": "수퍼비전보고서.txt",
    "04_termination_report.txt": "종결보고서.txt",
}
INTERNAL_CONDITION_TERMS = ("7-node", "11-node", "7node", "11node", "no_rag", "lightweight", "dense", "hybrid")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-1")
    parser.add_argument("--candidate-2")
    parser.add_argument("--selection-json", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    candidates = selection_from_args(args.candidate_1, args.candidate_2, args.selection_json)
    build_package(candidates[0], candidates[1], args.output.resolve(), overwrite=args.overwrite)
    print(json.dumps({"created": str(args.output.resolve()), "selected_candidates": candidates}, ensure_ascii=False, indent=2))
    return 0


def selection_from_args(candidate_1: str | None, candidate_2: str | None, selection_json: Path | None) -> list[str]:
    if selection_json:
        if candidate_1 or candidate_2:
            raise SystemExit("Use candidate arguments or --selection-json, not both.")
        text = selection_json.read_text(encoding="utf-8")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"SELECTED_CANDIDATES\s*=\s*(\[[^\n]+\])", text)
            if not match:
                raise SystemExit("Selection file contains neither JSON nor SELECTED_CANDIDATES=[...].")
            payload = json.loads(match.group(1))
        if isinstance(payload, list):
            candidates = payload
        elif isinstance(payload, dict):
            candidates = payload.get("selected_candidates") or payload.get("SELECTED_CANDIDATES") or payload.get("best_two")
        else:
            candidates = None
    else:
        candidates = [candidate_1, candidate_2]
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise SystemExit("Exactly two selected candidate IDs are required.")
    normalized = [str(item or "").strip() for item in candidates]
    if len(set(normalized)) != 2 or not all(re.fullmatch(r"Candidate-0[1-6]", item) for item in normalized):
        raise SystemExit("Candidates must be two distinct IDs from Candidate-01 through Candidate-06.")
    return normalized


def build_package(candidate_1: str, candidate_2: str, output: Path, *, overwrite: bool = False) -> Path:
    review_root = EVAL_ROOT / "gpt_review"
    map_path = EVAL_ROOT / "internal/blind_condition_map.json"
    if not review_root.exists() or not map_path.exists():
        raise RuntimeError("eval_outputs_v4 blind review artifacts are missing.")
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    for candidate in (candidate_1, candidate_2):
        if candidate not in mapping or not (review_root / candidate).is_dir():
            raise RuntimeError(f"Unknown or missing candidate: {candidate}")
    if output.exists():
        if not overwrite:
            raise RuntimeError(f"{output} already exists; use --overwrite to replace it.")
        if output == Path(output.anchor) or output == ROOT:
            raise RuntimeError("Refusing to remove a broad output path.")
        shutil.rmtree(output)
    (output / "blind_comparison").mkdir(parents=True)
    (output / "optional").mkdir()
    (output / "internal").mkdir()

    selected = [("A", candidate_1), ("B", candidate_2)]
    quality: dict[str, Any] = {}
    internal_mapping: dict[str, Any] = {}
    for display_label, candidate in selected:
        source_folder = str(mapping[candidate].get("source_folder") or "")
        source = EVAL_ROOT / "demo_quality" / source_folder
        if not source.is_dir():
            raise RuntimeError(f"Mapped condition output is missing for {candidate}")
        for source_name, suffix in DOCUMENTS.items():
            target_root = output / "optional" if source_name == "04_termination_report.txt" else output / "blind_comparison"
            shutil.copyfile(source / source_name, target_root / f"문서_{display_label}_{suffix}")
        quality[display_label] = json.loads((source / "quality_metadata.json").read_text(encoding="utf-8"))
        internal_mapping[display_label] = {"candidate_id": candidate, **mapping[candidate]}

    (output / "00_DEMO_GUIDE.md").write_text(demo_guide(), encoding="utf-8")
    (output / "01_CASE_BRIEF.md").write_text(case_brief(), encoding="utf-8")
    (output / "FEEDBACK_SHEET.md").write_text(feedback_sheet(), encoding="utf-8")
    (output / "internal/selected_candidate_mapping.json").write_text(_json(internal_mapping), encoding="utf-8")
    (output / "internal/selected_quality_metadata.json").write_text(_json(quality), encoding="utf-8")
    validate_public_package(output)
    return output


def validate_public_package(output: Path) -> None:
    public_files = [path for path in output.rglob("*") if path.is_file() and "internal" not in path.parts]
    for path in public_files:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        leaked = [term for term in INTERNAL_CONDITION_TERMS if term in lowered]
        if leaked:
            raise RuntimeError(f"Internal condition label leaked into {path}: {leaked}")
        if re.search(r"\[(?:PERSON|NAME|LOCATION|REDACTED|EMAIL|PHONE|ACCOUNT|RRN|STUDENT_ID|ADDRESS|INSTITUTION)\]", text):
            raise RuntimeError(f"Internal privacy placeholder leaked into {path}")


def case_brief() -> str:
    return """# 사례 요약

- 평가용 사례: CASE-MUSPSY-1416
- 현재 회기: 5회기
- 주요 어려움: 사회적 상황에서 부정적 평가를 예상하고 회피한 뒤 고립감과 자기비난이 커지는 패턴
- 활용 중인 자원: 스케치, 현재 경험에 주의를 돌리는 연습, 지지적인 룸메이트
- 현재 회기의 핵심: 스케치를 정서조절 전략으로 구체화하고, 자동사고를 점검하며, 사회적 상황에서 시도할 작은 행동계획을 세움

일부 심리검사와 관찰정보는 제품 시연을 위해 구성된 supplementary demo input입니다.
"""


def demo_guide() -> str:
    return """# 상담사 시연 진행 가이드

총 15~25분을 권장합니다.

## STEP 1 — 제품 설명 · 2~3분

“상담 이후 기록 초안을 만들고 상담사가 검토·수정하는 흐름”이라고 설명합니다. 완성 기록이 아니라 검토 가능한 초안이라는 점을 먼저 알립니다.

## STEP 2 — 사례 요약

`01_CASE_BRIEF.md`를 함께 읽고 현재 5회기 사례의 핵심만 설명합니다.

## STEP 3 — 상담일지 비교

상담일지 문서 A/B를 먼저 비교합니다.

질문: “두 문서 중 실제 상담 후 기록 초안으로 받는다면 어느 쪽을 선택하시겠어요?”

## STEP 4 — 회기요약 비교

회기요약 문서 A/B를 비교하고 빠진 핵심, 과한 해석, 수정하고 싶은 문장을 확인합니다.

## STEP 5 — 수퍼비전 보고서

두 문서를 모두 정독하기보다 필요한 section, 누락, 과잉 해석 여부를 중심으로 확인합니다.

## STEP 6 — 종결보고서 형식

현재 사례는 진행 중입니다. optional 폴더의 종결보고서는 임상 정확도 비교의 핵심 자료가 아니라 “이런 문서 형태가 유용한가”를 묻는 형식 피드백에만 사용합니다.

## STEP 7 — 전체 흐름 피드백

초안 생성, 상담사 확인, 수정, 근거 확인 흐름이 실제 기록 업무에 맞는지 질문합니다.

`internal/` 폴더는 운영 확인용이며 상담사에게 보여주지 않습니다.
"""


def feedback_sheet() -> str:
    return """# 상담사 피드백 시트

1. 두 상담일지 중 실제 업무에서 초안으로 받는다면 A/B 중 어느 쪽을 선택하시겠어요? 왜인가요?

2. 선택한 문서에서도 가장 먼저 수정하고 싶은 문장은 어디인가요?

3. 사실과 다르거나 상담사가 하기에는 과한 해석이라고 느껴지는 부분이 있나요?

4. 반대로 빠진 핵심 내용이 있나요?

5. 이 정도 초안이면 직접 처음부터 작성하는 것과 비교해 수정 부담이 얼마나 줄어들 것 같나요?
   - 거의 없음
   - 조금
   - 꽤 많이
   - 매우 많이

6. 이전 회기 정보가 반영된 부분 중 도움이 된 부분과 불필요한 부분이 있나요?

7. 근거가 어디서 왔는지 확인할 수 있는 기능이 실제 업무에 필요할까요? 어떤 상황에서 필요할까요?

8. 수퍼비전 보고서에서 실제로 자동화되면 가장 도움이 될 section은 무엇인가요?

9. 이 문서를 실제로 사용한다면 반드시 직접 확인하고 싶은 항목은 무엇인가요?

10. 현재 기록 방식에서 이 제품을 사용할 이유가 생기려면 무엇이 더 좋아져야 하나요?

11. 현재 사용 중인 기록 방식 대비 이 정도 결과라면 실제로 사용해볼 의향이 있나요?

12. 어떤 문서부터 가장 먼저 자동화되면 좋겠나요?
    - 회기요약
    - 상담일지
    - 수퍼비전 준비
    - 종결/사례보고
    - 기타

보조 질문: 유료로 사용할 정도의 가치가 있으려면 어느 수준까지 개선되어야 하나요?
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
