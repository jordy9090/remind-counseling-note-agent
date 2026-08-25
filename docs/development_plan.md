# Development Plan

## Current baseline

현재 기준선은 다음 흐름을 end-to-end로 제공합니다.

- Supabase authentication과 user-scoped draft persistence
- PDF/DOCX/TXT material extraction
- optional WhisperX transcription
- 11-node LangGraph note-generation workflow
- optional pgvector dense/hybrid retrieval
- evidence mapping, verification, conditional revision
- 상담사 편집·재구성·확정
- 한국상담심리학회 수퍼비전 보고서 초안
- DOCX 및 capability 기반 PDF export

`main`의 CI는 backend smoke, Vercel wrapper regression, PDF/supervision regression,
frontend workflow verification과 production build를 모두 실행해야 합니다.

## P0: expose the supervision data already supported

새 임상 추론을 추가하기 전에 backend schema에 이미 있는 다음 필드를 frontend에 연결합니다.

- 총 예정 회기와 회기별 날짜·주제·진행 상태
- 내담자와 합의한 목표
- 상담자의 임상 목표
- 상담전략
- 수퍼비전에서 도움받고 싶은 점
- 이전 인간 수퍼비전 피드백

완료 기준:

- 요청 payload와 저장 draft에 필드가 유지됨
- 보고서에서 `direct`, `ai_organized`, `clinical_review`, `missing`이 보임
- 누락 정보가 section 안의 수정 가능한 입력으로 이어짐
- 이전 피드백이 다음 보고서에서 인간이 작성한 정보로 구분됨
- DOCX/PDF export가 화면의 최신 수정 내용을 사용함

## P0: reduce first-use migration cost

- 기존 PDF/DOCX/TXT 여러 개를 한 사례로 가져오는 flow
- 파일별 추출 성공·경고·실패 상태
- 중복 회기와 날짜 충돌 확인
- 실제 저장 전에 상담사가 사례와 회기를 확정

송은영 인터뷰에서 기존 사례를 다시 입력하는 비용이 명시적인 이탈 이유로 제시되었습니다.

## P1: adaptive retrieval experiment

고정 workflow 전체를 자율화하지 않고 다음 최소 실험을 별도 feature branch에서 검증합니다.

```text
section requirements
  ↓
skip / case_memory / both
  ↓
field-level evidence sufficiency
  ├─ generate
  ├─ one retrieval retry
  ├─ generate partial
  └─ request section input
```

구현 전 필요한 평가자료:

- 실제 사례에서 section별 필요한 source와 query 정답
- 필수 evidence slot과 허용 가능한 누락
- route accuracy, latency, token, coverage, unsupported claim 지표

LLM confidence 숫자만으로 sufficiency를 결정하지 않습니다. 개인정보 scope, retry 횟수,
human-review 대상은 코드 규칙으로 제한합니다.

## P2: one-theory vertical slice

최한나 교수와 첫 이론의 개념 체계와 최소 근거 조건을 합의한 뒤 한 section에서만 실험합니다.

- theory definition, observable indicators, required evidence
- alternative explanation과 반례 질문
- 적용 한계와 검수자·버전
- 이론 문서와 case evidence의 명시적 분리

CBT, 정서중심, Bowen을 한 번에 추가하지 않습니다. Theory 수는 경쟁력 지표로 사용하지
않고, GPT 대비 반복 사용 가치가 확인된 lens만 확장합니다.

## Deferred

- 센터 관리자 dashboard와 다계정 운영
- 수퍼바이저 전용 계정
- 자격 수련 횟수 자동 인정·증빙
- 결제와 예약
- HWPX template export
- 실시간 상담 또는 내담자 monitoring
- 자동 사례개념화와 AI 임상 조언
