# 개발 계획

이 문서는 현재 구현 상태와 다음 작업을 맞추기 위한 MVP V1 개발 체크리스트입니다.

## 현재 완료된 checkpoint

### 1. 문서/제품 방향 정리

- README와 핵심 docs를 MVP V1 방향으로 정리
- Re:mind의 주 경로를 React + FastAPI + LangGraph + optional Supabase retrieval로 정의

### 2. Backend MVP V1 pipeline

- `backend/app/schemas/note.py`에 MVP V1 Pydantic schema 정의
- `backend/app/graph/graph.py`에 LangGraph workflow 구현
- `backend/app/graph/nodes.py`에 retrieval-aware node 구현
- `POST /api/notes/generate` 구현
- `GET /api/health` 구현
- OpenAI API key가 없거나 `USE_STUB=1`이면 deterministic stub output으로 동작
- `ENABLE_RAG=1`일 때 case memory, document template, privacy/ethics/security retrieval 시도
- `ENABLE_PERSISTENCE=1`과 `persist=true`일 때 Supabase 저장 시도
- `backend/smoke_test.py` 추가

### 3. Frontend MVP V1 demo

- `frontend/src/pages/SessionDraftPage.tsx`에 한 페이지 데모 구현
- 회기 자료 입력
- 처리 단계 표시
- 구조화 결과 탭
- 회기요약 초안 textarea 편집
- 검증 리포트 탭
- retrieval 요약 패널
- 문서 변환 preview 탭
- Raw JSON 확인

### 4. Sample data

- `sample_data/session_input_001.json`을 `SessionInput` schema에 맞춤
- `sample_data/session_output_001.json`을 `/api/notes/generate`의 full API response에 맞춤

## 현재 검증 명령

Backend:

```bash
cd backend
uv run python smoke_test.py
```

Frontend:

```bash
cd frontend
pnpm build
```

`pnpm`이 없는 환경에서는 다음으로 같은 build script를 검증할 수 있습니다.

```bash
npm run build
```

## 다음 작업 후보

1. frontend에서 확정된 회기 기록 영역을 실제 interaction으로 정리
2. 검증 리포트 표시 문구와 badge taxonomy 개선
3. Document Transform preview의 부족 필드 구조 정교화
4. 사용자 인터뷰 기반 회기요약 section label 조정

## MVP V1에서 계속 제외할 것

- 인증/회원가입
- 파일 업로드
- 음성 업로드 또는 실시간 STT
- pgvector 기반 의미 검색
- AI 슈퍼비전
- 자동 사례개념화
- 정식 Word/HWP export
- 결제/예약/관리자 기능
