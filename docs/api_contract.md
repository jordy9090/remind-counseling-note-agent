# API Contract

The MVP V1 end-to-end demo uses FastAPI as the backend, React/Vite as the frontend, and optional Supabase-backed retrieval.

## Health Check

```text
GET /api/health
```

Response:

```json
{
  "status": "ok"
}
```

## Generate Note Draft

```text
POST /api/notes/generate
```

The endpoint runs the retrieval-aware LangGraph note generation workflow and returns the full Pydantic-validated `GenerateNoteResponse`. If `OPENAI_API_KEY` is missing, or if the LLM call fails, the backend falls back to deterministic demo output. If Supabase or RAG settings are missing, retrieval and persistence are skipped while the response shape remains stable. The React frontend maps this full response into its screen-specific display state.

### Request

```json
{
  "case_id": "CASE001",
  "client_alias": "가명 은하",
  "session_number": 3,
  "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고를 중심으로 진행함.",
  "transcript": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
  "previous_summary": "이전 회기에서는 자기이해와 진로 가치 탐색을 중심으로 다룸.",
  "target_document_type": "session_note",
  "persist": false
}
```

Accepted input aliases:

- `transcript_text` is also accepted for `transcript`.
- `previous_session_summary` and `prev_summary` are also accepted for `previous_summary`.
- `session_no` is also accepted for `session_number`.
- `document_type` is also accepted for `target_document_type`.
- `persist=true` stores the generated note only when `ENABLE_PERSISTENCE=1` and Supabase credentials are configured.
- `SAVE_RAW_INPUT=0` is the default; raw counselor memo/transcript payloads are not stored unless `SAVE_RAW_INPUT=1`.
- `/api/notes/*` endpoints require `X-Remind-Preview-Token` until production Supabase Auth mapping exists.
- `POST /api/notes/confirm` accepts only `note_id`, `confirmed_note`, `counselor_edited`, and `create_case_memory`; case/session/counselor identity is derived from stored rows and the server actor.
- `ENABLE_CASE_MEMORY=0` is the default. Confirmed note memory chunks are written only when persistence and case-memory indexing are explicitly enabled.

### Frontend Display Projection

