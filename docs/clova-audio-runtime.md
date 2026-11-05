# CLOVA Speech beta runtime

The owner selected CLOVA Speech on 2026-11-04, superseding the brief OpenAI beta release. This document describes the adapter and release gates, not a claim that live CLOVA validation is complete. The OpenAI provider is not an automatic fallback. Existing session-summary models and PR #72 behavior are unchanged.

## Server configuration

Set `ENABLE_AUDIO_TRANSCRIPTION=1`, `AUDIO_TRANSCRIPTION_STUB=0`, `AUDIO_TRANSCRIPTION_ENGINE=clova`, `CLOVA_SPEECH_INVOKE_URL`, and `CLOVA_SPEECH_SECRET_KEY`. Obtain the last two from the **long-form** domain builder's Settings / Integration information. Store both in Vercel server-only Secret variables, never under a `VITE_` prefix or in Git. Leave `VITE_AUDIO_API_BASE_URL` unset for same-origin authenticated routing. Missing credentials disable the advertised capability and return 503 without calling another provider.

`CLOVA_SPEECH_KEYWORDS` optionally accepts up to 100 comma-separated words (80 characters each), at conservative weight 1. Leave it empty for an unboosted comparison; use only verified vocabulary. Do not commit real names or institutions. Keyword boosting changes recognition probabilities and does not guarantee correct names.

The browser consent explicitly names CLOVA. Every hosted request includes that provider identity, so a stale consent or server configuration cannot silently send audio to another company. The legacy OpenAI adapter remains only for explicit developer regression/reference use; the product client rejects an OpenAI capability.

## Bounded audio and speaker continuity

- The browser decodes to 16 kHz mono PCM without a total-duration cutoff and sends contiguous chunks of at most 60 seconds and under 2 MB. Hosted capabilities report `max_duration_seconds=null`; the per-request bound is unchanged. Source samples are neither skipped nor duplicated. Boundary turns remain review candidates. The 500 MB source-file safeguard and browser memory/codec constraints still apply.
- CLOVA requests use Korean `ko-KR`, `completion=sync`, word alignment, diarization with minimum 1 and maximum `expected_speakers` (default 2), and `resultToObs=false`. A maximum allows one-speaker chunks; it does not force counselor/client roles.
- CLOVA does not document known-speaker reference parameters. Instead, the adapter prepends up to four previously recognized 2–4 second isolated voice clips with 0.5-second separators. These clips remain in memory and are part of billable audio. This is application-level matching, not a CLOVA speaker-enrollment feature.
- A reference establishes identity only if one provider label dominates at least 85% of its covered duration, covers at least 40% of the reference (and 0.5 seconds), and maps uniquely across references. Provider label order never establishes identity. Unmatched voices retain separate chunk IDs and review flags; reference clips are not collected from uncertain/low-confidence turns.
- Reference speech is discarded by timestamps. If a segment crosses the reference/content boundary, word alignment isolates actual content. Missing alignment produces an explicit incomplete range instead of copying reference text or guessing a sentence. Millisecond provider times become seconds, reference offsets are removed, and the browser adds source-chunk offsets to both turns and words.
- This reference strategy must pass live Korean two-voice verification before release. If the provider cannot reliably anchor speakers, keep those chunks unassigned/reviewable; do not hide the failure or merge by label number. It is not a validated independent diarization model.

## Privacy and failure handling

Only the configured HTTPS `clovaspeech-gw.ncloud.com` domain is accepted; redirects and user-supplied remote reference URLs are rejected. Keys, provider bodies and domain-secret URLs are not returned in errors. Uploads use the OS temp directory (`UPLOAD_TMP_DIR` override); the route deletes them in `finally` on success and failure. The composite reference/audio payload is memory-only. No new raw-audio or raw-transcript database/object-storage retention is introduced. `resultToObs=false` does not establish a provider-wide zero-retention promise: verify the Ncloud account and domain retention settings before sensitive use.

Speaker failure retains recognized text for manual assignment. Low-confidence turns are flagged. No-speech ranges are reviewable and do not stop subsequent speech; failed ranges preserve successful results and two consecutive request failures stop later work. The application makes no semantic rewrite of names, negation, medication or risk statements. Corrected transcript and mandatory local PII review precede the existing summary stage.

Browser decoding still needs RAM proportional to the source recording; use a desktop browser for long audio. Individual API calls have a 240-second timeout inside the existing 300-second Vercel function. Provider latency and VRAM are not predictable from local tests. No A100/GPU is required by the application.

## Verification and release

`python -m unittest test_clova_audio test_openai_audio` covers provider binding, authentication, WAV and reference validation, error redaction, reference label swaps/collisions, boundary clipping, no-speech, raw text and temporary-file cleanup. `pnpm verify:hosted-audio` covers decoding and contiguous PCM coverage beyond 60 minutes, reference matching behavior, word offsets and partial ranges. These offline checks do not demonstrate actual Korean recognition quality.

Signed-in quick summary accepts audio directly using the same transcript editor and mandatory privacy review. Audio edits invalidate its applied text; reapplication replaces the audio contribution. Guests are directed to login for the protected audio API. New client sessions start with uploads and show optional date/time fields after material results or a memo exist; an omitted date stays unset. Quick summary retains its existing 20,000-character input budget; longer transcripts can be used in the regular client-session workflow.

Use the same synthetic recording/reference as the OpenAI benchmark for the live gate. Record CER, speaker attribution, names/domain words, negation/numbers, omissions/repetitions, wall time, billed duration including reference overhead, and counselor correction effort separately. Exercise upload, role assignment, text/speaker edit, merge/split, local PII review and actual-model summary. Log commit, deployment, results and synthetic cleanup in the release ledger; deploy only after these gates pass.

Official references: [upload contract](https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-longsentence-local), [long-form builder credentials](https://guide.ncloud-docs.com/docs/clovaspeech-builder-long), [service limits](https://guide.ncloud-docs.com/docs/clovaspeech-spec).
