# Case processing authorization: API and database boundaries

Status: implementation for review, not deployed. Real-data launch remains HOLD.

## Completion criteria and boundary

This increment requires a current, operator-issued permission before PoC detection,
reviewed generation/recomposition/supervision/memory, audio transcription and the
affected draft/generated-note/confirmation/supervision saves. Preserve existing
JWT/RLS, masking receipts, source-deletion and beta lifecycle controls. Use only
synthetic fixtures and mocks; finish the relevant CI and update the release ledger.

The authenticated RPC returns only a Boolean. Its non-exposed SECURITY DEFINER
helper checks the caller's auth.uid(), existing beta enrollment, receipt, policy,
purpose/provider, start/end timestamps, withdrawal and erasure. It reads current
auth.users.raw_app_meta_data on every call; JWT app metadata and user_metadata do
not grant permission. No service-role fallback is used by the API.

The existing beta schema remains inaccessible. A new private schema exposes only
this narrow helper to authenticated users through a SECURITY INVOKER public wrapper.
Anonymous and service-role execution are not granted. No records are backfilled.

## Why an operator-managed registry

The first cohort is small and already has explicit beta enrollment and a retained
institutional consent receipt. Reusing administrator-only Auth metadata avoids a
second consent collection UI or copying signed forms into application storage.
Supabase documents administrator-only app metadata updates; the API never accepts
an authorization object from the browser. This is a bounded pilot design, not a
large-scale consent-management platform.

