# Re:mind

Re:mind는 심리상담사를 위한 AI 보조 상담 문서화 워크스페이스입니다.

MVP V1의 주 경로는 **React + FastAPI + LangGraph 기반 lightweight retrieval-aware workflow**입니다. 상담사가 상담 이후에 가진 상담사 메모, 축어록/STT 텍스트, 이전 회기 요약을 입력하면 backend가 note generation workflow를 실행하고, frontend가 회기요약 초안과 근거 확인 결과를 카드 형태로 보여줍니다.

## 제품 원칙

Re:mind는 상담을 수행하거나, 상담사를 평가하거나, 임상적 판단을 대체하지 않습니다.

- 입력에 없는 정보는 확정적으로 쓰지 않습니다.
- AI 추론, 근거 부족, 상담사 확인 필요 영역을 분리합니다.
- `reflection`, `case_conceptualization`, `goal_attainment`는 상담사 확인 필요 영역으로 표시합니다.
- 생성된 초안은 상담사 검토 전 최종 기록으로 사용하지 않습니다.
- RAG는 상담 판단 보강이 아니라 `case memory`, `document template`, `privacy/ethics/security guardrail`에만 사용합니다.
- 진단, 임상적 위험도 점수화, 치료 권고, 심리검사 자동 해석은 생성하지 않습니다.
- 현재 구현은 production-ready RAG나 실서비스 상담 기록 저장소가 아닙니다. 실제 상담 데이터는 인증, RLS, 감사 로그, 보관기간 정책 전에는 저장하지 않습니다.

## MVP V1 기능 범위

포함:

1. 회기 자료 입력
2. 입력 정제와 민감정보 후보 탐지
3. Supabase 기반 선택적 저장
4. `case_id` 기반 이전 회기 retrieval
5. 상담 문서 양식 KB retrieval
6. 개인정보/윤리/보안 규칙 retrieval
7. 상담 내용 구조화
8. 근거 매핑
9. 회기요약 초안 생성
10. 검증 리포트 생성
11. 문서 변환 preview
12. 상담사 수정용 회기요약 textarea UI
13. 최종 문서 DOCX 내보내기
14. PDF 내보내기 서버 capability 확인과 지원 환경에서의 PDF 내보내기
15. PDF/DOCX/TXT 문서 업로드 텍스트 추출
16. 음성 업로드 UI와 자동 축어록 capability 확인

제외:

- 인증/회원가입
- 스캔 이미지 PDF OCR
- 기본 활성화된 음성 STT, 실시간 녹음, 화자 분리
- pgvector 기반 의미 검색
- 검증된 HWPX 템플릿 기반 내보내기
- 결제/예약/관리자 기능
- AI 슈퍼비전 또는 자동 사례개념화

문서 업로드는 원본 파일을 저장하지 않고 임시 파일에서 텍스트만 추출한 뒤 정리합니다. TXT는 UTF-8/BOM, DOCX는 문단과 표, PDF는 텍스트 레이어만 지원합니다. 스캔 이미지 PDF는 OCR을 지원하지 않으며 경고를 반환합니다. 음성 원본은 브라우저 세션의 `File` 참조와 object URL로만 재생/재시도에 사용하며 서버나 Supabase에 영구 저장하지 않습니다. 음성 자동 축어록은 기본 비활성화이고, `AUDIO_TRANSCRIPTION_STUB=1`이면 업로드 음성을 분석하지 않는 시연용 예시 축어록을 반환합니다. 실제 STT는 `AUDIO_TRANSCRIPTION_STUB=0`, `ENABLE_AUDIO_TRANSCRIPTION=1`, optional `audio-stt`/`audio-diarization` 의존성이 준비된 로컬/서버에서만 동작합니다.

현재 MVP에는 인증이 없습니다. 공개 배포나 공유 데모 환경에는 실제 내담자를 식별할 수 있는 상담 자료, 원본 음성, 심리검사 자료를 업로드하지 마세요.

## API 계약 요약

Primary API:

