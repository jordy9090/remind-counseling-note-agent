# AI Core Reliability Benchmark

This benchmark uses only synthetic Korean counseling material. It does not call an external model and must not be interpreted as a clinical quality evaluation.

## Long-input baseline

Command:

```bash
cd backend
PYTHONPATH=. ../.venv-dev/bin/python -m benchmarks.long_transcript_benchmark --pretty
```

The generator produces memo, speaker-labelled, and timestamped variants at approximately 300 Korean characters per minute. Token counts below were measured locally with `tiktoken`; preprocessing latency covers generation, token counting, and deterministic chunking only.

| Duration | Characters | Measured tokens | Chunks | Estimated core calls | Offline latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10 min | 3,015–3,045 | 1,745–1,798 | 1 | 2 | 0 ms |
| 20 min | 6,000–6,017 | 3,465–3,544 | 1 | 2 | 1 ms |
| 50 min | 15,005–15,015 | 8,615–8,850 | 2 | 3 | 8–10 ms |
| 60 min | 18,015–18,041 | 10,345–10,616 | 2 | 3 | 11–15 ms |

All 12 fixtures preserved the synthetic early, middle, and late event markers. Position-preserving references use `transcript_text.chars_START_END` or `counselor_memo.chars_START_END`. A chunk failure aborts the full summary instead of returning a partial result.

## Limits and interpretation

- Public Quick Summary remains capped at 20,000 characters and does not expand into multiple model calls.
- Authenticated Full Summary accepts at most 96,000 sanitized input characters, eight chunks, and ten core model calls.
- These figures are measured for deterministic preprocessing. Model latency, provider usage tokens, and monetary cost remain unknown because the approved paid-API budget was USD 0.
- The mock-backed regression suite verifies orchestration, source coverage, speaker-field separation, and failure semantics. A counselor must still review clinical quality from a real model before release.
