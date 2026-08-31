# Re:mind Raw Evidence Grounding — Demo Checkpoint

## 1. 문제

기존 흐름은 다음과 같았다.

```text
raw counseling transcript
→ AI-generated/confirmed summary
→ summary retrieval
→ downstream generation
```

이 구조에서는 AI가 이전 요약에서 누락하거나 추정한 내용을 후속 생성이 factual evidence처럼 재사용할 위험이 있다.

## 2. 최종 결정

```text
raw transcript
→ deterministic raw windows
→ raw-region retrieval
→ grounded generation
→ semantic source validation
→ counselor review UI
```

## 3. 버린 접근

- Global semantic episode extraction
- Turn-function based episode assembly
- Query-conditioned exact-span selector

Controlled synthetic evaluation에서 extraction/selection instability 또는 false-positive가 관찰되어 제품 경로에서 채택하지 않았다. 관련 코드는 연구·평가 이력을 재현하기 위한 experimental 코드이며 production graph에 연결하지 않는다.

## 4. 현재 evidence unit

현재 evidence unit은 `raw region`이다.

- Deterministic하게 생성한다.
- 비식별화된 sanitized transcript를 사용한다.
- Controlled demo의 평균 region 길이는 약 8 turns이다.
- 각 region은 canonical `source_ref`를 유지한다.

## 5. source hierarchy

```text
Raw transcript evidence
Counselor-confirmed judgment
Model clinical inference
Unsupported
```

## 6. hallucination 방어

- Retrieval query text 자체는 generation evidence로 취급하지 않는다.
- Generation에는 validated source만 제공한다.
- 인용한 source ID의 존재 여부와 claim-source semantic support를 별도로 검증한다.
- Partial 또는 unsupported claim은 `review_required`로 보낸다.
- 잘못 인용된 source를 다른 source로 자동 relink하지 않는다.

## 7. UI

```text
AI claim
→ evidence control
→ exact cited historical transcript
```

상담사는 요약 문장 옆의 근거 control을 통해 인용된 과거 회기와 sanitized 원문을 직접 확인한다. 상담사 확정 기록, AI 해석, 근거 부족 상태는 서로 다른 review state로 표시한다.

## 8. 현재 검증 상태

아래 결과는 작은 controlled synthetic corpus에만 해당하며 production 또는 실제 상담 정확도를 의미하지 않는다.

- Raw region Gold Span Containment@5: 7/7
- Gold Session Recall@5: 7/7
- Query Success@5: 6/6
- Citation Validity: 100%
- Factual Claim Citation Coverage: 100%
- Semantic Support Validity: 100%
- False Supported Rate: 0%
- Source-removal False Support: 0%
- Wrong-source swap approved: 0
- PR5 grounding/evidence UI verification 및 frontend production build 통과
- DEV synthetic demo는 `/api/notes/generate` 호출 없이 evidence UI에 진입

로컬 검증 산출물은 `results/debug/` 아래에 생성하며 checkpoint commit에는 포함하지 않는다.

## 9. 현재 limitation

- Synthetic corpus가 작다.
- Retrieval precision 자체는 아직 실제 상담 데이터에서 검증되지 않았다.
- Top-5에는 non-gold이지만 의미상 관련된 region이 존재한다.
- Counselor-facing usability validation이 필요하다.
- Grounding feature flag의 기본값은 OFF다.
- Supabase remote migration과 production deployment는 별도 검증이 필요하다.

## 10. 다음 제품 검증

상담사에게 다음을 확인한다.

1. AI 문장에서 원문을 바로 확인하는 방식이 실제 검토에 도움이 되는가?
2. 약 8-turn 원문 범위가 너무 길거나 짧은가?
3. Raw evidence, 상담사 확정 기록, AI 해석의 구분이 이해되는가?
4. 이런 근거 확인 기능이 있으면 AI 작성 문서를 실제 업무에서 사용할 의향이 높아지는가?