```text
GET  /api/health
POST /api/notes/generate
GET  /api/documents/capabilities
POST /api/documents/export
POST /api/materials/documents/extract
GET  /api/audio/capabilities
POST /api/audio/transcribe
```

`POST /api/notes/generate`는 Pydantic으로 검증된 full `GenerateNoteResponse`를 반환합니다. Frontend는 화면 표시를 위해 필요한 필드를 클라이언트에서 변환합니다.

`GET /api/documents/capabilities`는 서버가 DOCX/PDF/HWPX 내보내기를 실제로 지원할 수 있는지 반환합니다. PDF는 WeasyPrint와 Pango/GObject 계열 시스템 라이브러리, 한국어 fallback 폰트가 준비된 환경에서만 활성화됩니다.

`POST /api/documents/export`는 최종문서 화면에서 수정된 최신 섹션을 DOCX 또는 PDF byte stream으로 반환합니다. HWPX는 스키마와 exporter 인터페이스만 준비되어 있으며, 검증된 HWPX 템플릿이 추가되기 전까지는 422를 반환합니다.

`POST /api/materials/documents/extract`는 multipart `file` 필드로 PDF/DOCX/TXT를 받아 텍스트를 추출합니다. 기본 문서 업로드 제한은 20MB이며 `DOCUMENT_UPLOAD_MAX_BYTES`로 조정할 수 있습니다. DOCX는 압축 member 수, 압축 해제 총량, 압축률 제한을 추가로 검사하며 `DOCX_MAX_ARCHIVE_MEMBERS`, `DOCX_MAX_UNCOMPRESSED_BYTES`, `DOCX_MAX_COMPRESSION_RATIO`로 조정할 수 있습니다.

`GET /api/audio/capabilities`는 음성 업로드, 자동 축어록, 화자 분리 지원 상태와 `runtime_mode`(`disabled`, `stub`, `real`)를 반환합니다. `POST /api/audio/transcribe`는 multipart `file`, 선택 `language`, 선택 `task`, 선택 `expected_speakers`(기본 2, 범위 1~4)를 받으며 기본 음성 업로드 제한은 500MB입니다. `AUDIO_UPLOAD_MAX_BYTES`, `AUDIO_TRANSCRIPTION_STUB`, `ENABLE_AUDIO_TRANSCRIPTION`, `ENABLE_AUDIO_DIARIZATION`, `WHISPER_MODEL_SIZE`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE` 환경변수로 제어합니다.

OpenAI API key가 없거나 `USE_STUB=1`이면 deterministic mock/stub output으로 동작합니다. Supabase 환경변수가 없거나 `ENABLE_RAG=0`, `ENABLE_PERSISTENCE=0`이면 기존처럼 요청 단위 처리만 수행합니다. 따라서 API key와 Supabase credentials 없이도 데모와 smoke test를 실행할 수 있습니다.

## 프로젝트 구조

```text
remind-counseling-note-agent/
├── README.md
├── docs/
│   ├── product_spec.md
│   ├── mvp_scope.md
│   ├── architecture.md
│   ├── schema.md
│   ├── api_contract.md
│   ├── demo_scenario.md
│   ├── security_checklist.md
│   ├── supabase_schema.sql
│   ├── kb_seed_examples.json
│   └── development_plan.md
├── scripts/
│   └── seed_kb_examples.py
├── sample_data/
│   ├── session_input_001.json
│   └── session_output_001.json
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── smoke_test.py
│   └── app/
│       ├── main.py
│       ├── api/routes/
│       │   ├── health.py
│       │   └── notes.py
│       ├── core/
│       │   └── config.py
│       ├── graph/
│       │   ├── graph.py
│       │   └── nodes.py
│       ├── prompts/
│       │   ├── structure_prompt.py
│       │   ├── summary_prompt.py
│       │   └── verification_prompt.py
│       ├── schemas/
│       │   └── note.py
│       └── services/
│           ├── llm.py
│           ├── retrieval.py
│           ├── supabase_store.py
│           └── supabase_storage.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── api/client.ts
        ├── pages/SessionDraftPage.tsx
        └── types/session.ts
