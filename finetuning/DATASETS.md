# 데이터셋 출처·라이선스·사용 상태

| source | 출처 | 언어 | 규모 | 라이선스 | SFT 사용 상태 |
|---|---|---|---|---|---|
| `aihub_71806` | [AI Hub 심리상담 데이터 (dataSetSn=71806)](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71806) | ko | 1,496회기 / 노트 1,251건 | AI Hub 이용약관 — **재배포 금지**, 승인 사용자만 | **주 학습 데이터.** 요약 라벨 4섹션을 노트로 매핑 |
| `cactus` | [cactus-camel/cactus (HF)](https://huggingface.co/datasets/cactus-camel/cactus) | en | 31,577건 | MIT | 보조(형식 학습). 규칙 기반 노트, 배합 상한 권장 |
| `kmi` | [hjkim811/KMI (GitHub)](https://github.com/hjkim811/KMI), NAACL 2025 | ko | 1,000 대화 | CC BY 4.0 | 변환기 준비됨. 노트 라벨 없음 → `synthesize_notes.py`로 증류 후 사용 |
| `cpsycoun` | [CAS-SIAT-XinHai/CPsyCoun (HF)](https://huggingface.co/datasets/CAS-SIAT-XinHai/CPsyCoun) | zh | 3,134 대화 | CC BY-SA 4.0 | 미사용(교차언어 증류 후보). SA 조건 주의 |
| `mts_dialog` | [abachaa/MTS-Dialog (GitHub)](https://github.com/abachaa/MTS-Dialog), LREC 2023 | en | 1,698 스니펫 | CC BY 4.0 | **변환기만 준비.** 대화→임상 문서 섹션 페어. 원본 문서는 `meta.native_note`에 보존, Re:mind 스키마 매핑 확정 전 SFT 미사용 |
| `aci_bench` | [wyim/aci-bench (GitHub)](https://github.com/wyim/aci-bench), NPJ Digit. Med. 2023 | en | 207 진료 대화 | CC BY 4.0 | **변환기만 준비.** 긴 의사·환자 대화→전체 임상 노트. `meta.native_note` 보존, SFT 미사용 |

## 공통 intermediate 스키마

```json
{
  "id": "aihub71806-train-depression-D005-s1",
  "case_id": "aihub71806-depression-D005",
  "source": "aihub_71806",
  "language": "ko",
  "license": "...",
  "dialogue": [{"speaker": "counselor|client", "text": "...", "label": null}],
  "meta": {"session_number": 1, "native_note": "...(선택)"},
  "note": null
}
```

- `id`: 전역 유일. 변환기가 중복 시 하드 실패.
- `case_id`: 같은 내담자/사례의 모든 회기가 공유. **split은 반드시 case_id 단위 group split.**
- `note`: SessionSummaryDraft 형태일 때만 SFT에 포함. 다른 스키마의 문서(MTS/ACI)는
  `meta.native_note`에 두고 note는 null 유지 — 실수로 믹스에 섞이는 것을 방지.

## 사용 금지 결정

- ESConv(학술 전용), Psych8k(CC BY-NC-SA), KokoroChat(CC BY-NC-ND): 라이선스상 상업 파인튜닝 불가
- AI Hub 데이터의 HF/GitHub 재업로드본: 약관 위반 소지
- 싱글턴 상담 Q&A(Amod, CounselChat 등): 태스크 형식 불일치 (챗봇 응답 생성 ≠ 회기요약 생성)

## 재배포 주의

`data/raw`, `data/processed`, `output/`, `eval/results/`는 gitignore 대상입니다.
특히 AI Hub 파생물(sft_*.jsonl 포함)은 외부 공개·업로드 금지.
