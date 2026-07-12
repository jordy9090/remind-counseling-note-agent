# Re:mind 회기요약 모델 파인튜닝 (QLoRA SFT)

상담 축어록/메모 → 구조화된 한국어 회기요약(`SessionSummaryDraft` JSON)을 생성하는
오픈 LLM을 QLoRA로 파인튜닝하는 파이프라인입니다. 목표는 backend의
`generate_summary` 노드(현재 OpenAI `gpt-4o-mini`)를 자체 모델로 대체하는 것입니다.

## 데이터 전략

"한국어 축어록 ↔ 회기요약" 페어를 그대로 제공하는 공개 데이터는 없습니다.
따라서 3계층으로 구성합니다.

| 계층 | 원천 | 언어 | 라이선스 | 역할 |
|---|---|---|---|---|
| 형식 학습 | [CACTUS](https://huggingface.co/datasets/cactus-camel/cactus) 31,577건 | 영어 | MIT | intake/CBT계획 필드에서 규칙 기반으로 노트 타깃 생성. "대화→구조화 JSON" 형식 자체를 학습 |
| 한국어 핵심 | [KMI](https://github.com/hjkim811/KMI) 1,000건 | 한국어 | CC BY 4.0 | 전문가 검증된 한국어 상담 대화. LLM 증류로 노트 타깃 합성 |
| 보조/확장 | [CPsyCounD](https://huggingface.co/datasets/CAS-SIAT-XinHai/CPsyCoun) 3,134건 | 중국어 | CC BY-SA 4.0 | 대화만 있음. 한국어 노트 합성(교차언어 증류)으로 확장 가능 |
| **최상위(확보 완료)** | AI Hub 심리상담 데이터 (dataSetSn=71806) 개방데이터 | 한국어 | AI Hub 약관 (재배포 금지) | 실제 상담 축어록 + 요약 라벨(주요 증상/위험·개선요인/상담사 개입요인). 합성 없이 노트 페어 구성. 1,496회기 변환, 1,251건 노트 생성 완료 |

사용하지 않는 것: ESConv(학술 전용), Psych8k·KokoroChat(비상업), AI Hub 재업로드본(약관 위반 소지),
싱글턴 상담 Q&A류(태스크 형식 불일치).

## 파이프라인

```text
data/convert.py            원천 데이터 → 중간 형식 (intermediate_<source>.jsonl)
data/synthesize_notes.py   노트 없는 대화(KMI 등)에 LLM으로 한국어 노트 타깃 생성  [OPENAI_API_KEY 필요]
data/convert_aihub_71806.py AI Hub 심리상담 데이터 승인 후 변환 (스켈레톤, 명세서 확인 후 매핑)
data/build_sft_dataset.py  노트 있는 레코드 → chat 형식 sft_train/val.jsonl
train/train_qlora.py       QLoRA SFT (trl + peft + bitsandbytes)                  [GPU 필요]
eval/quick_eval.py         JSON 파싱률 / 스키마 유효율 / 한국어 비율 등 구조 평가   [GPU 필요]
```

### 1. 환경 (CPU, 이 레포에서 완료됨)

```bash
cd finetuning
uv venv .venv
uv pip install --python .venv -r requirements.txt
```

### 2. 데이터 다운로드 & 변환 (완료됨)

```bash
git clone --depth 1 https://github.com/hjkim811/KMI data/raw/KMI
python - <<'PY'
from huggingface_hub import hf_hub_download
import shutil
shutil.copy(hf_hub_download('cactus-camel/cactus', 'cactus.json', repo_type='dataset'), 'data/raw/cactus.json')
shutil.copy(hf_hub_download('CAS-SIAT-XinHai/CPsyCoun', 'CPsyCounD.json', repo_type='dataset'), 'data/raw/CPsyCounD.json')
PY
python data/convert.py --source all
```

### 3. 한국어 노트 합성 (다음 단계 — API 키 필요)

```bash
export OPENAI_API_KEY=sk-...
python data/synthesize_notes.py --source kmi --limit 20   # 품질 확인
python data/synthesize_notes.py --source kmi              # 전체 (~$1 미만, gpt-4o-mini)
```

합성 결과 20건 정도를 직접 읽어보고(특히 evidence_type 정직성),
프롬프트를 조정한 뒤 전체를 돌리는 것을 권장합니다.

### 3.5 AI Hub 심리상담 데이터 변환 (완료됨)

```bash
python data/convert_aihub_71806.py --input "C:/Users/.../16.심리상담 데이터/3.개방데이터"
```

- 라벨 ZIP 75개를 직접 읽어 1,496회기 변환 (우울증 437 / 불안장애 436 / 중독 404 / 일반군 219)
- summary 4개 섹션(주요 증상/위험요인/개선요인/상담사의 개입요인)을 노트 필드로 매핑,
  내담자 변화 라벨 발화를 client_response 인용으로 사용 → 1,251건 노트 페어
- 원본 결함 자동 복구: summary 값 미인용(JSON 깨짐), 숫자형 발화 텍스트.
  복구 불가 1건, 요약 결측 245건(노트 없음 — 합성 대상으로 남음)
- **주의: AI Hub 약관상 재배포 금지. data/raw, data/processed는 gitignore 유지**

### 4. SFT 데이터셋 빌드 (완료됨: train 1,769 / val 93)

```bash
python data/build_sft_dataset.py --sources aihub_71806,cactus --max-per-source cactus=1000 --max-chars 28000
```

- `--max-chars 28000`: 실측(Qwen 토크나이저) 기준 축어록+노트가 p50 15.8k / p90 19k 토큰이라,
  20k 컨텍스트에 안 들어가는 상위 31%(389건)는 제외. VRAM이 크면 상한을 올려 복구 가능
- KMI 합성 완료 후: `--sources aihub_71806,kmi,cactus`

### 5. QLoRA 학습 (GPU 서버)

**학습 데이터는 AI Hub 약관상 레포에 없습니다.** 데이터를 가진 사람이
`finetuning/data/processed/sft_train.jsonl`, `sft_val.jsonl`을 서버에 직접 복사해야 합니다:

```bash
scp finetuning/data/processed/sft_{train,val}.jsonl user@server:~/remind-counseling-note-agent/finetuning/data/processed/
```

서버에서 (tmux 안에서 실행 — SSH가 끊겨도 학습이 유지됨):

```bash
pip install -r finetuning/requirements-train.txt
tmux new -s train
python finetuning/train/train_qlora.py --config finetuning/configs/qlora_qwen25_7b.yaml
# Ctrl+B, D 로 detach / tmux attach -t train 으로 복귀

python finetuning/eval/quick_eval.py --adapter finetuning/output/qwen25-7b-remind-note-qlora --limit 50
```

- 베이스 모델: **Qwen2.5-7B-Instruct** (Apache-2.0, 한국어 우수). 대안: gemma-2-9b-it, Llama-3.1-8B-Instruct (config 주석 참고)
- 축어록이 길어 max_seq_length=20480 — **A100 40GB 이상 권장** (T4/L4 불가).
  VRAM이 부족하면 `--max-chars`와 max_seq_length를 함께 낮추세요 (config 주석 참고)
- 긴 시퀀스에서는 loss 계산 시 logits 메모리(vocab 152k × seq 20k ≈ 12GB)가 병목이라
  **Liger 커널(`use_liger: true`)이 기본 활성화**되어 있습니다. 미설치 시 경고 후 비활성화됩니다
- 무료 Colab(T4 16GB)은 이 구성으로 불가. Colab Pro A100이면 노트북 없이 위 명령 그대로 실행 가능
- 학습 후 서빙: vLLM(`--enable-lora`) 또는 어댑터 머지 후 GGUF 변환(Ollama)

### 6. 백엔드 연동 (학습 후)

`backend/app/services/llm.py`의 `get_structured_llm`이 유일한 교체 지점입니다.
vLLM은 OpenAI 호환 API를 제공하므로 `OPENAI_BASE_URL`만 바꾸면 LangChain의
`with_structured_output`이 그대로 동작합니다 (vLLM의 guided JSON 지원 확인 필요).

## AI Hub 심리상담 데이터 (71806) 신청 체크리스트

1. https://aihub.or.kr → dataSetSn=71806 페이지에서 사용신청 (내국인 계정 필요)
2. **신청 전 safezone1@aihub.kr에 확인할 것**:
   - 안심존 전용 여부 (일반 다운로드 가능한지)
   - 안심존 내 GPU 학습 후 **모델(LoRA 어댑터) 반출 가능 여부**
   - 상용 서비스에 탑재되는 모델 학습 목적 사용 가능 여부
3. 승인 후: 데이터 명세서를 보고 `data/convert_aihub_71806.py`의 TODO 필드 매핑을 채운 뒤 실행
4. 요약 라벨이 있으므로 합성 없이 최고 품질 한국어 페어가 됩니다 → `--sources aihub_71806,kmi,cactus`

## 알려진 한계

- CACTUS 규칙 기반 노트는 영어이고, presenting_problem이 접수면접지 1인칭 원문 발췌라
  문체가 노트체와 다릅니다. 형식(JSON 구조, evidence_type 규율) 학습용으로만 쓰고
  배합 비율을 한국어 데이터보다 낮게 유지하세요.
- KMI는 동기강화상담(MI) 스타일 합성 대화라 실제 축어록보다 짧고 정돈되어 있습니다.
  실전 품질은 AI Hub 71806 확보 여부에 크게 좌우됩니다.
- 합성 타깃은 teacher 모델(gpt-4o-mini)의 상한에 묶입니다. 품질을 올리려면 teacher를
  gpt-4o 등으로 올리고 소량-고품질로 가는 편이 낫습니다.