```

## 실행 방법

### Backend

```bash
cd backend
uv sync --link-mode=copy
uv run uvicorn app.main:app --reload
```

`--link-mode=copy` avoids hard-link issues that can occur on Windows or cloud-synced folders. If `uv` is not installed, run `pip install uv` first.

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

Supabase 저장과 lightweight RAG를 켜려면 Supabase SQL editor에서 [docs/supabase_schema.sql](docs/supabase_schema.sql)을 실행한 뒤 backend `.env`에 다음을 설정합니다.

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ENABLE_PERSISTENCE=1
ENABLE_RAG=1
SAVE_RAW_INPUT=0
```

`POST /api/notes/generate`에서 `persist=true`를 보낸 요청만 저장합니다. `SAVE_RAW_INPUT=0`이 기본값이며, 이 경우 `sessions.raw_input_text`는 저장하지 않고 sanitized input과 metadata만 저장합니다. 실서비스 전에는 인증, Row Level Security, 접근권한, 감사 로그, 보관기간 정책을 먼저 확정해야 합니다.

KB seed 예시는 [docs/kb_seed_examples.json](docs/kb_seed_examples.json)에 있습니다. 유료 검사 매뉴얼, 저작권 있는 상담 자료, 실제 내담자 기록은 seed에 넣지 않습니다. Supabase schema를 만든 뒤 demo KB를 넣으려면 repository root에서 다음을 실행합니다.

```bash
python scripts/seed_kb_examples.py
```

보안 경계는 [docs/security_checklist.md](docs/security_checklist.md)를 기준으로 확인합니다.

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

`pnpm`이 설치되어 있지 않다면 `npm install`과 `npm run dev`를 사용할 수 있습니다. 빌드 검증은 `pnpm build` 또는 `npm run build`로 실행합니다.

## 검증 명령

Backend smoke test:

```bash
cd backend
uv sync --link-mode=copy
uv run python smoke_test.py
```

Smoke test에는 노트 생성, 임시저장, DOCX/PDF export 계약, 문서 업로드 추출, 음성 capability/비활성화 응답, 업로드 크기 제한, 임시파일 정리 검증이 포함됩니다.

PDF export까지 강제 검증하려면 Linux/Ubuntu 환경에서 WeasyPrint 시스템 의존성과 한국어 폰트를 설치한 뒤 실행합니다. GitHub Actions의 `backend-pdf-export` job은 `fonts-noto-cjk`, Pango/GObject 관련 패키지를 설치하고 `REQUIRE_PDF_EXPORT=1 uv run python smoke_test.py`를 실행합니다.

Frontend build:

```bash
cd frontend
pnpm verify:material-workflow
pnpm verify:audio-transcript-workflow
pnpm build
```

`pnpm`이 없으면:

```bash
npm run build
```

Sample data는 [sample_data/session_input_001.json](sample_data/session_input_001.json)과 [sample_data/session_output_001.json](sample_data/session_output_001.json)을 사용합니다.

문서 업로드를 로컬에서 직접 확인하려면 backend 서버를 켠 뒤 실행합니다.

```bash
printf "상담 메모\n둘째 줄\n" > sample_data/upload_sample.txt
curl -F "file=@sample_data/upload_sample.txt;type=text/plain" http://localhost:8000/api/materials/documents/extract
curl http://localhost:8000/api/audio/capabilities
```

H100에서 실제 faster-whisper/pyannote 런타임을 켜는 방법은 [docs/h100_audio_runbook.md](docs/h100_audio_runbook.md)를 따릅니다. 연구용 GPU backend는 공개 인터넷에 노출하지 않고 SSH local port forwarding으로 검증합니다.

## 문서

- [제품 명세](docs/product_spec.md)
- [MVP 범위](docs/mvp_scope.md)
- [아키텍처](docs/architecture.md)
- [스키마](docs/schema.md)
- [API 계약](docs/api_contract.md)
- [H100 음성 STT runbook](docs/h100_audio_runbook.md)
- [보안 체크리스트](docs/security_checklist.md)
