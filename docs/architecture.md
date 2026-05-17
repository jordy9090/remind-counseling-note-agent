# Architecture

## 1. 개요

Re:mind MVP V0의 주 경로는 React frontend, FastAPI backend, LangGraph 기반 6-agent workflow입니다.

```text
React Frontend
  ↓
FastAPI
  ↓
LangGraph Workflow
  ↓
OpenAI API 또는 deterministic stub
  ↓
Pydantic validated JSON
```

Streamlit은 legacy/optional quick demo이며, 주 경로는 React + FastAPI입니다.

## 2. Frontend

Frontend 위치:

```text
frontend/src/pages/SessionDraftPage.tsx
```

Frontend 책임:

- 회기 입력 수집
- `POST /api/notes/generate` 호출
- 처리 단계 표시
- 구조화 결과 표시
- 회기요약 초안 textarea 편집
- 검증 리포트 표시
- 문서 변환 preview 표시
- Raw JSON 확인

API base URL:

- 기본값: `http://localhost:8000`
- 환경변수: `VITE_API_BASE_URL`

## 3. Backend

Backend 위치:

```text
backend/app/main.py
backend/app/api/routes/health.py
backend/app/api/routes/notes.py
backend/app/schemas/note.py
backend/app/graph/graph.py
backend/app/graph/nodes.py
```

Backend 책임:

- Pydantic 입력/출력 검증
- LangGraph workflow 실행
- OpenAI API 또는 deterministic stub 호출
- 구조화된 JSON 응답 반환

Primary routes:

```text
GET  /api/health
POST /api/notes/generate
```

Legacy compatibility route:

```text
POST /api/notes/session-draft
```

## 4. LangGraph Workflow

실제 구현은 `backend/app/graph/graph.py`에 있습니다.

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
transform_document_preview
```

## 5. Agent 책임

### sanitize_input

- 입력 자료 정제
- 상담사 메모, 축어록/STT, 이전 회기 요약 분리
- 전화번호, 이메일, 학교명, 실명 후보 탐지

### structure_session

- 공통 상담 문서 구조 생성
- 주호소, 회기 주제, 상담 내용, 상담자 개입, 내담자 반응, 주요 발화, 비언어 메모, reflection 후보, 추후 계획 추출

### map_evidence

- 각 구조화 항목을 source reference와 연결
- `direct`, `inferred`, `counselor_input`, `previous_context`, `needs_review`, `mixed`, `model_inference` 구분

### generate_summary

- 구조화 결과와 근거 매핑 결과를 바탕으로 회기요약 초안 생성
- frontend에서 섹션별 textarea로 수정 가능한 형태 반환

### verify_output

- 입력 근거 있음
- 입력 근거 부족 / 추론 가능성
- 민감정보 후보
- 상담사 직접 판단 필요 항목 분리

### transform_document_preview

- 확정된 회기요약을 슈퍼비전 보고서 또는 종결 보고서로 확장하기 위한 preview 제공
- MVP V0에서는 정식 문서 변환/export가 아니라 부족 필드와 일부 preview section만 반환

## 6. 데이터 저장

MVP V0에서는 세션 데이터를 데이터베이스에 저장하지 않습니다.

모든 데이터는 요청 단위로 처리합니다. DB 저장, 인증, RAG, 파일 업로드, 음성 저장은 MVP V0 제외 범위입니다.

## 7. 출력 검증 원칙

모든 LLM 출력은 Pydantic model로 검증합니다.

입력에 없는 정보는 확정적으로 서술하지 않습니다. 필요한 경우 `inferred`, `model_inference`, `needs_review`, `requires_review`로 표시합니다.

상담 진단, 위험 평가, 상담사 평가, 사례개념화의 최종 판단은 자동화하지 않습니다.
