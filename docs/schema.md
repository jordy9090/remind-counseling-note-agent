# Schema

## 1. SessionInput

회기 자료 입력 스키마입니다.

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_date": "2026-05-17",
  "counselor_name": "Counselor A",
  "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고 중심으로 진행함.",
  "transcript_text": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
  "previous_session_summary": "이전 회기에서는 자기이해와 진로 가치 탐색을 중심으로 다룸.",
  "counseling_goal": "진로 선택 과정에서 자기이해를 높이고 실행 계획을 세움.",
  "psychological_test_summary": "검사 결과는 상담사가 확인 후 입력.",
  "key_issue_tags": ["진로불안", "자기비난", "취업준비"],
  "nonverbal_notes": "말의 속도가 느려지고 한숨이 잦았음."
}
```

필수 필드는 다음과 같습니다.

- `case_id`
- `session_number`
- `session_date`
- `counselor_name`
- `counselor_memo`
- `transcript_text`
- `previous_session_summary`

선택 필드는 다음과 같습니다.

- `counseling_goal`
- `psychological_test_summary`
- `key_issue_tags`
- `nonverbal_notes`

## 2. SanitizedInput

입력 정제 결과입니다.

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_date": "2026-05-17",
  "sources": {
    "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고 중심으로 진행함.",
    "transcript_text": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
    "previous_session_summary": "이전 회기에서는 자기이해와 진로 가치 탐색을 중심으로 다룸."
  },
  "sensitive_info_candidates": [
    {
      "text": "실명 또는 학교명으로 보이는 표현",
      "source": "transcript_text",
      "recommendation": "가명 또는 케이스 ID로 대체"
    }
  ]
}
```

## 3. StructuredCaseData

상담 자료를 공통 중간 구조로 변환한 결과입니다.

```json
{
  "presenting_problem": [
    {
      "content": "내담자는 진로 불확실성과 취업 불안을 호소함.",
      "evidence_type": "direct",
      "source_refs": ["transcript:Cl-1", "counselor_memo"]
    }
  ],
  "session_theme": [
    {
      "content": "진로 불안과 자기비난 사고 탐색",
      "evidence_type": "direct",
      "source_refs": ["counselor_memo"]
    }
  ],
  "session_content": [],
  "counselor_interventions": [],
  "client_responses": [],
  "key_client_utterances": [],
  "nonverbal_observations": [],
  "reflection_candidates": [],
  "next_plan": []
}
```

## 4. EvidenceMappedData

각 구조화 항목에 근거 출처를 연결한 결과입니다.

```json
{
  "items": [
    {
      "field": "presenting_problem",
      "content": "내담자는 진로 불확실성과 취업 불안을 호소함.",
      "evidence_type": "direct",
      "source_refs": ["transcript:Cl-1", "counselor_memo"],
      "requires_review": false
    },
    {
      "field": "client_response",
      "content": "내담자는 자기비난 사고를 인식하는 반응을 보임.",
      "evidence_type": "inferred",
      "source_refs": ["transcript"],
      "requires_review": true
    }
  ]
}
```

근거 유형은 다음 값을 사용합니다.

- `direct`
- `inferred`
- `counselor_input`
- `previous_context`
- `needs_review`
- `mixed`

## 5. SessionSummaryDraft

상담사가 편집할 수 있는 회기요약 초안입니다.

```json
{
  "session_info": {
    "case_id": "CASE001",
    "session_number": 3,
    "session_date": "2026-05-17"
  },
  "session_theme": {
    "text": "진로 불안과 자기비난 사고 탐색",
    "evidence_type": "direct",
    "source_refs": ["counselor_memo"]
  },
  "presenting_problem": {
    "text": "내담자는 진로가 불확실하다고 느끼며 취업 준비 과정에서 불안을 경험하고 있다.",
    "evidence_type": "direct",
    "source_refs": ["transcript:Cl-1"]
  },
  "session_content": {
    "text": "이번 회기에서는 진로 불확실성과 자기비난 사고를 중심으로 내담자의 사고 패턴을 탐색하였다.",
    "evidence_type": "mixed",
    "source_refs": ["counselor_memo", "transcript"]
  },
  "counselor_intervention": {
    "text": "상담자는 내담자의 자동사고를 탐색하고, 자기비난 표현을 구체화하도록 질문하였다.",
    "evidence_type": "direct",
    "source_refs": ["counselor_memo"]
  },
  "client_response": {
    "text": "내담자는 자신의 불안과 비교 사고를 인식하는 반응을 보였다.",
    "evidence_type": "inferred",
    "source_refs": ["transcript"]
  },
  "reflection": {
    "text": "상담자 reflection은 상담사가 직접 작성하거나 확인해야 한다.",
    "evidence_type": "counselor_input",
    "source_refs": []
  },
  "next_plan": {
    "text": "다음 회기에서는 자동사고 기록지를 바탕으로 구체적인 행동 실험 가능성을 검토한다.",
    "evidence_type": "direct",
    "source_refs": ["counselor_memo"]
  }
}
```

