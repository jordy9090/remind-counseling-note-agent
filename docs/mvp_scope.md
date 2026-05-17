# MVP Scope

## 1. MVP V0 목표

MVP V0의 목표는 React + FastAPI + LangGraph 기반으로 핵심 상담 문서화 흐름을 데모 수준에서 동작시키는 것입니다.

```text
Session Input
  ↓
Input Sanitization
  ↓
Session Structuring
  ↓
Evidence Mapping
  ↓
Session Summary Draft
  ↓
Verification Report
  ↓
Document Transform Preview
```

Frontend에서는 상담사가 회기 자료를 입력하고, 결과 탭에서 구조화 결과, 회기요약 초안, 검증 리포트, 문서 변환 preview, Raw JSON을 확인합니다.

## 2. MVP V0 포함 범위

### 2.1 회기 입력

필수/주요 입력:

- 케이스 ID 또는 가명
- 회기 번호
- 회기 날짜
- 상담자
- 상담사 메모
- 축어록/STT 텍스트
- 이전 회기 요약

선택 입력:

- 상담 목표
- 심리검사 요약
- 주요 키워드
- 비언어/반언어 메모

### 2.2 입력 정제

- 전화번호, 이메일, 학교명, 실명 후보 등 민감정보 가능성 탐지
- 상담사 메모, 축어록/STT, 이전 회기 요약 분리
- 입력 자료를 Pydantic schema에 맞게 정규화

### 2.3 상담 내용 구조화

생성되는 공통 중간 구조:

- 주호소 / 주요 이슈
- 회기 주제
- 상담 내용
- 상담자 개입
- 내담자 반응
- 중요한 내담자 발화
- 비언어/반언어 메모
- reflection 후보
- 추후 계획

### 2.4 근거 매핑

각 구조화 항목에 근거 유형과 source reference를 연결합니다.

- `direct`
- `inferred`
- `counselor_input`
- `previous_context`
- `needs_review`
- `mixed`
- `model_inference`

### 2.5 회기요약 초안 생성

Frontend에서 섹션별 textarea로 수정 가능한 회기요약 초안을 생성합니다.

- 회기 정보
- 회기 주제
- 주호소 / 주요 문제
- 상담 내용 요약
- 상담자 개입
- 내담자 반응 및 변화
- reflection
- 추후 개입 계획

### 2.6 검증 리포트 생성

검증 리포트는 다음 항목을 분리합니다.

- 입력 근거 있음
- 입력 근거 부족 / 추론 가능성
- 민감정보 후보
- 상담사 직접 판단 필요

### 2.7 문서 변환 Preview

MVP V0에서는 문서 변환을 완성 기능으로 제공하지 않습니다.

현재 구현은 확정된 회기요약을 슈퍼비전 보고서 또는 종결 보고서로 확장할 때 필요한 preview section과 부족 필드를 보여주는 수준입니다.

## 3. 현재 Frontend 구현 범위

현재 `SessionDraftPage`는 다음을 제공합니다.

- 입력 폼
- 처리 단계 UI
- 구조화 결과 탭
- 회기요약 초안 textarea 편집
- 검증 리포트 탭
- 문서 변환 Preview 탭
- Raw JSON 탭

아직 DB 저장이나 최종 확정 저장은 구현하지 않습니다. textarea 수정은 현재 화면 안에서의 검토/편집용입니다.

## 4. MVP V0 제외 범위

- 실시간 상담 지원
- 상담사 수행 평가
- 완전 자동 사례개념화
- AI 슈퍼비전
- 자살/자해 위험 판단
- 원본 음성 저장
- 파일 업로드
- 장기 상담 데이터베이스
- Vector DB/RAG
- 관리자 대시보드
- 예약, 결제, 노쇼 관리
- 정식 Word/HWP/PDF 내보내기
- 로그인/회원가입

## 5. MVP V1 후보

- 상담사 확정 기록 저장 정책 설계
- 슈퍼비전 보고서 초안 변환 고도화
- 종결 보고서 초안 변환 고도화
- 문서 유형별 부족 정보 탐지 고도화
- 상담사 맞춤형 회기요약 섹션 설정
- 복사, Markdown, Word 내보내기
- 보안 저장 정책 수립 후 DB 검토

## 6. 제품 문구 원칙

Frontend와 backend는 다음 원칙을 유지해야 합니다.

```text
AI 초안은 상담사의 검토 전 최종 기록으로 사용되지 않습니다.
상담사가 수정·확정한 내용만 최종 회기 기록으로 저장됩니다.
```

MVP V0 현재 구현에서는 저장 기능이 없으므로, 이 문구는 제품 원칙과 V1 저장 기능의 기준으로 유지합니다.
