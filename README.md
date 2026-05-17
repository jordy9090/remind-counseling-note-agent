# Re:mind

Re:mind는 정신건강 상담사를 위한 AI 보조 상담 문서화 워크스페이스입니다.

상담사가 상담 이후에 가진 상담사 메모, 축어록/STT 텍스트, 이전 회기 요약을 바탕으로 구조화된 회기요약 초안을 생성합니다. 또한 생성된 내용이 입력 근거에 기반한 것인지, 모델 추론인지, 민감정보 후보인지, 상담사 확인이 필요한 영역인지 구분하는 검증 리포트를 제공합니다.

## 제품 목표

Re:mind는 상담을 수행하거나, 상담사를 평가하거나, 임상적 판단을 대체하지 않습니다.

MVP의 목표는 상담 이후 반복되는 문서화 부담을 줄이고, 상담사가 AI가 생성한 초안을 안전하게 검토, 수정, 확정할 수 있도록 돕는 것입니다.

## 핵심 가치

- 상담사 메모와 축어록을 바탕으로 구조화된 회기요약 초안 생성
- 생성된 내용과 원문 근거 연결
- 입력에 없는 주장과 민감정보 후보 표시
- AI 추론과 상담사 판단 영역 분리
- 상담사 검토, 수정, 확정을 전제로 한 human-in-the-loop 흐름 지원
- 향후 슈퍼비전 보고서와 종결 보고서 형식으로 문서 변환 확장

## MVP V0 범위

MVP V0는 다음 흐름에 집중합니다.

1. 회기 자료 입력
2. 입력 정제
3. 상담 내용 구조화
4. 근거 매핑
5. 회기요약 초안 생성
6. 검증 리포트 생성
7. 상담사 수정 및 확정

## 입력 예시

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_date": "2026-05-17",
  "counselor_name": "Counselor A",
  "counselor_memo": "...",
  "transcript_text": "...",
  "previous_session_summary": "..."
}
```

## 출력 예시

```json
{
  "structured_case_data": {},
  "evidence_mapped_data": {},
  "session_summary_draft": {},
  "verification_report": {},
  "confirmed_session_note": {}
}
```

## Agent Workflow

Re:mind MVP는 6개의 agent 흐름을 기준으로 설계합니다.

### 1. Input Sanitization Agent

민감정보 후보를 탐지하고 입력 자료를 정제합니다.

### 2. Session Structuring Agent

상담사 메모, 축어록, 이전 회기 요약을 공통 중간 구조로 변환합니다.

### 3. Evidence Mapping Agent

각 구조화 항목의 출처를 상담사 메모, 축어록, 이전 회기 요약, 모델 추론으로 연결합니다.

### 4. Session Summary Draft Agent

상담사가 수정할 수 있는 회기요약 초안을 생성합니다.

### 5. Verification & Review Agent

근거 부족 주장, 민감정보 후보, 상담사 확인 필요 항목을 탐지합니다.

### 6. Document Transform Agent

확정된 회기요약을 슈퍼비전 보고서 또는 종결 보고서 초안으로 변환합니다. MVP V0에서는 preview 수준으로 구현할 수 있습니다.

## 기술 스택

Frontend:

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui

Backend:

- FastAPI
- Python 3.11
- LangGraph
- Pydantic
- OpenAI API

Package Manager:

- Frontend: pnpm
- Backend: uv

Database:

- MVP V0에서는 데이터베이스를 사용하지 않습니다.
- 회기 데이터는 데모 목적상 요청 단위로 처리합니다.

## 프로젝트 구조

```text
remind-counseling-note-agent/
├── README.md
├── AGENTS.md
├── streamlit_app.py
├── requirements-streamlit.txt
├── docs/
│   ├── product_spec.md
│   ├── mvp_scope.md
│   ├── architecture.md
│   ├── schema.md
│   ├── api_contract.md
│   ├── demo_scenario.md
│   └── development_plan.md
├── sample_data/
│   ├── session_input_001.json
│   └── session_output_001.json
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── app/
│   │   ├── main.py
│   │   ├── pipeline.py
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── health.py
│   │   │       └── notes.py
│   │   ├── graph/
│   │   ├── schemas/
│   │   ├── prompts/
│   │   └── services/
│   └── uv.lock
└── frontend/
    ├── package.json
    └── src/
```

## 빠른 실행

### Streamlit 데모 UI

```bash
streamlit run streamlit_app.py
```

브라우저에서 `http://localhost:8501`로 접속합니다.

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

API 문서는 `http://localhost:8000/docs`에서 확인할 수 있습니다.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

## 개발 우선순위

첫 번째 개발 마일스톤은 다음 흐름을 연결하는 것입니다.

```text
Input
  ↓
Structured Case Data
  ↓
Session Summary Draft
  ↓
Verification Report
```

UI polish, 데이터베이스 저장, 문서 export, 고급 커스터마이징은 이후 버전에서 다룹니다.

## 문서

- [제품 명세](docs/product_spec.md)
- [MVP 범위](docs/mvp_scope.md)
- [아키텍처](docs/architecture.md)
- [스키마](docs/schema.md)
