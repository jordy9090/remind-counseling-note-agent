# Remind Counseling Note Agent - MVP v0

상담 회기 기록을 자동으로 구조화, 요약, 검증하는 AI 에이전트입니다.

## 프로젝트 개요

상담사가 **축어록과 메모**를 입력하면, LangGraph 기반 멀티 에이전트 워크플로우가:
1. **구조화**: 8가지 필드로 정보 정리
2. **요약**: 전문가 수준의 4가지 요약 항목 생성
3. **검증**: 근거도/민감도/판단 필요 여부를 4가지로 분류

→ 상담사가 최종 판단하여 기록을 확정하는 의사결정 지원 도구

## 폴더 구조

```
remind-counseling-note-agent/
├── README.md
├── .gitignore
├── .env.example
├── CLAUDE.md
├── streamlit_app.py          # Streamlit 데모 UI (화면 전용)
├── requirements-streamlit.txt
├── .streamlit/config.toml    # 파란색 테마
├── docs/
│   ├── mvp_spec.md           # v0-A/B 스펙
│   ├── api_contract.md       # API 명세
│   ├── demo_scenario.md      # 발표 시연 흐름
│   ├── schema.md             # 스키마 정의
│   └── development_plan.md   # 개발 일정
├── sample_data/
│   ├── session_input_001.json    # 입력 예시
│   └── session_output_001.json   # 출력 예시
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   └── app/
│       ├── main.py              # FastAPI 진입점
│       ├── pipeline.py          # run_pipeline(): UI/ API 공용 진입점 (+스텁)
│       ├── api/routes/
│       │   ├── health.py        # GET /health
│       │   └── notes.py         # POST /api/notes/session-draft
│       ├── core/
│       │   └── config.py        # 설정 관리
│       ├── schemas/
│       │   ├── session.py       # SessionInput
│       │   ├── structured_case.py
│       │   ├── summary.py
│       │   └── verification.py
│       ├── services/
│       │   └── llm.py           # OpenAI 호출 (유일한 외부 호출점)
│       ├── prompts/
│       │   ├── structure_prompt.py
│       │   ├── summary_prompt.py
│       │   └── verification_prompt.py
│       └── graph/
│           ├── state.py         # GraphState
│           ├── workflow.py      # StateGraph 조립
│           └── nodes/
│               ├── structure_node.py
│               ├── summary_node.py
│               └── verification_node.py
└── frontend/
    ├── package.json
    ├── index.html
    ├── vite.config.ts
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── postcss.config.js
    ├── components.json
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── index.css
        ├── api/client.ts        # axios + 백엔드 호출
        ├── types/session.ts     # 타입 정의
        ├── lib/utils.ts
        ├── components/
        │   ├── layout/
        │   │   ├── AppShell.tsx
        │   │   └── Header.tsx
        │   ├── ui/
        │   │   └── index.tsx    # Button, Card, Input 등
        │   └── note/
        │       ├── SessionInputForm.tsx
        │       ├── StructuredResult.tsx
        │       ├── SummaryResult.tsx
        │       └── VerificationReport.tsx
        └── pages/SessionDraftPage.tsx
```

## 빠른 시작 — Streamlit 데모 (권장)

입력 → 구조화 → 회기요약 → 검증 리포트 전체 흐름을 한 화면에서 확인하는
파란색 웹 UI입니다. LangGraph 로직은 `backend/app/` 에 분리돼 있고
`streamlit_app.py` 는 화면만 담당합니다.

```bash
pip install -r requirements-streamlit.txt
streamlit run streamlit_app.py
```

- 🌐 http://localhost:8501 에서 실행
- 🔑 **API 키 없이도 동작**: `backend/.env` 에 `OPENAI_API_KEY` 가 없거나
  `USE_STUB=1` 이면 `sample_data` 의 샘플 응답으로 전체 흐름을 보여줍니다(스텁 모드).
- 실제 분석을 보려면 `backend/.env` 에 키를 넣으세요(아래 참고).

## 실행 방법 (FastAPI + React, 전체 스택)

### 준비