References: [Supabase user management](https://supabase.com/docs/guides/auth/managing-user-data),
[administrator user updates](https://supabase.com/docs/reference/javascript/auth-admin-updateuserbyid).
Changelog reviewed on 2026-11-22; no Auth/RLS dependency upgrade is required.

## Configuration and permission contract

`PROCESSING_AUTHORIZATION_POLICY` defaults to empty. PoC processing fails closed
until an approved policy version is configured. This is intentional: deploying
the API alone does not enable real-data processing. Non-PoC synthetic compatibility
is unchanged; never use POC_MODE=0 to bypass a real-data launch gate.

The database additionally requires the same version in the private singleton
`processing_authorization.policy` table. The migration leaves it empty. Only an
authorized database operator may set it after approval; browser parameters, JWT
metadata and request settings cannot enable it. DB enforcement applies regardless
of API POC_MODE. Deploying this migration alone therefore denies application
access to counseling rows, including existing unregistered cases.

After institutional/legal and vendor review, an authorized operator may register
only the documented scope under `raw_app_meta_data.remind_processing_authorizations`.
This task does not register any user, change metadata or configure Production.
Each object is keyed by the exact registered `beta_rm_<receipt UUID>` case ID:

```json
{
  "status": "active",
  "policy_version": "<approved version matching the API>",
  "receipt": "<existing enrollment receipt UUID>",
  "not_before": 0,
  "expires_at": 0,
  "permissions": {
    "detection": ["iwinv"],
    "generate": ["openai"],
    "recompose": ["openai"],
    "storage": ["supabase"]
  }
}
```

The timestamps above are deliberately invalid placeholders, expressed as numeric
Unix seconds. Start must not precede the signed enrollment; expiry cannot exceed
its end. Missing purposes/providers are denied. `supervision`, `memory` and `audio`
require separately authorized entries; do not copy the example as a consent.
Audio uses the configured engine name and is omitted from the recommended initial
text-only cohort. Countries/contracts are represented by the reviewed policy
version; a provider name alone does not attest country or retention compliance.
Keep the map small (recommended maximum 16 cases per pilot account): Auth metadata
may also appear in the user's token. Store opaque IDs only, never client names,
counseling content, signatures, documents or credentials.

Removing the entry or changing status revokes future checks without waiting for a
JWT refresh. Existing beta withdrawal/expiry also denies processing independently
of the metadata entry. Both registries must be maintained by the enrollment runbook;
the metadata record does not replace the signed institutional evidence.

## Request behavior

- Preparation validates permission before reading prior history. Detection and
  polling recheck permission before the service call and before returning results.
- A masking receipt remains bound to the actor/purpose/body and cannot override a
  revoked grant. Each generation attempt, model-client construction and embedding
  egress rechecks the current case decision. Result return is rechecked too.
- Draft, generated-note, confirmation and supervision persistence check `storage`
  permission. Audio checks before app temporary-file persistence, immediately
  before transcription, and before result return; cleanup runs on rejection.
- Audio chunks include case_id and their resumable checkpoint key includes the
  case. A checkbox only supplies the additional immediate provider acknowledgement.
  Case/session changes revoke the upload URLs and remove pending/completed audio
  materials. Async state updates check URL liveness when applied; returning to an
  earlier case cannot restore a stale transcript or checkpoint for retry.
- PoC Quick input has no case binding and is therefore denied. The initial cohort
  must use the case-bound session flow; do not advertise unscoped Quick as enabled.
- Permission failures return fixed Korean 401/403/503 messages. No policy object,
  upstream error body, token or counseling content is logged or returned.

## Limits and subsequent gates

This increment is not a complete system-wide consent enforcement claim. The fresh
RPC and a later external request/write are separate transactions: withdrawal cannot
recall an already transmitted request, and there is a narrow check-to-use interval.
It blocks subsequent observed checks, retries and result return, not physical undo.

All 12 counseling tables now have an additional restrictive policy requiring the
current `storage/supabase` grant for SELECT/INSERT/UPDATE/DELETE. This includes
profiles inside cases, drafts, exports, transcripts, notes/evidence, memories,
retrieval records and vouchers. Existing owner and parent checks still apply.
Direct Data API access and invoker retrieval RPCs cannot bypass the gate. The
definer-backed history, restore and source-deletion RPCs check it too, including
their private entry points; former internal bodies have no application EXECUTE
grant. Anonymous/service-role table access, TRUNCATE and case retrieval RPC access
are revoked. Shared reference KB reads contain no counseling rows and retain their
existing read-only access.

Writable transactions hold shared locks on policy, caller Auth metadata and the
case enrollment until transaction end. A revocation that commits first makes a
waiting write fail; a write that acquired authorization first finishes before the
revocation commits. Read-only Data API GET/HEAD and STABLE RPC transactions cannot
take row locks and instead evaluate the current read snapshot. Neither mode
recalls a completed result. Clock expiry is checked at each operation, not a
promise to undo writes authorized before time elapsed.

An INSERT trigger acquires permission locks before the existing enrollment/parent
triggers. Operator transactions combining changes must use the same order: policy,
Auth metadata, enrollment, then counseling rows. The concurrency fixture holds an
Auth update, observes an INSERT waiting, then updates enrollment before commit.
Read-only behavior follows the [PostgREST transaction contract](https://docs.postgrest.org/en/stable/references/transactions.html).

The DB grant covers storage/access, not the downstream purpose of exported text.
Per-provider AI egress still uses the API checks. Independent HTTP persistence
requests remain independent transactions; denial of a later step does not undo a
prior authorized write. Superusers, owners and administrators who can change
grants or Auth metadata remain trusted operators. Operator-only beta erasure and
retention jobs intentionally work after application permission expires or is
withdrawn. Users with withdrawn permissions must request erasure through that
operator path; they cannot restore or manipulate protected rows themselves.

Remaining launch gates also include lawful basis and agreements, exact provider
countries/retention and commercial hosting terms, protected statutory access logs,
administrator MFA/key custody, and backup/restore deletion reconciliation.

## Validation and rollback

Run `python tests/run_poc_review.py` from backend with the locked environment. The
runner removes credentials/dotenv access and blocks network/process I/O. The new
suite tests API denial, transport metadata, A/B scope, stale approvals, retries,
in-flight withdrawal, result suppression, and temporary-file cleanup. Existing
masking/history/storage fixtures explicitly assume a valid permission decision;
the new suite and real SQL separately verify that decision boundary.

`python backend/tests/run_poc_database.py --run-disposable` applies all source
migrations and tests actual PostgreSQL role/grant/lifecycle behavior in its own
network-isolated database. It rolls back fixtures and verifies zero remaining rows.
Local Windows has no Docker, so actual SQL execution is a required CI gate.

Candidate `30578c67bde9c59c8e7174e21bbd429bb7b0ae21` passed Product CI,
160 synthetic security tests, 68 offline PoC tests, and the disposable PostgreSQL
contracts on 2026-11-22. The database runner reported zero remaining synthetic
rows and removed its owned container/tmpfs. The release checklist links the exact
runs and records the independent-review fallback when the managed scanner could
not start. Documentation-only follow-up commits reuse this tested code.

Before eventual deployment, validate the institution-approved configuration on a
non-production synthetic environment. Preserve the existing healthy release.
To roll back, revert the API/frontend to that release first, then drop the public
wrapper, private helper and new schema if authorized. Never drop beta_retention
or remove enrollment evidence as rollback. No operational rollback is needed for
this unmerged, undeployed PR.

The DB extension requires an explicit reviewed rollback migration before eventual
deployment: remove its restrictive policies/gated wrappers, restore prior function
names and exact grants, then remove the private policy registry. Doing so reopens
the direct-DB permission gap, so keep real-data processing disabled during rollback.
Do not drop counseling or enrollment data to roll back authorization.
