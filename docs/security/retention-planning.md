# Offline retention planning

`backend/app/services/retention_planning.py` evaluates explicit policy decisions against artifact metadata. It produces a dry-run plan only. It has no database client, network calls, scheduler, deletion executor, environment-policy reader, or application endpoint. Its output always contains `execution_performed: false` and `erasure_verified: false`.

No retention period is configured by this component. Source storage defaults, deployed save flags, masking, confirmation status, provider marketing, and the existence of a backup do not establish a retention basis. The owner must first establish the applicable artifact category, purpose, institution/program scope, policy version, basis, trigger, and decision evidence. See the [data inventory](data-inventory-and-access-matrix.md) and [open policy questions](legal-ethics-requirements-and-open-questions.md). This document contains no private research excerpts or institution-specific legal conclusions.

## Inputs and results

The public Python entry points are `PlanningRequest.model_validate(...)` and `plan_retention(request)`. `PlanningRequest.model_json_schema()` exposes the complete input contract. Unknown fields and unsupported period units are rejected. Use opaque references containing only ASCII letters, digits, underscore, period, colon, or hyphen, up to 128 characters. Do not place counseling text, names, filenames, tokens, prompts, or provider responses in this metadata. Metadata references may still be personal data; protect both the input and the plan.

Each request has an explicit timezone-aware `as_of`, `schema_version: 1`, a policy catalog, and artifacts. The planner does not read the clock. Identical valid input produces identical output and never mutates the input.

Each policy includes:

- `policy_id`, `version`, `category`, `purpose_ref`, `scope_ref`, `decision_ref`, and `effective_from`; optional `effective_until` is exclusive.
- `preservation_assessment`: `none_applicable`, `specified`, or `unresolved`. `specified` requires a `preservation` rule; the other values require explicit `null`. `none_applicable` records the supplied decision; the planner cannot verify that decision's legal correctness.
- Explicit `deletion`, which is a deadline rule or `null` when no operational threshold is approved. No threshold is inferred from preservation.
- Each deadline rule supplies its own `basis_ref`, event-name `trigger`, and `period`. Legal preservation and operational deletion can use different triggers and bases.

An artifact supplies its exact category/purpose/scope, explicit `policy_refs`, timestamped `events`, `hold_review`, `holds`, `copy_inventory_complete`, and `copies`. The planner requires one explicitly selected policy version whose applicability matches. Multiple selected policies are a conflict requiring an owner-resolved policy; the planner never picks the longest duration. Missing policies, expired versions, missing triggers, future observations, incomplete hold review, incomplete inventories, and unknown copy state block eligibility.

An active hold requires `hold_ref`, `basis_ref`, and `started_at`. A release requires both `released_at` and `release_evidence_ref`. A planned future release is not treated as an actual release. A hold is not itself a legal basis; the referenced decision must establish that basis.

| Status | Meaning |
| --- | --- |
| `unknown` | Required policy, applicability, time, hold, or inventory evidence is missing or unresolved. |
| `conflict` | Multiple policies were selected, or preservation extends past the operational deletion threshold. No duration wins automatically, even when both dates have passed. |
| `protected` | Complete metadata establishes an active hold, an unexpired preservation limit, or an operational threshold that has not been reached. |
| `eligible` | The supplied metadata passes these checks and the explicit deletion threshold has been reached. This is a planning candidate, not authorization, execution, or a compliance certification. |

Precedence is conflict, then unknown, then protected, then eligible. Reasons retain the unresolved conditions. `preserve_until` and `delete_after` remain separate output fields. Time comparisons are exact: a threshold is reached at equality. This planner uses `delete_after` as the approved operational eligibility threshold; it does not determine whether earlier deletion was permissible or whether a statutory response deadline was met.

## Calendar rules

All trigger, observation, hold, policy, and evaluation timestamps must include a UTC offset and are normalized to UTC before comparison, including Python `ZoneInfo` inputs during repeated daylight-saving hours. Date-only inputs and naive timestamps are rejected. The responsible owner must establish the intended instant and timezone for a service date; the planner does not infer end-of-day semantics.