1. **환경 변수 설정**
   ```bash
   cd backend
   cp .env.example .env
   # .env 파일에서 OPENAI_API_KEY 입력 (비워두면 스텁 모드)
   ```

### 백엔드 실행

```bash
cd backend
uv sync          # 의존성 설치
uv run uvicorn app.main:app --reload
```

- 🚀 http://localhost:8000 에서 API 실행
- 📖 http://localhost:8000/docs 에서 Swagger UI 확인

### 프론트엔드 실행

```bash
cd frontend
pnpm install     # 의존성 설치
pnpm dev
```

- 🌐 http://localhost:5173 에서 프론트엔드 실행

### 함께 실행하기

```bash
# 터미널 1
cd backend && uv run uvicorn app.main:app --reload

# 터미널 2
cd frontend && pnpm dev
```

## 기술 스택

- **Backend**: FastAPI, Python 3.11, LangGraph, langchain-openai, Pydantic v2, uv
- **Frontend**: React 18, TypeScript, Vite, TailwindCSS
- **LLM**: OpenAI GPT-4o-mini (환경변수로 모델 변경 가능)
- **Database**: 없음 (상태저장 없음, v1에서 추가 예정)

## v0-A 범위 (완료)

✅ **백엔드**
- 3개 노드 워크플로우 (구조화 → 요약 → 검증)
- Pydantic 스키마 (입력/출력 타입 정의)
- FastAPI 라우터 (`/api/notes/session-draft`)
- OpenAI 호출 (구조화된 출력 강제)

✅ **프론트엔드**
- 입력 폼 (좌측 고정)
- 3개 결과 카드 (우측 흐르기)
- 로딩/에러 상태 표시
- TailwindCSS 스타일링

✅ **문서**
- API 계약서
- 스키마 정의
- 샘플 데이터 (한국어 상담 사례)
- 발표 시연 시나리오

## v0-B 범위 (다음주)

- 검증 리포트 UI 개선 (색상, 아이콘)
- 결과 내보내기 (JSON, 향후 PDF)
- 수정/재생성 기능
- 슈퍼비전 워크플로우 초안

## 제외 항목 (v1+)

- ❌ 데이터베이스 저장
- ❌ 사용자 인증
- ❌ 상담 사례 관리 (CRM)
- ❌ 실시간 협업
- ❌ 모바일 앱
- ❌ 통계/리포팅

## API 예시

### 요청

```bash
curl -X POST http://localhost:8000/api/notes/session-draft \
  -H "Content-Type: application/json" \
  -d @sample_data/session_input_001.json
```

### 응답

```json
{
  "structured": {
    "basic_info": "...",
    "presenting_problem": "...",
    ...
  },
  "summary": {
    "session_content": "...",
    ...
  },
  "verification": {
    "grounded": [...],
    "ungrounded": [...],
    "sensitive": [...],
    "needs_human_judgment": [...]
  }
}
```

자세한 내용은 [docs/api_contract.md](docs/api_contract.md) 참고

## 주요 특징

1. **LangGraph 기반 멀티 에이전트**
   - 각 노드가 독립적이고 재사용 가능
   - 상태 관리로 정보 흐름 명확화

2. **구조화된 출력 강제 (Pydantic)**
   - OpenAI의 `with_structured_output()` 활용
   - 예측 불가능한 응답 방지

3. **검증 계층 (Verification)**
   - AI의 신뢰도를 명시
   - 근거 있는 vs 추측 구분
   - 민감정보 자동 플래깅

4. **한국어 우선**
   - 프롬프트, 샘플, 문서 모두 한국어
   - 한국 상담 문화 반영

## 향후 계획

- 슈퍼비전 워크플로우: 상담사가 승인 전까지 초안 상태
- 다중 모델 지원: Anthropic Claude, 로컬 모델 등
- 슬롯 기반 결과 내보내기: 고객사별 형식 커스터마이징
- 감정 분석, 위험도 판단 등 고급 검증 옵션

---

**개발**: Remind Lab | **라이선스**: MIT | **최종 업데이트**: May 2026
