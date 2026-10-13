# 보안 구현 진행 기록

기준: 2026-10-13 KST, v3 보안 지시서. 사용자 요청에 따라 이 진행 기록은 한국어로 작성한다.

## 완료 기준과 작업 경계

- 현재 코드의 API·데이터·권한·보존 흐름을 근거와 함께 기록한다.
- 합성 A/B 계정으로 타인 기록 읽기·수정·검색·내보내기 경계를 검증한다. 없는 삭제 API와 실제 DB에서만 검증 가능한 항목은 별도 표시한다.
- 로그·오류·캐시·임시 파일을 점검하고 독립적인 저위험 수정만 작은 Draft PR로 제출한다.
- 법률/윤리 요구사항, 문서 독자별 공개 범위, 서영님 PR 통합 점검표를 작성한다.
- 각 PR에 변경 파일, SHA, 테스트 명령·결과, 충돌 여부, 되돌리기와 승인 대기를 기록한다.
- main 병합, 운영 배포, 원격 DB/RLS 수정, 보존 정책 변경, 실제 상담 데이터 조회는 사전 승인 대상이다.

## 시작 상태

| 항목 | 확인 결과 |
| --- | --- |
| 기준 main SHA | `afd0476bd82dd7809b96fcd64a044325db06e565` |
| 작업 브랜치 | `codex/security-access-audit-20261013` |
| 최초 작업 트리 | 변경 없음 |
| GitHub 공개 범위 | public; 비공개 문서 원문과 민감한 취약점 상세는 저장소에 게시하지 않음 |
| 진행 중 PR | 시작 시 열린 PR 없음. 서영님 미게시 변경 파일과 충돌 여부는 unknown |
| 읽은 근거 | 10/12 담당/회의 문서, 9/19 법률·윤리 조사 문서, 9/30 사업계획서 HWP |
| 독립 검토 | 코드 기준 감사, 구조 검토, 법률/공개범위 문서 작업 분담 |

## 소유권과 충돌 방지

서영님 담당: Guest Quick Summary, 로그인 인계·자동저장, 비식별화, 원본 보존/삭제 UI, 내담자 입력 필드. 수연님 담당: Quick Summary/랜딩과 화면 디자인. 해당 기능의 구현은 이 브랜치에서 중복 작성하지 않는다. Codex는 새 보안 테스트와 문서, 독립적인 플랫폼 보안 수정을 담당한다. 미게시 변경은 확인할 수 없으므로 각 PR의 실제 경로 대조는 통합 직전에 다시 수행한다.

## 검증 기록

| SHA/대상 | 환경·배포 | 정확한 검사 | 결과·시각 | 합성 데이터 정리 |
| --- | --- | --- | --- | --- |
| 기준 SHA | 로컬, 배포 없음 | `git fetch origin`, `git status --porcelain`, `git worktree list` | 완료, 2026-10-13 KST | 데이터 생성 없음 |
| 기준 SHA | 로컬, 배포 없음 | 보안 스캐너 capability preflight `security_scan` | ready, 차단 없음. 작업자 3개 범위에서 분담 | 데이터 생성 없음 |
| `fb888c6769ab636d73dcc84caae48a9e0a21843d` | 로컬, 배포 없음 | `python -m unittest test_security_embedding_privacy -q` (`backend`에서) | 10개 통과, 2026-10-13 20:15 KST. 수정 전 동일 검사: 실패 2, 오류 1 | 전송 모의 처리, 캐시 정리 완료 |
| `fb888c6769ab636d73dcc84caae48a9e0a21843d` | 로컬, 배포 없음 | `python -m unittest test_raw_window_pipeline test_transcript_storage -q` | 25개 통과, 2026-10-13 20:16 KST | 원격 계정/행 생성 없음 |

## PR 1 — 임베딩 오류의 민감 정보 제거

