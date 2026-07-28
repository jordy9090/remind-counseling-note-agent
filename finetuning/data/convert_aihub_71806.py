"""Converter for AI Hub 심리상담 데이터 (dataSetSn=71806) -> intermediate format.

개방데이터 배포본(회기별 ZIP 안에 내담자별 라벨 JSON)을 ZIP 해제 없이 직접 읽습니다.

실제 라벨 스키마 (2025-04 배포본 기준):
  최상위: filename, id, age, gender, depression/anxiety/addiction, class,
          summary(주요 증상/위험요인/개선요인/상담사의 개입요인 4개 섹션 텍스트),
          silence, total_time, paragraph[]
  paragraph: paragraph_speaker(내담자|상담사), paragraph_text,
             내담자 증상/변화 라벨(depressive_mood, emotional_change 등),
             상담사 개입기법 라벨(sympathy_support, goal_setting 등)

매핑 (SessionSummaryDraft 스키마, 근거 정직성 유지):
  presenting_problem     <- summary "주요 증상" (direct)
  session_content        <- summary "위험요인" + "개선요인" (mixed: 요약자 해석 포함)
  counselor_intervention <- summary "상담사의 개입요인" (direct)
  client_response        <- 변화 라벨(emotional/cognitive/behavioral/acceptance_change)이
                            붙은 내담자 발화 인용 (direct), 없으면 needs_review
  session_theme          <- class + 주요 증상 첫 문장 (mixed)
  next_plan              <- 개입요인 중 계획/다음 회기 문장 (mixed), 없으면 needs_review
  reflection             <- 상담사 직접 작성 placeholder (counselor_input)

주의: AI Hub 데이터는 재배포 금지입니다. data/raw, data/processed는 gitignore
상태를 유지하고, 생성된 SFT 데이터도 외부 공개하지 마세요.

Usage:
  python data/convert_aihub_71806.py --input "C:/Users/.../16.심리상담 데이터/3.개방데이터"
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

OUT = Path(__file__).parent / "processed"

SUMMARY_SECTION_RE = re.compile(
    r"(주요\s*증상|위험\s*요인|개선\s*요인|상담사의?\s*개입\s*요인)\s*:\s*"
)
NEXT_PLAN_RE = re.compile(r"(다음\s*회기|계획|과제|추후|반복하는\s*활동)")
ZIP_META_RE = re.compile(r"(?:TL|VL)_\d+\.\s*(\S+)_\d+\.\s*(\d+)회기")

CHANGE_LABELS = [
    "emotional_change",
    "cognitive_change",
    "behavioral_change",
    "acceptance_change",
    "motivation_for_change",
]
INTERVENTION_LABELS = [
    "sympathy_support",
    "clarification_reflection",
    "cognitive_restructuring",
    "information_provision",
    "goal_setting",
    "process_feedback",
    "behavioral_intervention",
    "task_assignment",
    "training_of_coping_skills",
    "emotional_regulation_education_training",
    "structuring",
]

REFLECTION_PLACEHOLDER = "상담자 reflection은 상담사가 직접 작성하거나 확인해야 합니다."


def _section(text: str, evidence_type: str = "direct", source_refs: list[str] | None = None) -> dict:
    review_types = {"inferred", "model_inference", "needs_review", "counselor_input", "prior_context_based"}
    return {
        "text": text.strip(),
        "evidence_type": evidence_type,
        "source_refs": ["transcript_text"] if source_refs is None else source_refs,
        "requires_review": evidence_type in review_types,
    }


def split_summary(summary: str) -> dict[str, str]:
    """Split the 4-section summary text into {normalized heading: body}."""
    parts = SUMMARY_SECTION_RE.split(summary)
    sections: dict[str, str] = {}
    for heading, body in zip(parts[1::2], parts[2::2]):
        key = re.sub(r"\s", "", heading)
        key = {"상담사개입요인": "상담사의개입요인"}.get(key, key)
        sections[key] = body.strip()
    return sections


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return parts[0].strip() if parts else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if s.strip()]


CLASS_KO = {"DEPRESSION": "우울", "ANXIETY": "불안", "ADDICTION": "중독", "NORMAL": "일반"}


def build_note(data: dict, dialogue: list[dict]) -> dict | None:
    sections = split_summary(data.get("summary", ""))
    symptom = sections.get("주요증상", "")
    risk = sections.get("위험요인", "")
    improvement = sections.get("개선요인", "")
    intervention = sections.get("상담사의개입요인", "")
    if not symptom:
        return None  # 요약 라벨이 비어 있는 레코드 — 노트 타깃 구성 불가

    theme_class = CLASS_KO.get(data.get("class", ""), "")
    theme = _first_sentence(symptom)
    if theme_class:
        theme = f"{theme_class} 관련 호소를 다룬 회기. {theme}"

    content_parts = []
    if risk:
        content_parts.append(f"위험요인: {risk}")
    if improvement:
        content_parts.append(f"개선요인: {improvement}")
    session_content = "\n".join(content_parts) or symptom

    change_quotes = [
        t["text"] for t in dialogue if t["speaker"] == "client" and t.get("has_change")
    ]
    if change_quotes:
        quote = max(change_quotes, key=len)
        if len(quote) > 200:
            quote = quote[:200] + "…"
        client_response = _section(f'내담자는 회기 중 변화 관련 발화를 보였다: "{quote}"')
    else:
        client_response = _section("내담자 반응은 상담사가 축어록에서 확인해야 합니다.", "needs_review", [])

    counselor_intervention = (
        _section(intervention)
        if intervention
        else _section("상담사 개입 내용이 요약에 명시되지 않아 상담사 확인이 필요합니다.", "needs_review", [])
    )

    plan_sentences = [s for s in _sentences(intervention) if NEXT_PLAN_RE.search(s)]
    next_plan = (
        _section(" ".join(plan_sentences[:2]), "mixed")
        if plan_sentences
        else _section("다음 회기 계획이 명시되지 않아 상담사 확인이 필요합니다.", "needs_review", [])
    )

    return {
        "session_theme": _section(theme, "mixed"),
        "presenting_problem": _section(symptom),
        "session_content": _section(session_content, "mixed"),
        "counselor_intervention": counselor_intervention,
        "client_response": client_response,
        "reflection": _section(REFLECTION_PLACEHOLDER, "counselor_input", []),
        "next_plan": next_plan,
    }


def convert_label_json(data: dict, category: str, session_number: int, split: str, stem: str) -> dict | None:
    dialogue = []
    for p in data.get("paragraph", []):
        text = str(p.get("paragraph_text") or "").strip()
        if not text:
            continue
        speaker = "counselor" if p.get("paragraph_speaker") == "상담사" else "client"
        turn = {"speaker": speaker, "text": text, "label": None}
        if speaker == "client" and any(p.get(k) for k in CHANGE_LABELS):
            turn["has_change"] = True
        if speaker == "counselor":
            active = [k for k in INTERVENTION_LABELS if p.get(k)]
            if active:
                turn["label"] = ",".join(active)
        # merge consecutive same-speaker turns to shorten the transcript
        if dialogue and dialogue[-1]["speaker"] == speaker:
            dialogue[-1]["text"] += " " + text
            if turn.get("has_change"):
                dialogue[-1]["has_change"] = True
            if turn.get("label"):
                dialogue[-1]["label"] = ",".join(filter(None, [dialogue[-1].get("label"), turn["label"]]))
        else:
            dialogue.append(turn)
    if len(dialogue) < 4:
        return None

    note = build_note(data, dialogue)
    interventions = sorted(
        {label for t in dialogue if t["speaker"] == "counselor" and t.get("label") for label in t["label"].split(",")}
    )
    # ID 규칙: split + category + 원본 참여자 ID + 회기 번호를 모두 포함해 전역 유일성을 보장.
    # (참여자 ID(D005 등)는 카테고리/스플릿 간에 재사용될 수 있음)
    original_id = str(data.get("id") or stem)
    category_slug = re.sub(r"^label_", "", stem).split("_")[0] or category
    record_id = f"aihub71806-{split}-{category_slug}-{original_id}-s{session_number}"
    # case_id는 split을 제외 — 같은 내담자의 회기가 TL/VL로 흩어져 있어도
    # group split 시 한 스플릿에 모이도록 한다.
    case_id = f"aihub71806-{category_slug}-{original_id}"
    return {
        "id": record_id,
        "case_id": case_id,
        "source": "aihub_71806",
        "language": "ko",
        "license": "AIHub-terms(재배포 금지)",
        "dialogue": [{k: v for k, v in t.items() if k in ("speaker", "text", "label")} for t in dialogue],
        "meta": {
            "split": split,
            "category": category,
            "class": data.get("class", ""),
            "session_number": session_number,
            "age": data.get("age"),
            "gender": data.get("gender", ""),
            "intervention_labels": interventions,
            "total_time_sec": data.get("total_time"),
        },
        "note": note,
    }


UNQUOTED_SUMMARY_RE = re.compile(r'("summary"\s*:\s*)(?!")(.+?)(,\s*[\r\n]+\s*"silence")', re.S)


def parse_label_json(raw: str) -> dict | None:
    """Parse a label JSON, repairing the known unquoted-summary defect."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    repaired = UNQUOTED_SUMMARY_RE.sub(
        lambda m: m.group(1) + json.dumps(m.group(2).strip(), ensure_ascii=False) + m.group(3),
        raw,
    )
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="'3.개방데이터' 디렉토리 경로")
    args = parser.parse_args()

    root = Path(args.input)
    zips = sorted(root.rglob("*.zip"))
    label_zips = [z for z in zips if "라벨링데이터" in str(z)]
    if not label_zips:
        raise SystemExit(f"라벨링데이터 zip을 찾지 못했습니다: {root}")

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "intermediate_aihub_71806.jsonl"
    records: list[dict] = []
    skipped = parse_errors = 0
    for zip_path in label_zips:
        match = ZIP_META_RE.search(zip_path.name)
        category = match.group(1) if match else ""
        session_number = int(match.group(2)) if match else 0
        split = "train" if zip_path.name.startswith("TL") else "val"
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if not name.endswith(".json"):
                    continue
                data = parse_label_json(zf.read(name).decode("utf-8-sig"))
                if data is None:
                    parse_errors += 1
                    print(f"  parse error: {zip_path.name} :: {name}")
                    continue
                stem = Path(name).stem
                record = convert_label_json(data, category, session_number, split, stem)
                if record is None:
                    skipped += 1
                    continue
                records.append(record)

    # --- validation: ID 유일성은 필수 조건이다 (중복 시 하드 실패) ---
    ids = [r["id"] for r in records]
    duplicates = {i for i in ids if ids.count(i) > 1} if len(set(ids)) != len(ids) else set()
    with_note = sum(1 for r in records if r["note"])
    cases = {r["case_id"] for r in records}
    print(f"total rows:        {len(records)}")
    print(f"unique ids:        {len(set(ids))}")
    print(f"duplicate ids:     {len(duplicates)}")
    print(f"rows with note:    {with_note}")
    print(f"unique case_ids:   {len(cases)}")
    if duplicates:
        for d in sorted(duplicates)[:10]:
            print(f"  DUP: {d}")
        raise SystemExit("FATAL: duplicate ids detected — fix the ID scheme before training.")

    with out_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"aihub_71806: {len(records)} records (skipped {skipped}, parse errors {parse_errors}) -> {out_path}")


if __name__ == "__main__":
    main()
