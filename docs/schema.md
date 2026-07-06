# Schema

현재 MVP V1 schema의 기준 파일은 `backend/app/schemas/note.py`입니다. 이 문서는 해당 Pydantic schema와 같은 계약을 설명합니다.

## 1. EvidenceType

```text
direct
inferred
counselor_input
previous_context
needs_review
mixed
model_inference
```

## 2. SessionInput

회기 자료 입력 스키마입니다.

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_date": "2026-05-17",
  "counselor_name": "Counselor A",
  "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고를 중심으로 진행함.",
  "transcript_text": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
  "previous_session_summary": "이전 회기에서는 자기이해와 진로 가치 탐색을 중심으로 다룸.",
  "counseling_goal": "진로 선택 과정에서 자기이해를 높이고 실행 가능한 준비 계획을 세움.",
  "psychological_test_summary": "",
  "key_issue_tags": ["진로불안", "자기비난", "취업준비"],
  "nonverbal_notes": "",
  "target_document_type": "session_note",
  "persist": false
}
```

필수 입력:

- `case_id`
- `session_number`
- `counselor_memo`
- `transcript_text`

현재 Pydantic model에서는 `session_date`, `counselor_name`, `previous_session_summary` 등은 빈 문자열 default를 가질 수 있지만, frontend MVP 화면에서는 날짜, 상담자, 이전 회기 요약도 주요 입력으로 받습니다.

호환 alias:

- `session_no` → `session_number`
- `transcript` → `transcript_text`
- `prev_summary` → `previous_session_summary`
- `document_type` → `target_document_type`

`target_document_type`는 `session_note`, `supervision_report`, `termination_report` 중 하나입니다. `persist=true`는 Supabase 설정과 `ENABLE_PERSISTENCE=1`이 있을 때만 저장을 요청합니다.

## 3. SanitizedInput

입력 정제 결과입니다.

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_date": "2026-05-17",
  "counselor_name": "Counselor A",
  "sources": {
    "counselor_memo": "상담사 메모",
    "transcript_text": "축어록/STT 텍스트",
    "previous_session_summary": "이전 회기 요약",
    "counseling_goal": "상담 목표",
    "psychological_test_summary": "",
    "key_issue_tags": ["진로불안"],
    "nonverbal_notes": ""
  },
  "sensitive_info_candidates": [
    {
      "text": "010-0000-0000",
      "source": "transcript_text",
      "category": "phone",
      "recommendation": "전화번호 후보입니다. 가명 또는 케이스 ID로 대체하세요."
    }
  ]
}
```

민감정보 후보 탐지 범위:

- 전화번호
- 이메일
- 학교명
- 실명으로 보이는 표현

## 4. StructuredCaseData

상담 자료를 공통 중간 구조로 변환한 결과입니다.

```json
{
  "presenting_problem": [],
  "session_theme": [],
  "session_content": [],
  "counselor_interventions": [],
  "client_responses": [],
  "key_client_utterances": [],
  "nonverbal_observations": [],
  "reflection_candidates": [],
  "next_plan": []
}
```

각 배열 항목은 `EvidenceItem`입니다.

```json
{
  "content": "내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
  "evidence_type": "direct",
  "source_refs": ["transcript_text", "counselor_memo"]
}
```

## 5. EvidenceMappedData

각 구조화 항목을 근거 출처와 연결한 결과입니다.

```json
{
  "items": [
    {
      "field": "presenting_problem",
      "content": "내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
      "evidence_type": "direct",
      "source_refs": ["transcript_text", "counselor_memo"],
      "requires_review": false
    }
  ]
}
```

## 6. SessionSummaryDraft

상담사가 frontend에서 textarea로 수정할 수 있는 회기요약 초안입니다.

```json
{
  "session_info": {
    "case_id": "CASE001",
    "session_number": 3,
    "session_date": "2026-05-17",
    "counselor_name": "Counselor A"
  },
  "session_theme": {
    "text": "진로불안, 자기비난, 취업준비를 중심으로 한 회기 내용 정리",
    "evidence_type": "direct",
    "source_refs": ["counselor_memo"],
    "requires_review": false
  },
  "presenting_problem": {
    "text": "내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
    "evidence_type": "direct",
    "source_refs": ["transcript_text", "counselor_memo"],
    "requires_review": false
  },
  "session_content": {
    "text": "이번 회기에서는 주요 이슈, 사고 흐름, 다음 계획을 정리함.",
    "evidence_type": "mixed",
    "source_refs": ["counselor_memo", "transcript_text"],
    "requires_review": false
  },
  "counselor_intervention": {
    "text": "상담자는 내담자의 표현을 구체화하도록 질문함.",
    "evidence_type": "direct",
    "source_refs": ["counselor_memo", "transcript_text"],
    "requires_review": false
  },
  "client_response": {
    "text": "내담자는 불안을 언어화하고 자신의 사고 흐름을 점검함.",
    "evidence_type": "inferred",
    "source_refs": ["transcript_text"],
    "requires_review": true
  },
  "reflection": {
    "text": "상담자 reflection은 상담사가 직접 작성하거나 확인해야 합니다.",
    "evidence_type": "counselor_input",
    "source_refs": [],
    "requires_review": true
  },
  "next_plan": {
    "text": "다음 회기에서는 자동사고 기록과 구체적인 행동 계획을 검토함.",
    "evidence_type": "inferred",
    "source_refs": ["counselor_memo"],
    "requires_review": true
  }
}
```