- Draft PR: [#37](https://github.com/jordy9090/remind-counseling-note-agent/pull/37), 브랜치 `codex/security-access-audit-20261013`, 제출 HEAD `63c958775a1dc4a5f14e4da4bcbe5df2810ff6b5`.
- Codex 수정 완료: `backend/app/services/embeddings.py`의 HTTP/네트워크/시간초과 오류에서 외부 응답 본문과 이유 문자열을 제거하고 상태 코드만 유지한다. HTTP 오류 스트림을 닫고 일반 traceback에 외부 예외 내용을 연결하지 않는다.
- 신규 검증: `backend/test_security_embedding_privacy.py`. 성공 응답, 실패 처리, 캐시 내용·복사·만료·크기 제한·비활성화도 검증했다.
- 독립 코드 검토 완료. 새 테스트 10개와 관련 회귀 25개 통과. main은 PR 준비 시 다시 fetch했고 기준 SHA에서 변경 없음.
- 서영님과 동일 파일 변경: unknown(검토 가능한 PR 없음). 지시서의 담당 기능과는 분리된 임베딩 전송 경계만 수정했다.
- 병합 의존성: 없음. 운영 반영: 승인 대기. 되돌리기: 코드 커밋 `fb888c6769ab636d73dcc84caae48a9e0a21843d`를 revert. 보존 기본값·모델·DB 정책 변경 없음.
- 남은 위험: 다른 서비스의 오류 처리, 실제 운영 로그 설정, 외부 공급자의 보존 설정은 이 수정으로 검증되지 않는다.

## PR 2 — 캐시 임시 파일 격리와 실패 정리

- Draft PR: [#38](https://github.com/jordy9090/remind-counseling-note-agent/pull/38), 제출 HEAD `b94fd399d48d830e7fae2aad389569415c589aa8`.
- 브랜치 `codex/security-cache-temp-20261013`; PR #37 위에 순차 제출한다. 코드 SHA: `fbef1d8d117ecf4d9115cd890babee28ff85937f`.
- 변경: `backend/app/services/recompose_cache.py`, `backend/test_security_temporary_files.py`, 이 진행 기록.
- 수정 전: 동일 키 요청들이 같은 임시 파일을 사용했고 교체 실패 시 상담 결과를 담은 임시 파일이 남았다. 수정 후: 요청별 고유 임시 파일을 닫은 뒤 교체하고 일반 성공/예외 경로에서 정리한다. Windows에서 확인한 동시 교체 오류는 프로세스 내 잠금으로 방지했다.
- 합성 검증: `security-runtime/Scripts/python.exe -m unittest test_security_temporary_files -q` — 10개 통과(2026-10-13 KST). 별도로 `test_summary_generation_routes` 4개 통과. 성공/실패/동시 쓰기, A/B 키 분리, 업로드 크기·서명·중단 정리를 확인했다. 초기 검사에서 결함 2개를 재현했으며, 테스트 fixture 누락 1개는 검사 환경 문제로 수정했다.
- 로컬 검사 환경: 기본 Python의 FastAPI/Starlette 조합으로 앱 import가 실패해 저장소 밖 `security-runtime`에 uv.lock의 FastAPI 0.136.1, Starlette 1.0.0, python-docx 1.2.0을 설치했다. 의존성 파일·전역 패키지·운영 환경 변경 없음.
- 독립 검토 완료. 일반 임시 디렉터리는 테스트 종료 시 정리됐고 원격 데이터·유료 추론을 사용하지 않았다.
- 서영님 동일 파일 수정 여부: unknown. 기능 구현 경로는 수정하지 않았다. 병합 의존성: #37. 되돌리기: 코드 SHA를 revert.
- 한계: 강제 프로세스 종료, 파일 시스템 정리 실패, 여러 프로세스의 동시 교체는 보장하지 않는다. 최종 JSON 캐시의 보존 기간과 평문 내용은 기존 동작 그대로이며 보존 정책 결정이 필요하다. 병합·운영 반영은 승인 대기.

## PR 3 — 합성 A/B 접근 제어 검사

- Draft PR: [#39](https://github.com/jordy9090/remind-counseling-note-agent/pull/39), 제출 HEAD `7755259e2e3a302f96d05e7536da730d1ad221ac`.

- A/B 권한 회귀 완료: `backend/test_security_access_boundaries.py`, 코드 SHA `0f7d879beb8cd45d1029bfa91965504c4cbaa77b`. `security-runtime/Scripts/python.exe -m unittest test_security_access_boundaries -v` — 22개 통과, 3.859초, exit 0(2026-10-13 KST, backend 실행).
- 55개 경로·메서드 × 토큰 없음/잘못된 토큰/익명 계정의 165개 거부 검사, 실제 REST 클라이언트의 JWT·공개키 전달, 사례/기록/초안/검색/전사/캐시 A/B 격리, DOCX 실제 ZIP/XML 결과를 검사했다. 테스트 종료 시 임시 파일·모의 데이터 정리, 원격 계정/행 생성 없음.
- 위 검사는 DB 응답에 소유자 격리를 가정한 모의 전송을 사용한다. 실제 PostgreSQL 정책·FK·RPC·버킷 검증은 아니며 DELETE는 현재 경로의 405만 확인한다. 내보내기는 호출자가 준 본문을 렌더링하며 다른 사용자의 저장 기록을 조회하지 않는 현재 계약을 검사한다.
- 브랜치 `codex/security-access-tests-20261013`; 파일은 신규 테스트와 이 기록뿐. 서영님 동일 파일 수정 여부 unknown, 병합 의존성 #38(순차 검증 기준), 되돌리기 위 테스트 커밋 revert. 제품 코드 변경 없음.

## PR 4 — 근거 문서와 보안 회귀 CI

- Draft PR: [#40](https://github.com/jordy9090/remind-counseling-note-agent/pull/40), 제출 HEAD `782cdb3cc073223f5489e58bb72cfac9cf7baadb`.
- 브랜치 `codex/security-evidence-20261013`, 구현·문서 SHA `f5840c6129d26abcf4d2ae88011fff2cabad0c8d`.
- 요구한 문서 5종 작성: 데이터/권한/보존·운영자/공급자 목록, 법률/윤리 요구사항, 문서 독자별 공개 범위, 서영님 통합 점검표, 이 진행 기록. 법령 시행일·공식 윤리 규정·바우처 지침의 적용 범위를 원문 근거와 미결정 항목으로 구분했다.
- `backend/test_security_retrieval_logs.py`: `security-runtime/Scripts/python.exe -m unittest test_security_retrieval_logs -v` — 3개 통과, 0.044초(2026-10-13 KST). 검색 원문 대신 해시·길이·허용 메타데이터만 삽입하며 로그 실패 시 원문을 출력하지 않는 경로를 검증했다. 식별자/source_ref 자체의 비식별화는 별도 문제다.
- `.github/workflows/security-regressions.yml`: PR의 backend/api 변경 시 새 보안 검사 45개를 실행하도록 구성했다. 기존 CI는 main 대상 PR에만 적용되므로 이 워크플로는 순차 PR에서도 실행된다. Ubuntu/Python 3.11의 [실행 38392250602](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38392250602)가 성공했고 의존성 설치·45개 검사 단계 모두 성공했다.
- 독립 코드/문서 검토에서 차단 사항 없음. 비공개 원문·실데이터·공격 재현 상세를 공개 저장소에 게시하지 않았다. 공개 저장소 여부를 각 PR 제출 전에 재확인했다.
- 서영님 동일 파일 수정 여부 unknown. 병합 의존성 #39. 되돌리기: `f5840c6`와 후속 문서 커밋을 revert. 제품 코드·원격 데이터·보존 기본값 변경 없음.

## 현재 완료·한계·승인 대기

- Codex 수정: 임베딩 오류의 본문/이유 노출 제거, 캐시 쓰기 임시 파일 격리·정리.
- PR #40까지의 Codex 로컬 검증: 새 보안 검사 45개 + 관련 회귀 29개 = 74개 통과. 165개 게스트 하위 검사는 22개 A/B 검사에 포함되며 별도 테스트 수로 중복 합산하지 않았다.
- 운영 메타데이터: 2026-10-13 20:35:45 KST Vercel 운영 배포 `dpl_4GASoXeGR66hBL6FkAvz9s6Fa7Vv`, READY, main `afd0476bd82dd7809b96fcd64a044325db06e565`, region `iad1`. 운영 반영 없음. Re:mind와 연결되는 Supabase 프로젝트/지역은 명확히 식별되지 않았다.
- CI: PR #37 Product CI 실행 38389311116 성공. #40 신규 보안 CI 성공. #37–#40의 Vercel preview 상태 성공. Preview 자동 빌드는 운영 승격과 구분한다.
- 민감한 DB 관계 소유권 검토와 ROLLBACK으로 끝나는 제한적 정책 제안은 공개 Git 밖 보안 스캔 산출물에 보관했다. psql/Docker/Supabase 로컬 실행 도구가 없어 실제 DB 재현·정책 적용 검증은 수행하지 못했다. 원격 RLS 수정은 승인 대상이다.
- 제품/법률 결정 필요: 원본·초안·캐시·파생물·백업 보존/삭제 기준, 문서 수신자별 허용 필드, 공급자 계약·국외 처리·운영자 접근. 종단간 암호화·운영자 열람 불가·법률 준수를 주장할 근거는 없다.
- 추가 소스 확인 완료. 마스킹 담당 구현과 겹치는 경계의 비공개 합성 검증 2건도 통과했으며, 상세 실패 재현은 보안 스캔 산출물로만 보관했다. 공개 체크리스트에 검증 범위를 추가하고 직접 기능 수정은 하지 않았다.
- 서영님 통합 검증: 검토 가능한 PR/브랜치가 아직 식별되지 않아 대기. 최종 체크리스트에 계정 직접 전환·늦게 도착한 응답·확정 기록 재사용 검사를 포함했다.
- 운영 DB의 실제 RLS, 환경 변수 값, 공급자 계약·보존 설정 및 Vercel 메타데이터 외의 처리 지역은 확인하지 않음.
- 테스트 통과는 운영 배포 완료나 법률 준수 인증을 의미하지 않음.

## PR 5 — 비동기 업로드 취소 시 원본 임시 파일 정리

- Draft PR: [#41](https://github.com/jordy9090/remind-counseling-note-agent/pull/41), 검사 HEAD `8df86703e2ebc101541a04fab22f4d025b35c06e`. 이후 문서만 갱신하며 통과 결과를 재사용한다.
- 브랜치 `codex/security-upload-cleanup-20261013`, 코드 SHA `4449cf57416be9b3b044084e008cc10f1d955da5`.
- 파일: `backend/app/services/upload_validation.py`, 신규 `backend/test_security_upload_cancellation.py`, 보안 CI 목록, 진행 기록과 통합 점검표. 읽기/닫기 중 취소 및 닫기 실패에서 애플리케이션 임시 파일을 정리하고 예외를 그대로 전달한다. 성공 시에는 기존처럼 호출자에게 파일 소유권을 넘긴다.
- 실행 환경: 기존 `backend/.venv/Scripts/python.exe`, Python 3.11.15 / FastAPI 0.136.1 / Starlette 1.0.0. `-m unittest test_security_upload_cancellation -v`: 수정 전 8개 중 실패 6개·성공 2개, 수정 후 8개 모두 통과(0.749초).
- 관련 회귀: `-m unittest test_security_temporary_files.UploadCleanupTests -v` 4개 통과(0.149초); `-m unittest test_vercel_wrappers.TestVercelWrappers.test_material_extract_endpoint_requires_token_and_extracts_txt test_vercel_wrappers.TestVercelWrappers.test_material_extract_uses_supabase_bearer_identity -v` 2개 통과(0.104초). 모든 검사 2026-10-13 KST, 합성 파일 정리 완료.
- 새 검사 8개를 CI에 추가하여 보안 검사 총 53개. 관련 기존 회귀는 중복 실행을 제외하고 총 31개이며, 비공개 경계 검증 2건은 이 합계와 별도다.
- 독립 최종 소스 검토에서 차단 사항 없음. 서영님 동일 파일 수정 여부 unknown; 기능 구현은 수정하지 않았다. 병합 의존성 #40. 되돌리기: 코드 SHA revert.
- 한계: 파일 삭제 자체의 실패, 강제 프로세스 종료, 프레임워크 내부 spooling/스냅샷은 검증 범위 밖이다. 보존 기간·기본값·원격 정책·운영 배포 변경 없음.

## 최종 상태 — 2026-10-13 KST

- Draft PR 순서: #37 → #38 → #39 → #40 → #41. 각 PR은 바로 앞 브랜치를 기준으로 한다(#37만 main). main 병합/운영 승격은 하지 않았다.
- #41 [보안 CI 실행 38394552253](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38394552253) 성공: Ubuntu/Python 3.11에서 보안 검사 53개 통과. #41 Vercel Preview도 성공했다. 로컬의 관련 기존 회귀 31개 및 별도 비공개 합성 검증 2건도 통과했다.
- 보안 스캔 `c7b010d5-d92c-4e2b-9fb5-37d8a8bb0e9a` 보고서 생성/검증 완료. 기준 revision은 최초 main `afd0476`이며 작업 브랜치 수정/미배포 상태를 구분했다. 확정 중위험 3건 중 1건은 PR #37에서 수정, 2건은 정책/기능 담당 통합 단계로 남겼다. 캐시/업로드 수명주기 보강은 별도 수정 증거로 기록했다.
- 감사 범위는 부분 검증으로 명시했다. 실제 DB 정책·공급자 로그·의존성/native decoder 전체·직접 계정 교체 재현까지 검증했다는 주장은 하지 않는다. 비공개 재현 자료와 정책 제안은 Git 밖 스캔 산출물로 보관한다.
- 다음 실행 조건: 서영님 검토 가능한 PR의 정확한 SHA/파일을 대조하고 체크리스트 실행; 승인된 격리 DB에서 실제 정책 검사; 제품/법률 담당의 보존·수신자·공급자 결정. main 병합, 운영 배포, 원격 DB/RLS 및 보존 정책 변경 전 사용자 승인이 필요하다.
- 이번 세션의 독립 구현·검사·문서·PR 제출 작업은 완료했다. 남은 항목은 위 의존성/승인과 보고서의 미검증 범위이며, 세션 밖에서 작업 중이라고 표시하지 않는다.

## 후속 실행 — 기존 PR 이후 독립 보안 작업

- 사용자의 추가 지시에 따라 #37–#41을 중간 단계로 유지하고 실행을 재개했다. 이번 완료 기준: 확정 기록 재사용 경계의 합성 재현과 좁은 수정, 격리 DB의 실제 소유권/RLS 검사와 안전한 제안, 남은 접근·오류 로그·파일·내보내기 경계의 독립 결함 수정 및 회귀 검증.
- 기준 HEAD `9e3c2d4a970c949941da9ee3459df7c947d43f28`, main `afd0476bd82dd7809b96fcd64a044325db06e565`. 기존 스택은 변경하지 않는다. 조회한 공개 PR은 #37–#41뿐이며 서영님 미공개 작업 파일은 여전히 unknown이다.
- 별도 `codex/security-retrieval-privacy-20261013` 브랜치에서 기존 `deidentify_text`를 조회 서비스에 재사용한다. 새로운 식별 규칙·저장 원본·자동저장 UI를 구현하지 않는다. 중첩 JSON 키 충돌은 값이 소실되지 않게 구분한다.
- 2026-10-13 KST: 새 조회 마스킹 검사 7개, 수정 전 실패 7개 하위 사례(6개 테스트), 정상 제어 1개 통과; 수정 후 7개 모두 통과(0.042초). 최근 기록/빈 dense fallback의 구조화·요약 실제 invoke, legacy dense의 grounding invoke, 중첩 키/값/근거문, 원본 불변·인용·정상 문장·숫자·날짜 보존을 합성 데이터로 검증했다. 모델은 mock, 네트워크 차단, 실데이터·유료 호출 0.
- DB 작업은 원격 접근 없이 저장소 밖 PGlite 엔진으로 진행한다. 그 외 확정된 독립 후보는 저장소 오류 본문/traceback, 초안 자격 증명 fallback과 실패 staging 정리, 재구성 실패 응답의 본문 노출이다. 완료 후 다음 항목으로 이동한다.
- 조회 수정 관련 회귀: `test_source_refs test_grounded_generation test_security_access_boundaries` 46개 중 44개 통과. 기존 claim-support 2개는 API 키가 없으면 mock에 도달하지 않는 stub 설정 때문에 실패했다. 합성 키와 소켓 차단을 명시하여 그 2개만 재검사했고 모두 통과(0.003초); 원인·수정은 테스트 환경이며 제품 코드 변경은 없다.
- 독립 최종 검토: 차단 사항 없음. 검토자가 기존 식별 패턴 8종과 정상 dense 결과의 구조화·요약 호출도 별도 합성 검사했다. 보장 범위는 기존 탐지 패턴이며 모든 개인정보 제거를 뜻하지 않는다. raw transcript/KB 및 비정상 provenance 필드는 이번 패치 범위 밖이다. 인용/저장 원본 보존, RAG 비활성 정상 제어 확인. 보안 CI에 새 검사 7개를 추가했다.
- 조회 수정 되돌리기: 이 범위의 코드 커밋 revert. DB·보존 정책 변경 없음. 다음 작업은 이미 합성 재현한 저장소 오류 경계다.

## PR 6 — 저장된 기록 재사용 마스킹

- Draft PR [#42](https://github.com/jordy9090/remind-counseling-note-agent/pull/42), 코드/HEAD `bc17da0a6c75bd0e7f0742826a8f397d859b66ab`, 기준 #41. 위 조회 검사와 독립 검토 완료. 원본을 바꾸지 않고 기존 마스킹 함수를 재사용하며 서영님 새 기능을 구현하지 않는다.

## PR 7 준비 — 저장소 오류 진단의 원문 노출 제거

- 브랜치 `codex/security-storage-diagnostics-20261013`, 기준 #42. 두 Supabase REST 어댑터에서 HTTP 상태와 고정 허용 목록의 구조화 코드만 보존한다. 본문·reason·기본 traceback 연결을 노출하지 않으며 오류 스트림을 닫는다. 프로필 컬럼 fallback은 `42703`/`PGRST204`로 유지한다.
- 초기 합성 검사 12개는 수정 전 실패 하위 사례 41개/오류 4개, 정상 제어 2개 통과; 수정 후 12개 통과. 독립 검토가 실제 `HTTPResponse.begin()`의 잘못된 상태 줄이 빠져나오는 문제를 찾아, 응답 읽기/디코딩 실패까지 3개 추가 검사로 재현했다(수정 전 어댑터 하위 사례 오류 6개).
- 최종 `backend/.venv/Scripts/python.exe -m unittest test_security_storage_diagnostics`: 15개 모두 통과. `test_case_list test_case_dashboard test_transcript_storage test_security_access_boundaries`: 60개 통과(후속 오류 유형 수정이 정상 경로를 바꾸지 않아 재실행하지 않음). 구문/diff 검사 통과. 2026-10-13 KST, 합성 응답만 사용, 외부 호출/정리할 원격 데이터 없음.
- 파일: `supabase_errors.py`, 두 REST 어댑터의 예외 처리와 오류 클래스, 신규 진단 검사, 기존 case-list 오류 fixture 1개, 보안 CI와 진행 기록. 인증 자격 증명 선택은 이 PR에서 변경하지 않는다.
- 정상 payload 자체나 telemetry가 억제된 예외 context/locals를 의도적으로 수집하는 경우까지 보장하지 않는다. 운영 로그 설정 검증은 별도다. 다음은 초안 저장의 자격 증명·staging 경계 수정이다.

- 제출 완료: Draft PR [#43](https://github.com/jordy9090/remind-counseling-note-agent/pull/43), 코드/HEAD `98c0b1b0f89d83a5ab1cf4d56be35b45b2f2930a`. [보안 CI 38399040115](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38399040115) 성공(75개). #42 [CI 38398439297](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38398439297)도 성공(60개).

## PR 8 준비 — 초안 인증·임시 파일 경계

- 브랜치 `codex/security-draft-boundaries-20261013`, 기준 #43. 인증 JWT가 있는 요청은 public key/URL 누락 시 명시적으로 실패하며 서비스 권한이나 로컬 디스크로 대체하지 않는다. 명시적 legacy/local 경로는 유지한다. 로컬 초안 쓰기는 요청별 staging과 `finally` 정리를 사용하며 Windows 교체 충돌을 프로세스 내에서 직렬화한다.
- 합성 재현에서 직접 서비스 bearer 선택, 실패·중단 후 staging 잔존, 동시 쓰기 충돌을 확인했다. 초기 8개 검사 중 정상 fixture의 잘못된 `counselorMemo` 키도 발견해 기존 allowlist의 `counselor_memo`로 바로잡았다; 이는 제품 결함 수에 포함하지 않는다.
- 최종 검사: 신규 `test_security_draft_boundaries` 9개 + 기존 A/B draft save/detail/local path/JWT 검사 5개 = 14개 통과(0.676초, 2026-10-13 KST). 구문 검사 통과. 독립 검토에서 부분 쓰기/닫기 실패 정리와 실제 Request의 JWT/public-key/owner 보존을 추가 확인했고 차단 사항 없음. 합성 임시 디렉터리 정리 완료, 원격/유료 호출 0.
- 파일: `draft_store.py` 파일 쓰기 helper, `supabase_store.py` 자격 증명 선택, 신규 검사, CI와 진행 기록. 자동저장 UI·초안 projection·보존 기간은 변경하지 않았다. 서영님 동일 파일 수정 여부는 unknown이므로 통합 시 이 helper 변경을 대조한다.
- 한계: 프로세스 강제 종료·OS unlink 실패·여러 프로세스 간 잠금은 보장 범위 밖. 최종 초안의 보존 정책은 승인 대기. 다음 작업은 합성 SDK/검증 오류가 재구성 응답·로그에 노출되는 경계다.

- 제출 완료: Draft PR [#44](https://github.com/jordy9090/remind-counseling-note-agent/pull/44), 코드/HEAD `deddab79d07bfc519f270e78f4b0968c81c41b4e`, 기준 #43.

## PR 9 준비 — 재구성 실패 응답·로그

- 브랜치 `codex/security-recompose-diagnostics-20261013`, 기준 #44. Main/Vercel 두 recompose handler의 일반 오류 응답을 고정 한국어 문구로 바꾸고 예외 연결을 억제한다. Main의 원문 traceback 출력을 제거한다. SDK 오류와 모델 출력 ValidationError가 실제 pipeline/cache를 거쳐 도달하는 경계만 수정했다.
- 수정 전 새 검사 6개 중 개인정보 보호 검사 3개가 6개 호스트 하위 사례에서 실패했고 정상 제어 3개는 통과. 수정 후 `test_security_route_diagnostics test_summary_generation_routes test_security_temporary_files.RecomposeFileSafetyTests` 16개 통과. 실제 HTTP·pipeline·cache, 실패 캐시 없음, 성공 재사용, 품질 오류 502, 미인증 401을 확인했다. 구문 검사 통과. 2026-10-13 KST; 외부 모델/네트워크 차단, 합성 임시 디렉터리 정리 완료.
- 독립 최종 검토에서 차단 사항 없음. 파일은 두 handler와 신규 검사·CI·진행 기록이다. confirmation/supervision sibling도 확인했지만 같은 민감 오류가 도달하는 추가 경로는 입증되지 않아 기능 구현을 확장하지 않았다. 운영 telemetry의 별도 예외 수집 설정은 미검증이다.
- 다음 단계: DB 제안 결합 검증, 최종 변경 범위 보안 검사, CI 상태와 남은 승인/의존성 체크포인트 정리. 원격 DB·RLS·보존·운영 변경 없음.

- 제출 완료: Draft PR [#45](https://github.com/jordy9090/remind-counseling-note-agent/pull/45), 코드/검사 HEAD `3c6775fe12ca3e9a6403c7cf7d546561fce7a53b`, 기준 #44. [보안 CI 38399854462](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38399854462) 성공: Ubuntu/Python 3.11, 잠긴 의존성 설치와 보안 검사 90개 단계 통과. #44 [CI 38399743429](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38399743429)도 성공(84개). 추가 코드는 37개 새 검사이며 기존 53개와 중복 합산하지 않았다.

## 독립 로컬 DB 재현·제안 검증 완료

- 기존 psql/Docker 미설치 제약을 저장소 밖의 고정 버전 PGlite 0.5.9/실제 PostgreSQL 18.6 WASM으로 해소했다. 저장소 migration 10개를 수정 없이 적용하고 실제 nosuperuser/nobypassrls authenticated 역할로 검사했다. `auth.uid()/auth.role()`만 합성 claims 호환 함수이며 인증/JWT 검증 자체는 모의 환경이다.
- 세 개별 실행 35/30/10 검사 그룹 통과(반복 환경 2개를 제외한 고유 그룹 71개). 이어 별도 독립 검토자가 세 제안을 결합한 41개 시나리오 그룹을 통과시켰다. 별도/결합 검사의 중복 시나리오는 합산하지 않는다. 최초 결합 harness의 제어 흐름 오류는 수정 후 성공했고 실패 출력도 비공개 증거에 보존했다.
- 제안 범위: 부모 관계 소유권, 관계 일관성, 저장 참조 무결성. 정상 CRUD/upsert, optional NULL, cascade, source 삭제, 기존 데이터 보존과 rollback을 검증했다. 공개 저장소의 자동 migration 폴더에는 넣지 않았다. 재현 스크립트·결과·정확한 SQL·읽기 전용 preflight·독립 검토는 Git 밖 보안 artifact에 보관했다.
- 정책만 추가해도 기존 잘못된 관계·점유 키가 자동 복구되지는 않는다. privileged/legacy 쓰기, NOT VALID의 기존 행 동작, 인덱스 잠금과 버전 호환성을 별도 승인 조건으로 정리했다. 원격 DB/RLS/기존 행/보존 변경은 0회. 모든 메모리 DB를 종료했다.
- 남은 DB 단계: 실제 배포 프로젝트와 PostgreSQL 버전/catalog를 식별한 뒤 동일 버전의 격리 native 환경에서 통합 검사. 원격 inspection 범위, 기존 불일치 행 처리, 최종 SQL·인덱스/잠금·유지보수 시간·rollback 승인 전에는 적용하지 않는다.

## 남은 경계·재개 조건

| 항목 | 현재 근거와 남은 의존성 | 다음 실행/정확한 승인 |
| --- | --- | --- |
| 서영님 통합 | 검토 가능한 feature PR/SHA 미확인. 직접 A→B 세션 교체 시 workspace 유지 위험은 source/hook harness로 확인했으나 실제 SDK/DOM 흐름은 미재현. 일반 로그아웃은 unmount된다는 반대 근거 있음. | 정확한 PR/SHA와 변경 파일을 받으면 기존 체크리스트로 handoff/autosave/마스킹/저장·삭제 동작을 검증. 로그인 workspace 구현을 중복 수정하지 않음. |
| DB 정책 반영 | 로컬 실제 엔진 재현과 개별/결합 제안 완료; 배포 버전/catalog/PostgREST/JWT/동시 연결은 미검증. | 프로젝트 식별·합의된 읽기 전용 inspection 범위·배포와 같은 격리 환경 필요. 원격 쓰기 전 최종 정책/제약 SQL, 기존 행 처리, 잠금 계획과 rollback의 명시적 승인. |
| 보존·삭제·문서 독자 | 원본/초안/재구성/파생 자료·백업의 별도 수명과 현재 export가 caller body를 렌더링한다는 계약 확인. HTTP no-store 부재는 기록했으나 공유 캐시 노출은 입증되지 않음. | 담당 제품/법률/윤리 책임자가 artifact별 보존·삭제·수신자 필드를 정해야 함. 기간·기본값·과거 행 삭제는 승인 전 변경하지 않음. |
| 운영자·공급자 | 서비스 권한/운영자 plaintext 접근 가능성, provider/host 보존·지역·telemetry 설정 미확인. | 계약/운영 설정 근거와 지정된 관리자 검증 필요. 운영자 열람 불가·종단간 암호화·법률 준수 주장을 하지 않음. |
| 배포·병합 | #37→#38→#39→#40→#41→#42→#43→#44→#45 모두 Draft. main `afd0476` 유지. | 사용자 main 병합/운영 배포 승인 필요. 유료 모델/STT 검사는 비용 승인 전 계속 stub 사용. |

- 다음 담당자가 바로 확인할 코드: 브랜치 `codex/security-recompose-diagnostics-20261013`, 검사 revision `3c6775fe12ca3e9a6403c7cf7d546561fce7a53b`. 후속 문서만 바뀌면 위 통과 결과를 재사용한다. 되돌리기는 각 PR 코드 커밋을 역순 revert하며 배포/DB rollback은 별도 승인한다.
- 이 체크포인트는 보안 프로젝트 전체 완료 선언이 아니다. 독립 수정·로컬 검증을 마친 후, 남은 구현은 위 기능 담당·환경·제품/법률 결정·승인 경계를 따른다.

## 최종 변경 검사에서 발견한 회귀와 후속 수정

- 고정 범위 `9e3c2d4..3c6775f`의 diff 보안 검사 `2d3bd648-84e9-432c-800b-2e98d8792f71` 완료. source/config/test 13개와 관련 호출을 검토했다. preflight 3개 통과. 원래 repository 위협 모델을 그대로 재사용했으며 기존 운영/DB/제품 미결정을 해결했다고 주장하지 않는다.
- 검사에서 #42에 추가된 마스킹 키 충돌 처리의 과도한 반복을 발견했다. 같은 결과로 마스킹되는 키마다 번호 검색이 처음부터 반복되어 입력 크기에 비해 처리량이 급증했다. 합성 직접 helper 검사와 실제 helper의 작업량 회귀 검사로 재현했다. 검사 보고서는 원래 `3c6775f`에서 발견된 중위험 1건을 보존하며, 후속 수정 증거를 따로 연결한다.
- 별도 `codex/security-mask-collision-work-20261013` 브랜치에서 마스킹 결과별 다음 번호를 기억하도록 좁게 수정했다. 탐지 규칙·저장 원본·사용자 인용 식별자는 그대로다. 기존 literal suffix 키·중첩 충돌·모든 값 보존·재적용 안정성과 입력당 작업량 한도를 검사한다.
- 수정 전 작업량 검사 1개 실패(0.116초); 수정 후 `test_security_retrieval_privacy` 9개 모두 통과(0.058초), 구문 검사 통과. 시간 의존적인 CI 한도를 사용하지 않는다. 별도 합성 측정의 키 1k/2k/4k/8k 처리는 수정 전 0.220/0.752/3.363/12.546초, 수정 후 0.014/0.027/0.053/0.107초였다. 환경별 수치는 성능 SLA가 아니다.
- #42–#45 코드 검사에서 발견된 이 회귀는 후속 커밋까지 포함해 배포해야 한다. 원래 #37–#41 스택과 main은 그대로 유지한다. 검사 도구 집계 사용량은 총 6,089,467 tokens(캐시 입력 5,905,408 포함, 4개 thread); 공급자 모델 API를 호출한 비용과 구분한다.
- 후속 수정의 독립 최종 검토: 차단 사항 없음. 기존/수정 함수를 기존 detector와 비교한 6,040개 합성 동등성 사례 통과. literal placeholder·겹치는 suffix·빈 번호·중첩 값·재적용을 확인했다. 128/512/2,048개 입력의 충돌 그룹에서 membership 검사 횟수가 255/1,023/4,095로 증가해 값 보존과 선형 충돌 처리량을 확인했다. 기존 탐지·문자열 처리 비용은 이 복잡도 주장과 구분한다. 추가 범위만 검토했으며 전체 통과 검사를 중복 실행하지 않았다.

## PR 10 및 재개 체크포인트 — 2026-10-13 22:07 KST

- Draft PR [#46](https://github.com/jordy9090/remind-counseling-note-agent/pull/46) 제출·연결 완료. 브랜치 `codex/security-mask-collision-work-20261013`, 코드/검사 SHA `698c67a5b4ad8ca89ebcc464639af10d98279102`, 기준 #45. 이후 진행 기록만 갱신하며 코드 검사 결과를 재사용한다.
- [보안 CI 38402404554](https://github.com/jordy9090/remind-counseling-note-agent/actions/runs/38402404554) 성공. Job `115313098002`에서 Ubuntu/Python 3.11, 잠긴 의존성 설치와 보안 검사 **92개 모두 통과**(0.935초, 2026-10-13 13:07:08 UTC). #41의 53개에 후속 검사 39개를 추가한 수이며 이전 CI 횟수를 중복 합산하지 않는다.
- 기존 #37 → #38 → #39 → #40 → #41을 보존하고 #42 → #43 → #44 → #45 → #46을 순서대로 추가했다. 모두 Draft이며, #42 설명에도 후속 충돌 처리 수정 #46을 함께 반영해야 한다고 기록했다. main 기준 `afd0476bd82dd7809b96fcd64a044325db06e565`는 변경하지 않았다.

| 추가 완료 PR | 코드 SHA | 완료 범위 |
| --- | --- | --- |
| #42 | `bc17da0a6c75bd0e7f0742826a8f397d859b66ab` | 저장된 확정 기록·fallback·dense 재사용에서 기존 마스킹 함수 적용 |
| #43 | `98c0b1b0f89d83a5ab1cf4d56be35b45b2f2930a` | REST 저장소 오류 본문·reason·traceback 노출 제거 |
| #44 | `deddab79d07bfc519f270e78f4b0968c81c41b4e` | 인증된 초안 요청의 권한 fallback 차단, 실패 staging 정리 |
| #45 | `3c6775fe12ca3e9a6403c7cf7d546561fce7a53b` | 두 재구성 handler의 민감 오류 응답·로그 제거 |
| #46 | `698c67a5b4ad8ca89ebcc464639af10d98279102` | 마스킹 키 충돌 처리량 회귀 수정·동등성 보존 |

- DB 재현은 위 고유 71개 그룹과 별도 결합 41개 그룹 통과 결과를 유지한다. 비공개 보안 artifact 묶음 `artifacts-8307464bcdd6db59660b6439a697229b75139d012faa81ce8a31f77c38e0a1e0`의 `artifacts/local-rls-checkpoint.md`에 정확한 재현 명령, `artifacts/local-combined-security-review.md`에 세 제안의 후속 결합 검증, `hardening/`에 검토용 SQL과 읽기 전용 preflight가 있다. 결합 제안 SHA-256은 `f5f280a025a0d1ff1a0da8ae0225b8e920b54ae297cdadc56d4b115bebe1d933`. 앞선 개별 검토의 결합 미검증 한계는 이 후속 결합 검사 범위에서 해소했다.
- 최신 고정 diff 검사 보고서는 `3c6775f`의 중위험 1건을 그대로 보존한다. #46 수정은 `findings/masked-key-collision-fix.md`의 후속 증거·독립 검토·CI로 연결하며, 원래 보고서를 수정 완료나 무결함 보고서로 바꾸지 않는다.
- 다음 실행 가능한 작업은 서영님 PR의 정확한 SHA/파일을 확보하여 `seoyoung-integration-checklist.md`와 대조하는 통합 검증이다. DB 쪽은 배포 프로젝트/버전/catalog 식별 자료와 동일 버전 격리 환경이 준비되면 제안의 호환성·PostgREST/JWT·동시성 검증을 이어간다. 현재 구현을 다시 실행하거나 기능 담당 영역을 중복 수정할 이유는 없다.
- 필요한 명시적 승인: **(1)** main 병합과 운영 배포, **(2)** 원격 DB/RLS 변경의 최종 SQL·기존 불일치 행 처리·인덱스/잠금·유지보수 시간·validation/rollback 계획, **(3)** 제품/법률 결정에 따른 보존·삭제 기본값 및 과거 데이터 처리, **(4)** 유료 모델/STT 검사의 비용. 원격 읽기 검증도 식별된 프로젝트와 합의된 메타데이터/집계 범위에서만 수행한다.
- 남은 위험은 기존 잘못된 관계/점유 키, 실제 계정 직접 전환과 늦은 응답의 통합 동작, 탐지 규칙 밖 개인정보, 운영 telemetry/공급자·백업 설정이다. 현재 확인된 독립 수정과 로컬 검증은 끝났으며, 위 자료·환경·승인·제품/법률 결정이 있어야 다음 단계로 진행할 수 있다. 실데이터·원격 DB 쓰기·main 병합·운영 배포·보존 정책 변경·유료 API 호출은 하지 않았다. 합성 임시 파일과 메모리 DB는 정리했고 재현 런타임/증거만 보존했다.
