# Re:mind Raw Evidence Grounding — Demo Checkpoint

## 1. Problem

The previous flow was:

```text
raw counseling transcript
→ AI-generated/confirmed summary
→ summary retrieval
→ downstream generation
```

This structure risks downstream generation reusing omissions or assumptions from earlier AI summaries as factual evidence.

## 2. Final decision

```text
raw transcript
→ deterministic raw windows
→ raw-region retrieval
→ grounded generation
→ semantic source validation
→ counselor review UI
```

## 3. Rejected approaches

- Global semantic episode extraction
- Turn-function based episode assembly
- Query-conditioned exact-span selector

Controlled synthetic evaluation revealed extraction/selection instability or false positives, so these
approaches were not adopted in the product path. Related code is experimental code for reproducing
research/evaluation history and is not connected to the production graph.

Location: `research/raw_evidence_experiments/`

## 4. Current evidence unit

The current evidence unit is a `raw region`.

- Generated deterministically.
- Uses de-identified, sanitized transcripts.
- Average region length in the controlled demo is approximately 8 turns.
- Each region retains a canonical `source_ref`.

## 5. Source hierarchy

```text
Raw transcript evidence
Counselor-confirmed judgment
Model clinical inference
Unsupported
```

## 6. Hallucination defenses

- Retrieval query text itself is not treated as generation evidence.
- Only validated sources are provided to generation.
- Cited source ID existence and claim-source semantic support are validated separately.
- Partial or unsupported claims are sent to `review_required`.
- Incorrectly cited sources are not automatically relinked to other sources.

## 7. UI

```text
AI claim
→ evidence control
→ exact cited historical transcript
```

Counselors use the evidence control beside a summary sentence to directly inspect the cited historical
session and sanitized source text. Counselor-confirmed notes, AI interpretations, and insufficient
evidence are displayed as distinct review states.

## 8. Current verification status

These results apply only to a small controlled synthetic corpus, not to production or real counseling accuracy.

- Raw region Gold Span Containment@5: 7/7
- Gold Session Recall@5: 7/7
- Query Success@5: 6/6
- Citation Validity: 100%
- Factual Claim Citation Coverage: 100%
- Semantic Support Validity: 100%
- False Supported Rate: 0%
- Source-removal False Support: 0%
- Wrong-source swap approved: 0
- PR5 grounding/evidence UI verification and frontend production build passed
- DEV synthetic demo enters the evidence UI without calling `/api/notes/generate`

Local verification artifacts are generated under `results/debug/` and are not included in the checkpoint commit.

## 9. Current limitations

- The synthetic corpus is small.
- Retrieval precision itself has not yet been validated on real counseling data.
- Top-5 contains regions that are non-gold but semantically related.
- Counselor-facing usability validation is needed.
- The grounding feature flag defaults to OFF.
- Remote Supabase migrations and production deployment require separate verification.

## 10. Next product validation

Ask counselors:

1. AI가 작성한 문장에서 근거 원문을 바로 열어 보는 것이 실제 검토에 도움이 되나요?
2. 근거로 제시되는 원문 범위가 약 8개 발화(턴)일 때, 너무 길거나 짧게 느껴지나요?
3. 원문 근거, 상담사가 검토·확정한 기록, AI의 해석이 서로 어떻게 다른지 이해하기 쉬운가요?
4. 이 근거 확인 기능이 있으면 실제 업무에서 AI가 작성한 문서를 사용할 의향이 높아지나요?