The full API response includes `sanitized_input`, `retrieved_case_context`, `retrieved_template_context`, `retrieved_privacy_context`, `retrieval_report`, `structured_case_data`, `evidence_mapped_data`, `session_summary_draft`, `verification_report`, `document_transform_preview`, `confirmed_session_note`, `persistence_report`, and `stub`. The frontend derives the following compact display fields from that full response:

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_summary": "이번 회기에서는 취업 준비 과정에서 나타나는 진로 불안과 자기비난 사고를 다루었다.",
  "main_issue": "내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
  "counselor_intervention": "상담자는 내담자의 표현을 구체화하고 불안과 자기비난 사고를 탐색하도록 질문함.",
  "client_response": "내담자는 진로 불확실성과 관련된 불안을 언어화함.",
  "next_plan": "다음 회기에는 자동사고 기록지를 함께 검토함.",
  "evidence_check": [
    {
      "claim": "내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
      "source_type": "transcript",
      "source_excerpt": "C: 지난 회기 이후 어떻게 지내셨나요? Cl: 여전히 진로가 불확실해서 불안해요.",
      "confidence": "high"
    }
  ],
  "missing_items": ["reflection", "case_conceptualization", "goal_attainment"],
  "warnings": ["AI 초안은 상담사의 검토 전 최종 회기 기록으로 사용되지 않습니다."]
}
```

Field notes:

- `source_type`: `transcript`, `counselor_memo`, `previous_summary`, `retrieved_context`, `template_context`, `privacy_context`, or `ai_inference`
- `confidence`: `high`, `medium`, or `low`
- `missing_items`: fields that may require additional counselor input or review
- `warnings`: safety and review notices shown to the counselor

## Recompose Summary Draft

```text
POST /api/notes/recompose
```

When the counselor changes the "요약에 포함할 항목" checklist, the frontend calls this endpoint instead of only hiding sections locally. The backend regenerates a checklist-specific AI draft and caches it by normalized `session_input`, `session_topic`, and `visible_section_ids`, so repeated clicks with the same settings reuse the existing generated draft instead of spending more LLM tokens.

### Request

```json
{
  "session_input": {
    "case_id": "CASE001",
    "client_alias": "가명 은하",
    "session_number": 3,
    "session_date": "2026-05-17",
    "counselor_name": "박상담사",
    "counselor_memo": "이번 회기는 진로 불안과 자기비난 사고를 중심으로 진행함.",
    "transcript_text": "C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요.",
    "previous_session_summary": ""
  },
  "session_topic": "진로 불안과 자기비난 사고 점검",
  "visible_section_ids": ["main_issue", "session_theme", "session_content"]
}
```

### Response

```json
{
  "result": {},
  "visible_section_ids": ["main_issue", "session_theme", "session_content"],
  "cache_key": "sha256-cache-key",
  "cache_hit": false
}
```

`result` is the same full `GenerateNoteResponse` shape returned by `POST /api/notes/generate`.

## Temporary Draft Save

```text
POST /api/notes/drafts
GET  /api/notes/drafts/{draft_id}
GET  /api/notes/drafts?case_id=CASE001
```

The temporary draft endpoint stores the counselor's current workspace state before final confirmation. It preserves the current screen, raw input form, selected checklist items, editable summary sections, and generated draft response when available.

### Save Request

```json
{
  "case_id": "CASE001",
  "session_number": 3,
  "session_date": "2026-05-17",
  "counselor_name": "박상담사",
  "screen": "summary_draft",
  "form": {},
  "session_topic": "진로 불안과 자기비난 사고 점검",
  "visible_section_ids": ["main_issue", "session_theme", "session_content"],
  "draft_sections": [],
  "result": null,
  "final_document_type": "session_note"
}
```

If `draft_id` is included, the backend updates that temporary draft. If it is omitted, the backend creates a new temporary draft.

### Save Response

```json
{
  "draft_id": "draft_1234",
  "case_id": "CASE001",
  "session_number": 3,
  "saved_at": "2026-06-19T03:40:00+00:00",
  "message": "임시저장되었습니다."
}
```

## Export Final Document

```text
GET /api/documents/capabilities
```

Returns server-side export availability. PDF availability is checked by importing WeasyPrint and rendering a minimal PDF, so clients can disable PDF download before sending an export request.

Response:

```json
{
  "docx": {
    "available": true
  },
  "pdf": {
    "available": false,
    "reason": "WeasyPrint native runtime is unavailable."
  },
  "hwpx": {
    "available": false,
    "reason": "Verified HWPX template is not configured."
  }
}
```

```text
POST /api/documents/export
```

Generates a downloadable file from the counselor's latest final-document draft. The frontend sends only visible, non-empty sections. For supervision reports, `contentBlocks` preserve paragraph, table, transcript, and reflection box structure.

AI review fields such as `missing_items`, warnings, unsupported claims, and human-review prompts remain screen-only review data. They are not automatically included in exported document metadata.

### Request

```json
{
  "format": "docx",
  "document_type": "session_note",
  "case_id": "CASE-DEMO-001",
  "session_number": 5,
  "session_date": "2026-05-24",
  "title": "상담 회기 기록",
  "metadata": {
    "client_alias": "가명 은하",
    "counselor_name": "박상담사"
  },
  "sections": [
    {
      "id": "main_issue",
      "title": "주요 호소",
      "content": "진로 불안과 자기비난 사고를 호소함."
    }
  ]
}
```

Supported `format` values are `docx`, `pdf`, and `hwpx`. DOCX and PDF return a file byte stream. HWPX currently returns 422 until a verified HWPX template ZIP structure is available.

### Response

```text
200 OK
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; filename="document_export.docx"; filename*=UTF-8''...
```

PDF responses use `application/pdf`. Filenames follow `{문서유형}_{case_id}_{회기번호}_{날짜}.{확장자}` with unsafe filename characters replaced by `_`.

## Extract Uploaded Materials

```text
POST /api/materials/documents/extract
```

Accepts a multipart `file` field and extracts text without permanently storing the raw upload. Supported formats are TXT, DOCX, and text-layer PDF. Default size limit is 20MB and can be changed with `DOCUMENT_UPLOAD_MAX_BYTES`. DOCX uploads are additionally checked with `DOCX_MAX_ARCHIVE_MEMBERS`, `DOCX_MAX_UNCOMPRESSED_BYTES`, and `DOCX_MAX_COMPRESSION_RATIO` before parsing.

The backend validates extension, `Content-Type`, and file signature. Empty files return 400, oversized files return 413, and unsupported or mismatched formats return 415.

### Request

```text
Content-Type: multipart/form-data
file=@case-note.docx
```

### Response

```json
{
  "material_id": "material_abc123",
  "filename": "case-note.docx",
  "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "status": "completed",
  "character_count": 3421,
  "page_count": null,
  "extracted_text": "상담 메모...",
  "warnings": []
}
```

Scanned/image-only PDFs return 200 with `status: "warning"` and a warning that OCR is not currently supported.

## Audio Capabilities and Transcription

```text
GET /api/audio/capabilities
```

Returns whether this runtime can accept audio uploads, whether automatic transcription is configured, and which runtime mode is active. Upload is available by default. `AUDIO_TRANSCRIPTION_STUB=1` enables a demo transcript that does not analyze uploaded audio. Real transcription requires `AUDIO_TRANSCRIPTION_STUB=0`, `ENABLE_AUDIO_TRANSCRIPTION=1`, `AUDIO_TRANSCRIPTION_ENGINE=whisperx`, and the optional `audio-whisperx` dependency group. Speaker diarization is opt-in with `ENABLE_AUDIO_DIARIZATION=1` and `HF_TOKEN`.

```json
{
  "upload": {
    "available": true
  },
  "transcription": {
    "available": false,
    "reason": "음성 자동 축어록 런타임이 비활성화되어 있습니다."
  },
  "speaker_diarization": {
    "available": false,
    "reason": "실제 화자 분리는 WhisperX 런타임에서 별도 설정 후 활성화됩니다."
  },
  "runtime_mode": "disabled"
}
```

```text
POST /api/audio/transcribe
```

Accepts multipart `file`, optional `language`, optional `task`, and optional `expected_speakers`. Supported uploads are WAV, MP3, and M4A. Default size limit is 500MB and can be changed with `AUDIO_UPLOAD_MAX_BYTES`. Runtime duration and process-level concurrency default to 7200 seconds and one job, controlled by `AUDIO_MAX_DURATION_SECONDS` and `AUDIO_MAX_CONCURRENT_JOBS`.

`expected_speakers` defaults to 2 and must be between 1 and 4. When transcription is unavailable, the endpoint returns 503. In stub mode, the endpoint returns a clearly marked demo transcript with warning text: `시연용 예시 축어록이며 업로드 음성을 분석한 결과가 아닙니다.`

Real mode uses WhisperX 3.8.6 for ASR, the explicit `kresnik/wav2vec2-large-xlsr-korean` forced-alignment model, Community-1 diarization, and WhisperX speaker assignment. Alignment failure retains ASR segment timestamps. Diarization failure retains transcription as one `SPEAKER_00` speaker.

`pause_before_seconds` is based on the previous chronological transcript turn end time. `speech_rate_wps` is turn words per second, and `speech_rate_level` is speaker-relative when enough samples exist. `volume_level` is computed from the already-decoded waveform and compared within the same speaker when enough turns exist. The API does not infer emotion, depression, anxiety, risk, diagnosis, tremor, or treatment effect from audio.

### Response

```json
{
  "transcription_id": "transcription_abc123",
  "filename": "session.wav",
  "status": "completed",
  "runtime_mode": "real",
  "transcription_engine": "whisperx",
  "alignment_model": "kresnik/wav2vec2-large-xlsr-korean",
  "diarization_model": "pyannote/speaker-diarization-community-1",
  "alignment_status": "completed",
  "diarization_status": "disabled",
  "duration_seconds": 142.3,
  "language": "ko",
  "language_probability": 0.98,
  "segments": [
    {
      "id": 1,
      "start": 0.0,
      "end": 4.2,
      "text": "상담자 발화...",
      "speaker": "SPEAKER_00",
      "pause_before_seconds": 0.8,
      "duration_seconds": 4.2,
      "speech_rate_wps": 1.7,
      "speech_rate_level": "typical",
      "volume_level": "low",
      "confidence": 0.91,
      "words": []
    }
  ],
  "transcript_text": "상담자 발화...",
  "nonverbal_notes": "",
  "warnings": []
}
```

## Local Run

Backend:

```bash
cd backend
uv run uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
pnpm dev
```

If `pnpm` is not available in the local environment, the same Vite scripts can be run with npm:

```bash
npm run dev
```
