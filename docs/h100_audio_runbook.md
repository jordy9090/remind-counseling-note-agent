# H100 Audio STT Runbook

This runbook is for enabling the real faster-whisper audio transcription runtime on a research H100 host. Do not expose the H100 backend publicly.

## Runtime Modes

- `AUDIO_TRANSCRIPTION_STUB=1`: demo stub mode. It returns a sample transcript and does not import faster-whisper, pyannote, or torch.
- `AUDIO_TRANSCRIPTION_STUB=0` and `ENABLE_AUDIO_TRANSCRIPTION=1`: real faster-whisper mode.
- Both disabled: `/api/audio/transcribe` returns 503 and `/api/audio/capabilities` reports `runtime_mode: disabled`.

## Install Optional Audio Dependencies

Core backend CI does not install GPU/STT dependencies. On the H100 host only:

```bash
cd backend
uv sync --extra audio-stt --extra audio-diarization
```

Do not commit model weights, Hugging Face tokens, CUDA cache directories, or generated transcripts.

If speaker diarization is enabled, provide a Hugging Face token through the host environment only:

```bash
export HF_TOKEN=<hugging-face-token-with-model-access>
export ENABLE_AUDIO_DIARIZATION=1
```

## Run Real STT On One Worker

Use one Uvicorn worker so the process-local Whisper model cache is loaded once per backend process. Do not use `--reload` for the GPU run; autoreload can restart the process and repeatedly reload the model.

```bash
cd backend
CUDA_VISIBLE_DEVICES=<assigned_gpu> \
ENABLE_AUDIO_TRANSCRIPTION=1 \
AUDIO_TRANSCRIPTION_STUB=0 \
ENABLE_AUDIO_DIARIZATION=1 \
WHISPER_DEVICE=cuda \
WHISPER_COMPUTE_TYPE=float16 \
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1
```

Use `--reload` only for CPU/dev code iteration when real GPU STT is off.

## Local Browser Verification Through SSH Tunnel

Keep the research backend bound to localhost and forward it to your local machine:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<research-server>
```

Run the frontend locally and point it at the tunnel:

```bash
cd frontend
VITE_API_BASE_URL=http://localhost:8000 pnpm dev
```

Then verify:

```bash
curl http://localhost:8000/api/audio/capabilities
```

Expected real mode shape:

```json
{
  "runtime_mode": "real",
  "transcription": { "available": true }
}
```

If `transcription.available` is false, check optional dependency installation, CUDA visibility, and model download/cache permissions on the H100 host. Do not include raw exception traces, file paths, tokens, or transcript contents in user-facing responses.

## Acoustic Observation Definitions

- `pause_before_seconds` is calculated from the end time of the immediately preceding transcript segment in chronological order. Overlapping turns produce `0`, and another speaker's turn is not counted as silence.
- `speech_rate_wps` is words per second for the segment text divided by segment duration. For Korean text without spaces, the fallback approximation is visible characters divided by 3, then divided by duration.
- `speech_rate_level` is relative to the same speaker's median rate and is left empty when there are fewer than three comparable samples.
- `volume_level` is emitted only when a runtime supplies normalized speaker-relative loudness. The faster-whisper adapter does not infer volume by itself.
- The audio workflow must not infer emotion, depression, anxiety, risk level, diagnosis, or treatment effect from acoustic observations.

If pyannote is unavailable, the token is missing, model access has not been accepted, model loading fails, or inference fails, transcription still succeeds. In that fallback path all segments are returned as `speaker_1`, `diarization_status` is `fallback`, and only a safe Korean warning is returned.
