# Single-call session-summary Skill

This candidate implements the mentoring proposal as executable product code: a
task-specific `SKILL.md` is loaded only when session summarization is requested,
then one structured model call creates the existing seven summary sections. It
does not add an autonomous agent, tool-selection loop or runtime skill registry.
The Skill format follows the [Agent Skills specification](https://agentskills.io/specification).

## Completion criteria and boundary

- Load the real Skill instructions at execution time, rather than copying them into another prompt.
- Replace only the extraction-and-summary core with one structured invocation.
- Reuse section schemas, source-reference normalization, reflection guards and prose checks.
- Measure the candidate against the unchanged baseline using identical sanitized synthetic input.
- Leave public routes, upstream de-identification, verification, insights, storage and deployment unchanged.

Implementation: `backend/app/skills/session-summary/SKILL.md` and
`backend/app/services/summary_skill.py`. The callable is:

```python
from app.services.summary_skill import run_summary_skill

# `sanitized` must be the same already-deidentified SanitizedInput used by
# the baseline. Authorize external model use separately before calling.
result = run_summary_skill(sanitized)
draft = result.summary  # Existing SessionSummaryDraft, with metadata filled locally.
```

The provider receives current-session sources once, their valid reference IDs,
the selected Skill body and the seven-section schema. Session metadata and
sensitive-candidate excerpts are not sent. Missing configuration, explicit stub
mode, provider/parse errors and unusable prose fail without mock substitution,
automatic retries or a repair call. Provider-reported usage is retained when
available; missing usage is not converted to zero.

The Skill expresses a small set of domain distinctions: speaker and recipient,
reported event versus interpretation, corrected statement, performed intervention
versus proposed action, and proposed versus agreed plan. These are generation
instructions, not a formal ontology or independently validated factual checker.

## Offline validation

Use the existing backend Python environment from the repository root:

```powershell
& '<existing-python.exe>' -I research/session_summary_skill/validate_offline.py --mode tests --output '<results-directory>'
& '<existing-python.exe>' -I research/session_summary_skill/validate_offline.py --mode compare --baseline-response '<synthetic-live-response.json>' --output '<results-directory>'
```

The runner disables network and `.env` loading before application imports. Tests
use synthetic fixtures and mocked providers. Comparison replays a previously
captured synthetic response through the real baseline core and candidate. This
checks code contracts and request size; it does not generate new output or score
the candidate's factual accuracy. Token estimates require an already cached
`o200k_base` vocabulary. Missing cache is reported as BLOCKED without downloads.

## Recorded result, 2026-10-25

Base commit: `e95458a634765eb40843245ce27ae81b736b003f`.
Environment: local, network disabled; no deployment for this candidate.
Existing Production reference `dpl_45bRcgbAYJrK9Htp2wJ26zdaCVWp` was not accessed or changed.

| Check | Result | Timestamp (UTC) |
|---|---|---|
| `validate_offline.py --mode tests` | PASS: 37 tests, including 16 new Skill contracts and 21 existing quality/reference/model-setting checks | 2026-10-25 14:50:46 |
| `validate_offline.py --mode compare` with the existing 74-turn, 10,532-character synthetic input | PASS for replay: baseline core 2 calls, Skill core 1 | 2026-10-25 14:50:08 |
| Request text plus serialized schema size | 42,565 → 15,732 characters, about 63.0% smaller | Same comparison |
| Local token estimate | BLOCKED: tokenizer vocabulary not cached; no dependency or data download | Same comparison |
| `python -X utf8 .../skill-creator/scripts/quick_validate.py backend/app/skills/session-summary` | PASS; initial Windows default-code-page attempt failed, UTF-8 invocation fixed the validator environment | 2026-10-25 |
| Python AST parse of the three new Python files | PASS | 2026-10-25 |
| Focused independent source/privacy review | No actionable defect found; unchanged production callers confirmed | 2026-10-25 |
| Fresh model quality, generation latency, billed tokens and cost | NOT RUN | — |

The 63% figure is **characters in core request text/schema**, not tokens or total
product cost. Both comparison arms exclude upstream entity extraction, semantic
verification, relational insights and grounded-document calls. The live quick
pipeline includes more than the two core calls. Its cost must not be compared to
the summary-only candidate as though the outputs and safeguards were equivalent.
Valid source IDs and prose checks do not prove semantic grounding. The candidate
still requires counselor review and has not been connected to the demo route.

No accounts, database rows or server processes were created. New model calls: 0.
No application configuration or existing worker changes were modified. Detailed
`tests.json`, `tests.txt` and `comparison.json` are retained in the task's local
`docs/validation/summary-skill-20261025` artifact directory.

## Proposed authorized live comparison

Reuse the same 74-turn synthetic case and the identical already-deidentified
input for both arms. Fix the model to `gpt-5.4-2026-03-05`, reasoning to `low`, and
all other provider parameters equally. Plan three calls: baseline extraction,
baseline summary, and candidate Skill. Abort rather than issue an unbudgeted
repair/retry. Keep verification and insights outside both arms for this initial
core experiment. Judge fabrication, speaker mistakes, important omissions and
necessary counselor edits alongside time and actual reported usage.

For planning only, 60,000 total input tokens plus 20,000 total output/reasoning
tokens across the three calls would cost about **US$0.45** at standard GPT-5.4
rates of US$2.50/1M input and US$15/1M output. This is a budget assumption, not
measured consumption, a spending cap, or a guaranteed bill. Pricing checked on
2026-10-25 against the [official model page](https://developers.openai.com/api/docs/models/gpt-5.4).
No live comparison was authorized or executed by this change.
