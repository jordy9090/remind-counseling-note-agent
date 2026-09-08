# 저장·확정·복원 흐름

기준: origin/main `4815b44`. 작업 브랜치: `codex/persistence-workflow`.

## Audit와 변경 범위

| 기능 | 기존 상태 | 연결 결과 |
| --- | --- | --- |
| 임시저장 POST `/api/notes/drafts` | client 함수 존재, 화면 미사용 | 입력·요약 편집·문서 작업 상태 저장, 응답 ID로 같은 작업 갱신 |
| 임시저장 GET `/api/notes/drafts`, `/drafts/{draft_id}` | API만 존재 | client 조회 함수와 현재 화면의 선택 복원 추가 |
| 생성 POST `/api/notes/generate` | `persist:false` | `persist:true`, `stored`와 `note_id` 확인 후에만 확정 가능 |
| 확정 POST `/api/notes/confirm` | client 함수 존재, 화면 미사용 | 최신 `draftSections`를 전송하여 `confirmed_json` 저장 |
| case dashboard | 기존 케이스 화면에서 사용 | 기존 문서 목록으로 동일 케이스의 AI 초안·확정본 선택 |
| note 상세 조회 | 없었음. Dashboard는 대표 필드 최대 300자만 제공 | 승인받은 GET `/api/notes/records/{note_id}` 추가 |

인증, AuthGate, anonymous/email 정책, ownership, RLS, migration은 변경하지 않는다.
새 상세 조회는 확정 API와 같은 note → session → case 검증 및 사용자 Bearer token을 사용하며,
`Cache-Control: private, no-store`로 전체 저장 JSON을 반환한다.
Vercel wrapper `/api/notes/record?note_id=...`와 rewrite도 포함한다.

## 사용 흐름

1. 회기 입력에서 케이스 ID와 합성 상담 자료를 입력하고 **임시저장**한다.
2. **저장된 기록 불러오기 → 저장 목록 조회**에서 임시저장을 선택한다. 케이스 ID를 비워도 현재 계정의 임시저장 목록을 조회할 수 있다.
3. **요약 초안 생성**은 AI draft만 저장한다. `confirmation_status=draft`, `confirmed_json={}`인 기존 저장 계약을 따른다.
4. 요약 내용을 편집하고 **상담사 확정**을 누른다. 현재 요약의 모든 항목(사용자 추가 항목, 빈 문장, 표시 여부 포함)을 저장한다. 숨긴 항목은 삭제하지 않는다.
5. 새로고침 후 **저장된 기록 불러오기**에서 같은 케이스 ID로 조회하고 **확정본**을 선택한다. 확정 JSON 전체를 다시 읽는다.

임시저장과 확정은 별도 작업이다. 임시저장 복원 시 서버 확정 상태를 조회하더라도 편집 문장을 확정본으로 덮어쓰지 않는다.
확정 후 편집하면 ‘미확정 수정사항’으로 표시한다. 복원으로 현재 작업을 교체하기 전 사용자에게 알린다.
중복 저장·확정 및 요청 중 화면 편집을 막아 전송 스냅샷과 표시 상태의 경합을 방지한다.

확정 JSON의 canonical summary 필드는 dashboard와 호환되고, `sections`는 기존 case-memory 계약과 호환된다.
추가 UI 항목·표시 순서는 같은 JSON 내 `workspace_sections`에 보존한다. DB 컬럼은 추가하지 않는다.
이번 확정 UI는 `create_case_memory:false`를 사용한다. 메모리 색인·임베딩 생성은 이번 범위에 포함하지 않는다.
요약 화면의 확정은 회기요약에 적용된다. 문서변환 후 별도로 편집한 최종문서는 임시저장·내보내기 대상이다.

## 실패 및 복원 한계

- 생성 HTTP 200도 `persistence_report.stored=false`일 수 있다. 초안은 유지하고 저장 실패를 표시하며 확정 버튼을 비활성화한다.
- 저장되지 않은 생성 결과를 재생성 없이 generated_notes에 넣는 기존 API는 없다. 이 경우 임시저장으로 편집을 보관할 수 있다.
- Bearer token이 없으면 persistence client가 전송 전에 실패한다. 서버 인증 가드는 그대로 유지된다.
- 파일 바이트와 blob URL은 저장하지 않는다. 추출 텍스트·축어록·편집 메타데이터는 임시저장에 보존하며 원본 파일은 다시 선택해야 한다.
- note 상세 조회는 원문 입력 전체를 반환하지 않는다. 원문 회기 입력은 임시저장에서 복원한다.
- 복원한 임시요약의 AI 근거는 재확인 대상으로 표시한다. 확정본은 AI 초안의 claim mapping을 수정 문장의 검증 근거로 제시하지 않는다.
- 기존 backend의 생성 다중 쓰기는 트랜잭션이 아니다. 중간 실패 시 부분 저장이 남을 수 있으며, 이번 변경은 해당 저장 계약을 바꾸지 않는다.

## 검증

합성 데이터만 사용한다. 실제 routes·generation stub·저장 helper를 실행하고 Supabase Auth/REST 경계만 메모리 대역으로 바꾸므로,
운영 Supabase 연결·실제 RLS·실제 LLM 호출 검증과는 구분한다.

백엔드(프로젝트 의존성이 설치된 Python 환경):

```powershell
Set-Location backend
python -m unittest test_persistence_workflow test_case_dashboard test_vercel_wrappers
```

프론트엔드:

```powershell
Set-Location frontend
npm install --package-lock=false
npm run build
npm run verify:counselor-edit
npm run verify:material-workflow
npm run verify:grounding-review
```

브라우저 재현용 로컬 서버(별도 터미널):

```powershell
Set-Location backend
python test_persistence_workflow.py --serve
```

```powershell
Set-Location frontend
$env:VITE_SUPABASE_URL='http://127.0.0.1:8017'
$env:VITE_SUPABASE_PUBLISHABLE_KEY='synthetic-public-key'
$env:VITE_API_BASE_URL='http://127.0.0.1:8017'
npm run dev -- --host 127.0.0.1 --port 4174 --strictPort
```

```powershell
Set-Location frontend
npm run verify:persistence-browser
```

브라우저 검증은 Node 22 및 Windows Edge를 사용하며, `EDGE_PATH`로 실행 파일을 지정할 수 있다.
임시저장→새로고침→조회, AI 생성→긴 문장 편집→확정→새로고침→전체 확정본 조회,
확정 이후 미확정 편집 복원, 중복 요청 방지, 저장/확정 실패 UI, token 없는 요청 차단을 확인한다.
375/767/768/1024/1440px에서 스크롤 폭과 저장 UI 경계를 검사하고 `frontend/screenshots/persistence/`에 캡처한다.

## 적용과 되돌리기

원격 반영·Production 배포는 수행하지 않았다. 적용할 때는 상세 조회 API와 Vercel rewrite를 frontend와 함께 제공한다.
backend 먼저 적용해도 기존 클라이언트와 호환된다. 되돌릴 때는 frontend 연결을 먼저 되돌린다.
기존 DB 구조와 저장 기록은 그대로 유지되며 데이터 삭제나 migration 롤백이 필요하지 않다.
