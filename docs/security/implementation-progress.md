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

## 진행 중 / 승인 대기

- A/B 권한 회귀 완료: `backend/test_security_access_boundaries.py`, 코드 SHA `0f7d879beb8cd45d1029bfa91965504c4cbaa77b`. `security-runtime/Scripts/python.exe -m unittest test_security_access_boundaries -v` — 22개 통과, 3.859초, exit 0(2026-10-13 KST, backend 실행).
- 55개 경로·메서드 × 토큰 없음/잘못된 토큰/익명 계정의 165개 거부 검사, 실제 REST 클라이언트의 JWT·공개키 전달, 사례/기록/초안/검색/전사/캐시 A/B 격리, DOCX 실제 ZIP/XML 결과를 검사했다. 테스트 종료 시 임시 파일·모의 데이터 정리, 원격 계정/행 생성 없음.
- 위 검사는 DB 응답에 소유자 격리를 가정한 모의 전송을 사용한다. 실제 PostgreSQL 정책·FK·RPC·버킷 검증은 아니며 DELETE는 현재 경로의 405만 확인한다. 내보내기는 호출자가 준 본문을 렌더링하며 다른 사용자의 저장 기록을 조회하지 않는 현재 계약을 검사한다.
- PR 3 준비: 브랜치 `codex/security-access-tests-20261013`; 파일은 신규 테스트와 이 기록뿐. 서영님 동일 파일 수정 여부 unknown, 병합 의존성 #38(순차 검증 기준), 되돌리기 위 테스트 커밋 revert. 제품 코드 변경 없음.
- 진행 중: 데이터 목록과 법률·문서 공개범위·서영님 통합 점검표의 최종 근거 확인.
- 서영님 통합 검증: 검토 가능한 PR/브랜치가 아직 식별되지 않아 대기. 독립 작업은 계속 진행.
- 운영 DB의 실제 RLS, 환경 변수 값, 공급자 계약·지역·보존 설정은 확인하지 않음.
- 테스트 통과는 운영 배포 완료나 법률 준수 인증을 의미하지 않음.