## 6. VerificationReport

회기요약 초안의 검증 결과입니다.

```json
{
  "grounded_items": [
    {
      "claim": "내담자는 진로 불확실성과 취업 불안을 호소했다.",
      "source_refs": ["transcript:Cl-1", "counselor_memo"]
    }
  ],
  "weakly_grounded_items": [
    {
      "claim": "내담자는 자기비난 사고 패턴을 보인다.",
      "reason": "입력에 자기비난 관련 메모는 있으나, 구체적 사고 패턴은 상담사 확인이 필요함.",
      "recommendation": "상담사가 유지, 수정, 삭제 여부를 판단"
    }
  ],
  "unsupported_or_risky_claims": [
    {
      "claim": "내담자의 불안은 부모 기대 내면화에서 비롯되었다.",
      "reason": "부모 기대에 대한 언급은 있으나 원인으로 확정할 근거는 부족함.",
      "recommendation": "원인으로 단정하지 말고 상담사 판단 영역으로 이동"
    }
  ],
  "sensitive_info_items": [
    {
      "text": "실명, 학교명, 학번, 연락처 등으로 보이는 표현",
      "recommendation": "가명 또는 케이스 ID로 대체"
    }
  ],
  "requires_counselor_review": [
    {
      "field": "reflection",
      "reason": "상담자 내적 경험과 임상적 판단 영역"
    },
    {
      "field": "case_conceptualization",
      "reason": "MVP V0 자동 생성 대상이 아님"
    }
  ]
}
```

## 7. ConfirmedSessionNote

상담사가 수정하고 확정한 최종 회기 기록입니다.

```json
{
  "session_info": {
    "case_id": "CASE001",
    "session_number": 3,
    "session_date": "2026-05-17"
  },
  "confirmed_sections": {
    "session_theme": "진로 불안과 자기비난 사고 탐색",
    "presenting_problem": "내담자는 진로 불확실성과 취업 준비 과정의 불안을 호소함.",
    "session_content": "상담사는 자동사고와 자기비난 표현을 중심으로 사고 패턴을 탐색함.",
    "counselor_intervention": "상담자는 개방형 질문과 구체화 질문을 사용함.",
    "client_response": "내담자는 비교 사고를 인식하고 불안을 언어화함.",
    "reflection": "상담사가 직접 작성한 reflection.",
    "next_plan": "다음 회기에서 자동사고 기록지를 검토함."
  },
  "confirmed_by_counselor": true
}
```

## 8. DocumentTransformPreview

MVP V0에서 preview 수준으로 제공할 문서 변환 출력입니다.

```json
{
  "document_type": "supervision_report",
  "preview_sections": {
    "session_summary": "확정된 회기요약 기반 미리보기",
    "client_main_issue": "입력 근거 기반으로 채울 수 있는 항목",
    "supervision_question": "상담사 추가 입력 필요"
  },
  "missing_required_fields": [
    "내담자 기본 정보",
    "상담신청경위",
    "이전 상담 경험",
    "가족관계",
    "심리검사 결과",
    "사례개념화 및 상담방향성",
    "슈퍼비전 요청사항"
  ]
}
```

## 9. 원칙

- 모든 LLM 출력은 Pydantic model로 검증합니다.
- 입력에 없는 정보는 확정적으로 추론하지 않습니다.
- 진단, 위험 평가, 상담사 평가, 사례개념화의 최종 판단은 자동화하지 않습니다.
- `reflection`, `case_conceptualization`, `risk_judgment` 같은 영역은 상담사 확인 필요로 표시합니다.