- `elapsed_days` adds exact 24-hour days in UTC and accepts no calendar options.
- `calendar_months` and `calendar_years` require an explicit `timezone` (`UTC`, a fixed offset such as `UTC+09:00`, or an available IANA zone) and an explicit `overflow`: `month_end` clamps an unavailable day to the target month's last day; `next_month_start` moves it to the first day of the following month. There is no implicit leap-day choice.
- Calendar periods retain local wall-clock time and account for timezone offset changes. An ambiguous or nonexistent daylight-saving deadline produces `unknown`; no offset is guessed.
- Nonnegative integer amounts up to 10,000 are supported. Out-of-range computed dates produce `unknown`. Business-day calendars, combinations of units, date-only rules, and recurrence schedules are unsupported.

Fixed-offset zones use the standard library and never infer daylight-saving rules. The runtime must have timezone data for any requested IANA zone. An unavailable named zone is rejected as unsupported configuration rather than approximated with a fixed offset. Changes to installed timezone data can change a future calendar calculation; preserve the reviewed input/output and runtime provenance when adopting a decision. Synthetic timezone data in tests verifies offset changes, gaps, and overlaps without installing a timezone package.

## Copies and truthful completion reporting

Copy locations are `primary`, `derivative`, `cache`, `export`, `provider`, and `backup`. States are `present`, `deletion_pending`, `deletion_confirmed`, and `unknown`, each with `observed_at`. `deletion_confirmed` additionally requires an `evidence_ref`; this is caller-reported evidence, not verification performed by the planner.

The output separates `local_copies`, `provider_copies`, and `backup_copies`. A complete supplied inventory with all local copies reportedly removed yields `local_copies: reported_deleted`; provider/backup entries can still be `pending`, `remaining`, or `unknown`. `not_in_inventory` means only that a complete caller-supplied inventory lists no copies at that location. It is not an independent assertion of zero retained copies. Incomplete inventory yields `unknown`.

Eligible local copies receive `plan_local_deletion`; provider copies receive `provider_followup`; backups receive `backup_followup`. These are planning labels only. Already reported deletion retains its evidence reference. No item, including an expired backup, is automatically marked erased. An executor, if separately authorized later, must revalidate policies, holds, current ownership, complete derivative scope, source revisions, retries, and restored copies before acting. This planner contains no protection against concurrent state changes after its metadata snapshot.

## Offline CLI

From `backend`, run:

```powershell
.\.venv\Scripts\python.exe -m app.services.retention_planning .\metadata-only-plan-input.json
```

The command reads one UTF-8 JSON file and prints JSON to standard output. It does not create or modify files. Exit code `0` means valid planning input, including valid plans with `unknown` or `conflict` results; exit code `2` means invalid or unreadable input. Error output intentionally omits validation values and file paths, so accidentally supplied content is not echoed. The Python validation API is for trusted callers; do not log raw Pydantic validation errors from private inputs.

A minimal unconfigured example selects no period:

```json
{
  "schema_version": 1,
  "as_of": "2026-10-14T12:00:00+09:00",
  "policies": [],
  "artifacts": [{
    "artifact_ref": "synthetic-artifact",
    "category": "cache",
    "purpose_ref": "synthetic-purpose",
    "scope_ref": "synthetic-scope",
    "policy_refs": [],
    "events": {},
    "hold_review": "unknown",
    "holds": [],
    "copy_inventory_complete": false,
    "copies": []
  }]
}
```

It reports `unknown` with missing policy, hold review, and inventory reasons. To obtain useful eligibility decisions, supply the independently approved policy and verified artifact/copy metadata; do not copy synthetic test durations into Production policy.

Focused verification: `python -m unittest test_retention_planning -v`. Tests use synthetic metadata and temporary local files only. They cover timezone equivalence, calendar/leap/DST boundaries, conflicting policies, preservation holds, incomplete evidence, separate provider/backup state, and CLI input/error privacy. They do not establish legal applicability, inspect deployed storage, or verify physical deletion.
