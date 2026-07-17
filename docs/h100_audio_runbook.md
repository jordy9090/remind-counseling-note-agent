# H100 WhisperX Audio Runbook

This runbook enables the optional WhisperX 3.8.6 runtime on a research H100 host. Keep the backend bound to localhost and do not expose it publicly.

## Runtime Modes

- `AUDIO_TRANSCRIPTION_STUB=1`: deterministic demo output. It does not import WhisperX, faster-whisper, pyannote, or torch and does not analyze the uploaded audio.
- `AUDIO_TRANSCRIPTION_STUB=0` and `ENABLE_AUDIO_TRANSCRIPTION=1`: real WhisperX mode.
- Both disabled: `/api/audio/transcribe` returns 503 and `/api/audio/capabilities` reports `runtime_mode: disabled`.

## Install

Core backend CI does not install GPU or model dependencies. On the assigned H100 host only:

```bash
cd backend
uv sync --extra audio-whisperx
ffmpeg -version
```

Accept the Hugging Face access conditions for `pyannote/speaker-diarization-community-1` before enabling diarization. Keep the read token in the host environment only. Do not commit tokens, model weights, CUDA caches, generated transcripts, or local model-cache paths.

## Configure

```env
AUDIO_TRANSCRIPTION_STUB=0
ENABLE_AUDIO_TRANSCRIPTION=1
AUDIO_TRANSCRIPTION_ENGINE=whisperx

WHISPERX_MODEL=large-v3
WHISPERX_LANGUAGE=ko
WHISPERX_DEVICE=cuda
WHISPERX_COMPUTE_TYPE=float16
WHISPERX_BATCH_SIZE=4
WHISPERX_ALIGN_MODEL=kresnik/wav2vec2-large-xlsr-korean

ENABLE_AUDIO_DIARIZATION=1
WHISPERX_DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
HF_TOKEN=<read-token>

AUDIO_MAX_DURATION_SECONDS=7200
AUDIO_MAX_CONCURRENT_JOBS=1
```

`WHISPERX_DEVICE=auto` selects CUDA when available and otherwise uses CPU. A CPU fallback converts `float16` to `int8` for a safer local setting. Do not hard-code a numeric GPU index in the application; use `CUDA_VISIBLE_DEVICES` to select the assigned GPU.

## Run One Worker

WhisperX ASR, Korean alignment, and diarization models are cached once per backend process. Run one worker and never use `--reload` with the real GPU runtime.

```bash
cd backend
CUDA_VISIBLE_DEVICES=<assigned_gpu> \
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1
```

Use a local SSH tunnel instead of exposing the research host:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<research-server>
```

Point the local frontend at the tunnel:

```bash
cd frontend
VITE_API_BASE_URL=http://localhost:8000 pnpm dev
```

## First Verification

Use only synthetic or de-identified audio for the first run, preferably a 5-10 minute two-speaker sample. Do not use identifiable counseling audio.

1. Confirm `GET /api/audio/capabilities` reports `runtime_mode: real` and transcription available.
2. Submit the sample with `expected_speakers=2`.
3. Confirm `transcription_engine=whisperx`, `alignment_status`, and `diarization_status` in the response.
4. Review Korean word timing, speaker turns, the one-second turn gap rule, and transcript text manually.
5. Repeat once and confirm the process does not reload all three models.

If Korean alignment fails, ASR segment timestamps are retained with `alignment_status=fallback`. If diarization is disabled, the token is missing, access conditions are not accepted, or diarization fails, ASR/alignment output is retained as `SPEAKER_00` with `diarization_status=fallback`. User-facing responses must not include raw exceptions, tokens, server paths, or model-cache paths.

## Acoustic Observations

- `pause_before_seconds` uses the immediately preceding chronological turn end. Another speaker's turn is not counted as silence.
- `speech_rate_wps` is whitespace-delimited Korean eojeol count divided by turn duration.
- `speech_rate_level` uses the same speaker's median and remains empty with fewer than three valid turns.
- `volume_level` reuses the decoded waveform, computes per-turn RMS, and compares the same speaker's robust distribution. It remains empty with fewer than three valid turns.
- Acoustic fields must not be used to infer emotion, depression, anxiety, risk, diagnosis, tremor, or treatment effect.

## Shutdown

Stop the backend process after the test. Process termination releases the model references; verify VRAM release with `nvidia-smi`. Do not delete the Hugging Face model download cache after a normal test because the next run should reuse it. Idle model unloading is intentionally outside this PR.
