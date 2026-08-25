# MVP Scope

## 1. Current product path

Re:mind는 상담사가 상담 후 자료를 정리하고 근거를 확인한 뒤 공식 문서로 내보내는
workspace입니다.

```text
자료 입력·추출
  ↓
회기 구조화와 이전 회기 retrieval
  ↓
근거가 연결된 회기요약 초안
  ↓
검증·수정·확정
  ↓
수퍼비전/종결 문서 변환과 DOCX/PDF export
```

초기 사용자 가설은 축어록, 회기 기록, 사례 보고서, 수퍼비전 자료를 반복 작성하는
수련상담사입니다. 결제 의향과 반복 사용 빈도는 아직 고객검증 대상입니다.

## 2. Implemented

### Session materials

- 상담사 메모, 축어록/STT, 이전 회기 요약 입력
- 상담 목표, 심리검사 요약, 키워드, 비언어·반언어 메모 입력
- PDF 텍스트 레이어, DOCX, TXT 추출
- 음성 업로드 UI, capability 확인, 선택적 WhisperX transcription
- 민감정보 후보 탐지와 입력 비식별화

### Note generation

- LangGraph 기반 11-node note-generation workflow
- 동일 상담자·사례 범위의 이전 확정 기록 retrieval
- 문서 양식과 개인정보·윤리 경고 KB retrieval
- 선택적 pgvector dense/hybrid retrieval
- 상담 내용 구조화와 source reference 연결
- 회기요약 초안, verification report, conditional revision
- 상담사 편집, 재구성, 확정, 임시저장

### Documents

- 회기 기록과 종결 보고서 변환 초안
- 한국상담심리학회 개인상담 사례 수퍼비전 보고서 A-1~C-2 초안
- 수퍼비전 보고서의 근거 상태, 누락 입력, AI review panel
- DOCX export
- capability가 충족된 runtime의 PDF export

### Identity and persistence

- Supabase email/password 및 OAuth frontend auth
- API의 Supabase access-token 검증
- 사용자 소유 상담 데이터의 RLS migration
- feature flag 기반 저장, case memory, retrieval
- 기본값 `SAVE_RAW_INPUT=0`, `ENABLE_CASE_MEMORY=0`

## 3. Current gaps

- 수퍼비전 report schema의 회기 이력, 합의 목표, 임상 목표, 상담전략, 이전 피드백을
  frontend가 모두 입력받아 전달하지 않음
- 수퍼비전 workflow가 case memory와 KB를 직접 검색하지 않음
- section별 필수 근거의 의미적 충족도를 판단하지 않음
- 입력에 따라 retrieval source를 고르는 router가 없음
- theory lens 또는 theory KB가 없음
- 기존 사례를 대량으로 옮기는 import/migration flow가 없음
- 감사 로그, 보관·삭제 정책, 동의 절차를 포함한 실사용 보안 운영 검토가 남아 있음

## 4. Explicit exclusions

- 실시간 상담 개입 또는 내담자 모니터링
- 상담사 수행 평가
- 진단, 자살·자해 위험 점수화, 치료 권고
- 자동 심리검사 해석
- 자율형 AI 수퍼바이저 또는 자동 사례개념화 확정
- 스캔 이미지 PDF OCR
- 실시간 녹음·streaming STT
- 검증된 HWPX template export
- 결제, 예약, 센터 관리자 dashboard

## 5. Product experiment boundary

다음 실험 후보는 `skip / case_memory / both` retrieval router, field-level evidence
sufficiency, 이전 인간 수퍼비전 피드백 carryover입니다. 제품 가치는 “agentic”이라는
명칭보다 준비시간 감소, 근거 coverage, unsupported claim 감소, 반복 사용으로 판단합니다.

Theory KB는 한 이론의 최소 근거 규칙을 전문가가 검수한 뒤 별도 실험으로 추가합니다.
여러 이론 목록 자체는 차별화 지표로 사용하지 않습니다.

## 6. Output rule

```text
AI 초안은 상담사의 검토 전 최종 기록으로 사용되지 않습니다.
상담사가 수정·확정한 내용만 최종 회기 기록으로 저장됩니다.
```
