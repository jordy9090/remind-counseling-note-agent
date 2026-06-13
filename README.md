# Re:mind

Re:mind는 정신건강 상담사를 위한 AI 보조 상담 문서화 워크스페이스입니다.

MVP V0의 주 경로는 **React + FastAPI + LangGraph**입니다. 상담사가 상담 이후에 가진 상담사 메모, 축어록/STT 텍스트, 이전 회기 요약을 입력하면 backend가 기존 note generation workflow를 실행하고, frontend가 회기요약 초안과 근거 확인 결과를 카드 형태로 보여줍니다.

Streamlit 화면은 남아 있지만 현재 주 경로가 아니라 **legacy/optional quick demo**입니다.

## 제품 원칙

Re:mind는 상담을 수행하거나, 상담사를 평가하거나, 임상적 판단을 대체하지 않습니다.

- 입력에 없는 정보는 확정적으로 쓰지 않습니다.
- AI 추론, 근거 부족, 상담사 확인 필요 영역을 분리합니다.
- `reflection`, `case_conceptualization`, `goal_attainment`는 상담사 확인 필요 영역으로 표시합니다.
- 생성된 초안은 상담사 검토 전 최종 기록으로 사용하지 않습니다.

## MVP V0 기능 범위

포함:

1. 회기 자료 입력
2. 입력 정제와 민감정보 후보 탐지
3. 상담 내용 구조화
4. 근거 매핑
5. 회기요약 초안 생성
6. 검증 리포트 생성
7. 문서 변환 preview
8. 상담사 수정용 회기요약 textarea UI

제외:

- DB 저장
- 인증/회원가입
- 파일 업로드
- 음성 업로드 또는 실시간 STT
- Vector DB/RAG
- 정식 문서 export
- 결제/예약/관리자 기능
- AI 슈퍼비전 또는 자동 사례개념화

## API 계약 요약

Primary API:

```text
GET  /api/health
POST /api/notes/generate
```

`POST /api/notes/generate`는 Pydantic으로 검증된 full `GenerateNoteResponse`를 반환합니다. Frontend는 화면 표시를 위해 필요한 필드만 compact shape으로 변환합니다.

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_summary": "...",
  "main_issue": "...",
  "counselor_intervention": "...",
  "client_response": "...",
  "next_plan": "...",
  "evidence_check": [],
  "missing_items": [],
  "warnings": []
}
```

OpenAI API key가 없거나 `USE_STUB=1`이면 deterministic mock/stub output으로 동작합니다. 따라서 API key 없이도 데모와 smoke test를 실행할 수 있습니다.

## 프로젝트 구조

```text
remind-counseling-note-agent/
├── README.md
├── streamlit_app.py                  # legacy/optional quick demo
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
│   ├── uv.lock
│   ├── smoke_test.py
│   └── app/
│       ├── main.py
│       ├── pipeline.py              # Streamlit compatibility adapter
│       ├── api/routes/
│       │   ├── health.py
│       │   └── notes.py
│       ├── core/
│       │   └── config.py
│       ├── graph/
│       │   ├── graph.py
│       │   ├── nodes.py
│       │   ├── state.py
│       │   └── workflow.py
│       ├── prompts/
│       │   ├── structure_prompt.py
│       │   ├── summary_prompt.py
│       │   └── verification_prompt.py
│       ├── schemas/
│       │   ├── note.py              # current MVP V0 schema
│       │   ├── session.py           # legacy compatibility schema
│       │   ├── structured_case.py
│       │   ├── summary.py
│       │   └── verification.py
│       └── services/
│           └── llm.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── api/client.ts
        ├── pages/SessionDraftPage.tsx
        ├── types/session.ts
        └── components/
```

## 실행 방법

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

API 문서:

```text
http://localhost:8000/docs
```

Stub mode로 실행하려면 `backend/.env`에 다음을 둘 수 있습니다.

```env
USE_STUB=1
```

실제 OpenAI 호출을 사용하려면:

```env
OPENAI_API_KEY=sk-proj-your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
USE_STUB=0
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

기본 API 주소는 `http://localhost:8000`입니다. 필요하면 frontend 환경변수로 바꿀 수 있습니다.

```env
VITE_API_BASE_URL=http://localhost:8000
```

이 작업 환경에서는 `pnpm`이 PATH에 없어 검증을 `npm run build`로 수행했습니다. 프로젝트 package script는 `pnpm build`와 `npm run build` 모두 같은 `tsc && vite build`를 실행합니다.

### Legacy Streamlit Demo

Streamlit은 React + FastAPI 주 경로와 별개인 optional quick demo입니다.

```bash
streamlit run streamlit_app.py
```

또는 Python/uv 환경에 따라:

```bash
uv run streamlit run ../streamlit_app.py
```

## 검증 명령

Backend smoke test:

```bash
cd backend
uv run python smoke_test.py
```

Frontend build:

```bash
cd frontend
pnpm build
```

`pnpm`이 없으면:

```bash
npm run build
```

Sample data는 [sample_data/session_input_001.json](sample_data/session_input_001.json)과 [sample_data/session_output_001.json](sample_data/session_output_001.json)을 사용합니다.

## 문서

- [제품 명세](docs/product_spec.md)
- [MVP 범위](docs/mvp_scope.md)
- [아키텍처](docs/architecture.md)
- [스키마](docs/schema.md)
- [API 계약](docs/api_contract.md)
