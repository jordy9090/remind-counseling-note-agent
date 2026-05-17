# Architecture

## 1. 개요

Re:mind MVP V0는 React frontend, FastAPI backend, LangGraph 기반 multi-agent workflow로 구성됩니다.

```text
Frontend
  ↓
FastAPI
  ↓
LangGraph Workflow
  ↓
OpenAI API
  ↓
Structured Output
```

## 2. Frontend

Frontend의 책임은 다음과 같습니다.

- 회기 입력 수집
- backend API로 입력 전송
- 구조화 결과 표시
- 회기요약 초안 표시
- 검증 리포트 표시
- 상담사 수정 및 확정 지원

주요 페이지:

- `SessionDraftPage`

주요 UI 영역:

- `InputPanel`
- `ProcessingStatus`
- `ResultTabs`
- `ConfirmedNotePanel`

결과 탭:

- 구조화 결과
- 회기요약 초안
- 검증 리포트
- 문서 변환 Preview

## 3. Backend

Backend의 책임은 다음과 같습니다.

- Pydantic을 통한 입력 검증
- LangGraph workflow 실행
- 구조화된 출력 반환
- 오류를 안전하게 처리

주요 API route:

```text
POST /api/notes/generate
```

현재 구현에서 기존 route가 다를 수 있으므로, MVP 정리 과정에서 route naming을 통일합니다.

## 4. LangGraph Workflow

MVP V0의 기본 workflow는 다음과 같습니다.

```text
sanitize_input
  ↓
structure_session
  ↓
map_evidence
  ↓
generate_summary
  ↓
verify_output
  ↓
transform_document
```

V0에서는 `transform_document`를 preview 수준으로 구현할 수 있습니다.

## 5. Agent 책임

### sanitize_input

- 민감정보 후보 탐지
- 입력 형식 정규화
- 상담사 메모, 축어록, 이전 회기 요약 분리

### structure_session

- 상담 문서화에 공통적으로 필요한 필드 추출
- 주호소, 회기 주제, 상담 내용, 개입, 반응, 추후 계획 구성

### map_evidence

- 각 항목의 근거 출처 연결
- 상담사 메모, 축어록, 이전 회기 요약, 모델 추론, 확인 필요 구분

### generate_summary

- 구조화 결과와 근거 매핑 결과를 바탕으로 회기요약 초안 생성
- 상담사가 수정 가능한 섹션형 출력 생성

### verify_output

- 입력에 없는 주장 탐지
- 과도한 해석 탐지
- 민감정보 후보 표시
- 상담사 검토 필요 영역 표시

### transform_document

- 확정된 회기요약을 목적별 문서 초안으로 변환
- 슈퍼비전 보고서, 종결 보고서, 기관 양식용 요약으로 확장 가능
- MVP V0에서는 preview-level logic으로 처리

## 6. 데이터 저장

MVP V0에서는 세션 데이터를 데이터베이스에 저장하지 않습니다.

모든 데이터는 요청 단위로 처리합니다. 이 방식은 초기 데모를 가볍게 유지하고, 민감한 상담 데이터의 저장 위험을 줄입니다.

저장 기능은 V1 이후 전문가 검토와 보안 정책 설계 후 검토합니다.

## 7. 출력 검증 원칙

모든 LLM 출력은 Pydantic model로 검증합니다.

입력에 없는 정보는 확정적으로 서술하지 않습니다. 필요한 경우 `model_inference`, `needs_review`, `requires_counselor_review`로 표시합니다.

상담 진단, 위험 평가, 상담사 평가, 사례개념화의 최종 판단은 자동화하지 않습니다.