## 7. VerificationReport

회기요약 초안의 검증 결과입니다.

```json
{
  "grounded_items": [
    {
      "claim": "내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
      "source_refs": ["transcript_text", "counselor_memo"]
    }
  ],
  "weakly_grounded_items": [
    {
      "claim": "내담자는 불안을 언어화하고 자신의 사고 흐름을 점검함.",
      "reason": "입력 근거는 있으나 일부 해석 또는 요약이 포함되어 상담사 확인이 필요함.",
      "recommendation": "상담사가 유지, 수정, 삭제 여부를 판단"
    }
  ],
  "unsupported_or_risky_claims": [
    {
      "claim": "사례개념화, 위험 판단, 목표 달성 정도를 자동으로 확정하지 않음.",
      "reason": "현재 MVP의 자동 생성 대상이 아니며 상담사 임상 판단 영역임.",
      "recommendation": "상담사가 직접 작성하거나 별도 확인 필드로 분리"
    }
  ],
  "sensitive_info_items": [],
  "requires_counselor_review": [
    {
      "field": "reflection",
      "reason": "상담자 내적 경험과 임상적 판단 영역"
    },
    {
      "field": "case_conceptualization",
      "reason": "현재 MVP 자동 생성 대상이 아님"
    },
    {
      "field": "goal_attainment",
      "reason": "목표 달성 정도는 상담사 확인 필요"
    }
  ]
}
```

## 8. DocumentTransformPreview

MVP V1에서 preview 수준으로 제공하는 문서 변환 결과입니다.

```json
{
  "document_type": "preview",
  "available_transforms": ["supervision_report", "termination_report"],
  "preview_sections": {
    "session_summary": "확정된 회기요약 기반 미리보기",
    "client_main_issue": "입력 근거 기반으로 채울 수 있는 항목",
    "next_plan": "추후 계획",
    "psychological_test_summary": "입력된 심리검사 요약"
  },
  "partially_available_fields": {
    "심리검사 결과": "입력 요약은 있으나 검사명, 실시일, 세부 척도, 상담적 해석은 상담사 확인 필요"
  },
  "missing_required_fields": [
    "내담자 기본 정보",
    "상담신청경위",
    "이전 상담 경험",
    "가족관계",
    "사례개념화 및 상담방향성",
    "슈퍼비전 요청사항"
  ],
  "notice": "현재 MVP에서는 확정된 회기요약을 기반으로 일부 항목만 미리보기합니다."
}
```

## 9. Retrieval Context

`ENABLE_RAG=1`과 Supabase 설정이 있을 때 다음 필드가 채워질 수 있습니다. 없으면 빈 배열 또는 `null`로 반환되어 기존 동작을 유지합니다.

```json
{
  "retrieved_case_context": [
    {
      "source_ref": "stored_session_note:<session_id>",
      "session_id": "<session_id>",
      "session_number": 2,
      "session_date": "2026-05-03",
      "summary": "이전 회기 요약",
      "confirmed_note": {},
      "evidence_items": [
        {
          "id": "<evidence_id>",
          "source_type": "direct",
          "source_ref": "stored_evidence:<evidence_id>",
          "source_text": "이전 회기의 근거 문장",
          "linked_field": "session_content"
        }
      ]
    }
  ],
  "retrieved_template_context": {
    "target_document_type": "session_note",
    "required_fields": ["주호소", "상담 내용", "다음 계획"],
    "optional_fields": [],
    "counselor_review_fields": ["사례개념화"],
    "missing_field_checklist": ["목표 달성 정도"],
    "source_refs": ["kb_template:<chunk_id>"]
  },
  "retrieved_privacy_context": [
    {
      "source_ref": "kb_privacy:<chunk_id>",
      "title": "Privacy minimization principle",
      "category": "privacy_rule",
      "rule": "필요 최소한의 정보만 저장한다는 원칙",
      "warning": "저장 전 비식별화와 동의 필요 여부를 확인하세요."
    }
  ],
  "retrieval_report": {
    "enabled": true,
    "case_context_count": 1,
    "template_context_found": true,
    "privacy_rule_count": 1,
    "failures": [],
    "notices": []
  }
}
```

## 10. GenerateNoteResponse

```json
{
  "structured_case_data": {},
  "evidence_mapped_data": {},
  "session_summary_draft": {},
  "verification_report": {},
  "document_transform_preview": {},
  "confirmed_session_note": {},
  "sanitized_input": {},
  "retrieved_case_context": [],
  "retrieved_template_context": null,
  "retrieved_privacy_context": [],
  "retrieval_report": {},
  "persistence_report": {},
  "stub": true
}
```

## 11. 원칙

- 모든 LLM 출력은 Pydantic model로 검증합니다.
- 입력에 없는 정보는 확정적으로 추론하지 않습니다.
- 진단, 위험 평가, 상담사 평가, 사례개념화의 최종 판단은 자동화하지 않습니다.
- `reflection`, `case_conceptualization`, `goal_attainment`는 상담사 확인 필요로 표시합니다.
- RAG는 이전 회기 기록, 문서 양식, 개인정보/윤리/보안 경계 검토에만 사용합니다.
