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

## Interview-derived quality gates

The synthetic checks translate the recurring concerns recorded in the 송은영 counselor and 노은정 center-director interviews into regression contracts. They do not use interview transcripts or real counseling data.

| Concern | Offline evidence | Status |
| --- | --- | --- |
| Client/counselor confusion | Neutral speaker-labelled fixture requires the counselor intervention to come from a counselor turn, not from a client-focused memo | Passed |
| Invented intervention or plan | A no-plan fixture rejects the previous hard-coded anxiety, intervention, and next-session claims and returns `[상담사 확인 필요]` | Passed |
| Documented plan omission | A plan present only in the transcript is retained with a `transcript_text` reference | Passed |
| Long-input omission | 10/20/50/60-minute fixtures retain early, middle, and late markers across all three input formats | Passed at deterministic chunk/evidence layer |
| Real-model clinical fidelity | Requires an approved provider call and counselor review | Blocked: paid API budget is USD 0 |

## Limits and interpretation

- Public Quick Summary remains capped at 20,000 characters and 20,000 tokenizer-estimated input tokens, and does not expand into multiple model calls.
- Authenticated Full Summary accepts at most 96,000 sanitized input characters and tokenizer-estimated tokens, eight chunks, and ten core model calls.
- These figures are measured for deterministic preprocessing. Model latency, provider usage tokens, and monetary cost remain unknown because the approved paid-API budget was USD 0.
- The mock-backed regression suite verifies orchestration, source coverage, speaker-field separation, and failure semantics. A counselor must still review clinical quality from a real model before release.
- Quick-versus-Full clinical quality is therefore not scored. The table below compares only the verified call topology and deterministic evidence behavior; it must not be presented as a real-model quality win.

## Call and cost comparison

| Flow | Normal generation calls | Maximum guarded calls | Raw current-session text transmissions | Cost status |
| --- | ---: | ---: | ---: | --- |
| Legacy Quick at base `ba46cce` | 1 | 1 | 1 | Not measured |
| Improved Quick | 2 (structure + summary) | 3 including one repair | 1; the summary reuses structured evidence | Estimated only when provider usage and known/configured rates exist |
| Full, short input | 3 (structure + summary + provider verification) | 16 request-wide | 2 in the existing full-quality path | Estimated only when provider usage and known/configured rates exist |
| Full, 60-minute synthetic input | 4 (two chunk structures + summary + provider verification) | 16 request-wide | Each raw chunk once; final summary uses chunk evidence | Model usage unknown because no paid call ran |

The improved Quick path deliberately spends one additional call versus the legacy one-shot prompt to share field separation and evidence handling with Full Summary. It avoids sending the raw text twice. Telemetry uses provider-reported input, output, and cached-input tokens; missing usage remains `unknown`, never `0`. The built-in standard GPT-5.4 estimate uses the official 2026-10-19 rates of $2.50/M input, $0.25/M cached input, and $15/M output from the [OpenAI model page](https://developers.openai.com/api/docs/models/gpt-5.4). This sprint made no paid calls, so there is no actual billed-cost result.
