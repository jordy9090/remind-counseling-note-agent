# Architecture

## 1. Runtime overview

Re:mind의 현재 제품 경로는 React frontend, FastAPI 또는 Vercel Python functions,
LangGraph 기반 문서 생성 workflow, 선택적 Supabase retrieval/persistence로 구성됩니다.

```text
React frontend
  ├─ Supabase Auth
  └─ REST API
       ├─ FastAPI backend (local/server)
       └─ Vercel Python wrappers (serverless)
            ↓
       LangGraph workflows / document and audio services
            ↓
       Optional Supabase + OpenAI + WhisperX
```

모든 생성 응답은 Pydantic schema로 검증됩니다. `USE_STUB=1`에서는 외부 모델 없이
결정론적 출력으로 smoke test와 데모를 실행할 수 있습니다.

## 2. Note-generation graph

실제 wiring은 `backend/app/graph/graph.py`에 있습니다.

```text
sanitize_input
  ↓
formulate_retrieval_query
  ↓
retrieve_case_memory
  ↓
retrieve_authoritative_kb
  ↓
finalize_retrieval_report
  ↓
structure_session
  ↓
map_evidence
  ↓
generate_summary
  ↓
verify_output
  ↓
conditional_revision
  ├─ reverify ───────────────→ verify_output
  └─ preview ────────────────→ transform_document_preview → END
```

각 retrieval node는 일반 Python service 함수를 직접 호출합니다.

- `retrieve_case_memory`: 동일 상담자·사례 범위의 이전 확정 기록 검색
- `retrieve_authoritative_kb`: 문서 양식과 개인정보·윤리 경고 규칙 검색
- `finalize_retrieval_report`: 검색 결과 수와 latency를 집계

`finalize_retrieval_report`는 reranker 모델을 호출하지 않습니다. Dense/hybrid 검색은
`backend/app/services/retrieval.py`가 담당하며 feature flag로 활성화합니다.

## 3. Supervision-report graph

`backend/app/graph/supervision_report.py`에는 한국상담심리학회 개인상담 사례 수퍼비전
보고서 형식을 만드는 별도 11-node workflow가 있습니다.

```text
load_case_context
  ↓
normalize_inputs
  ↓
build_evidence_index
  ↓
generate A sections
  ↓
generate B sections
  ↓
generate C sections
  ↓
generate supervision questions
  ↓
evidence grounding checker
  ↓
clinical safety guard
  ↓
build AI review panel
  ↓
format report
```

이 workflow는 현재 고정 순서로 실행됩니다. 수퍼비전 보고서 입력 schema에는 회기 이력,
합의 목표, 임상 목표, 상담전략, 이전 수퍼비전 피드백이 있으나 frontend는 아직 이 필드를
모두 입력받아 전달하지 않습니다.

## 4. Agentic capability boundary

현재 구현을 정확히 분류하면 다음과 같습니다.

| Capability | Status |
| --- | --- |
| LangGraph stateful workflow | 구현됨 |
| Case-memory and authoritative-KB retrieval | 구현됨 |
| Evidence mapping and output verification | 구현됨 |
| Verification-driven conditional revision loop | 구현됨 |
| Input-dependent retrieval source routing | 미구현 |
| Section-level evidence sufficiency routing | 미구현 |
| LLM function calling / `ToolNode` / autonomous tool selection | 미구현 |
| Retrieval reranker model | 미구현 |

따라서 현재 제품은 **LangGraph-orchestrated, retrieval-aware document workflow**로
설명하는 것이 정확합니다. Export와 transcription은 사용자가 명시적으로 호출하는 별도
API 서비스이며 LLM이 선택하는 tools가 아닙니다.

## 5. API and service boundaries

주요 API는 다음과 같습니다.

```text
GET  /api/health
POST /api/notes/generate
POST /api/notes/confirm
POST /api/notes/recompose
POST /api/notes/supervision-report
POST /api/notes/drafts
GET  /api/notes/drafts
GET  /api/notes/drafts/{draft_id}
POST /api/materials/documents/extract
GET  /api/audio/capabilities
POST /api/audio/transcribe
GET  /api/documents/capabilities
POST /api/documents/export
```

- 문서 추출은 PDF 텍스트 레이어, DOCX, TXT를 지원합니다.
- 음성 전사는 별도 WhisperX service이며 기본 비활성화입니다.
- DOCX export는 기본 지원하고 PDF는 서버 capability가 충족될 때 지원합니다.
- HWPX는 capability contract만 있으며 검증된 template exporter는 아직 없습니다.

## 6. Authentication and storage boundary

`ENABLE_REAL_USER_AUTH=1`에서는 Supabase access token을 검증하고 authenticated user id를
storage actor로 사용합니다. `supabase/migrations/20260823000100_user_owned_counseling_data.sql`
은 상담 데이터에 `user_id`와 RLS policy를 추가합니다. Preview token은 명시적으로 활성화한
legacy demo 경로입니다.

인증과 RLS가 구현되어 있어도 실제 상담자료 운영에 필요한 감사 로그, 보관·삭제 정책,
동의 절차, 운영 보안 검토까지 완료된 상태는 아닙니다. 자세한 경계는
`docs/security_checklist.md`를 따릅니다.

## 7. Candidate adaptive retrieval experiment

향후 검증 후보는 문서 유형과 section 요구사항에 따라 `skip / case_memory / both`를 고르는
retrieval router와 field-level evidence sufficiency check입니다. 이 기능은 현재 구현에 포함되지
않습니다. 구현 전에 route별 정답과 필수 근거 slot을 상담사·수퍼바이저와 정의하고 다음을
측정해야 합니다.

- route accuracy와 activation rate
- retrieval latency와 token 사용량
- 근거 coverage와 unsupported claim 비율
- 추가 입력 요청의 적절성

이론 문서를 추가할 경우 문서 양식·윤리 KB와 분리하고, 이론 설명은 사례 근거로 집계하지
않습니다.
