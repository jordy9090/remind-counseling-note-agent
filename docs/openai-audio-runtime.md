# Hosted audio runtime

The owner authorized switching the production audio path to OpenAI on 2026-11-04. The local/KoreaIDC benchmark remains historical evidence; it does not qualify this hosted provider.

## Configuration

Set server-only `ENABLE_AUDIO_TRANSCRIPTION=1`, `AUDIO_TRANSCRIPTION_STUB=0`, `AUDIO_TRANSCRIPTION_ENGINE=openai`, `OPENAI_AUDIO_MODEL=gpt-4o-transcribe-diarize`, and `OPENAI_API_KEY`. Leave `VITE_AUDIO_API_BASE_URL` unset for same-origin Vercel routing. Never expose the API key through a `VITE_` variable. The existing document-extraction function also serves the three audio routes (300-second function limit); authentication remains mandatory.

The current official speaker-label API uses `gpt-4o-transcribe-diarize`. OpenAI marks it deprecated with shutdown on **2027-02-26**. Replace this adapter before that date; changing only the model to `gpt-transcribe` does not preserve diarization. Official pricing at implementation is approximately $0.006/minute, excluding references, retries, and downstream summaries. See [speech guide](https://developers.openai.com/api/docs/guides/speech-to-text) and [pricing](https://developers.openai.com/api/docs/pricing).

## Data path and limits

1. The counselor explicitly accepts raw-audio transmission to OpenAI. The browser decodes a maximum 60-minute recording at 16 kHz and mixes channels to mono.
2. Contiguous chunks of at most 60 seconds end at a quiet 100 ms window when possible. No sample is discarded or processed twice. Turns near cuts require review; quiet-point selection cannot guarantee an actual silence or a complete sentence.
3. Each PCM WAV is below 2 MB, with up to four 2–4 second inline speaker references. This stays below Vercel's 4.5 MB request limit without persistent object storage. The server rejects other PCM formats, oversized chunks and remote reference URLs.
4. OpenAI returns text, timestamps and anonymous speakers. References anchor IDs across requests when recognized. Unmatched voices retain distinct chunk IDs and review flags; they are never inferred to be counselor/client. Expected speaker count limits reference collection, not the provider's inferred speaker count.
5. Raw provider segments and edited segments stay separate. Midstream failures retain successful segments and mark failed/unprocessed time ranges. Two consecutive failures stop remaining requests. No-speech chunks remain reviewable and do not interrupt later speech. Removing the file stops further chunks; an in-flight request may still finish.
6. The existing editor supports role assignment, text/speaker edits, merge/split and playback. Local PII candidates must be reviewed and confirmed again after edits before corrected text enters the existing summary pipeline.

Application server uploads use the OS temporary directory (`UPLOAD_TMP_DIR` override) and are deleted in route `finally` blocks on success or failure. No raw audio or raw transcript is added to database/object storage by this adapter. Audio and voice references leave the application for OpenAI; provider retention follows the account's OpenAI policy, and deletion of our temp file does not imply provider deletion. The browser retains the source/audio buffers while processing/reviewing; decoded buffers become collectible after processing, and object URLs are revoked on removal/workspace close. Closing the browser loses unpersisted editing state.

Browser decode uses RAM proportional to recording size, even though API requests are bounded. Large multichannel/uncompressed source files can exceed mobile browser memory. The initial release requires a desktop browser; decoding failures must be surfaced. No GPU is used by the application and provider VRAM is unavailable.

## Verification scope

`python -m unittest test_openai_audio test_audio_app_boundary` checks authentication, consent, references, provider failures, raw-text preservation and temp cleanup. `pnpm verify:hosted-audio` checks 60-minute PCM coverage, bounded payloads, speaker anchors and partial failures. Existing editor and deidentification regression scripts still apply. These are offline checks, not claims about Korean recognition accuracy. Actual provider and browser results belong in the release validation ledger.
