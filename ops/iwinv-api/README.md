# Direct iwinv API deployment

Vercel serves only `frontend/dist`. The production browser API origin is
`https://api.remind.ai.kr`; ordinary requests, audio, review, persistence, reads,
and voucher exports share that origin. Supabase authentication remains direct.
No Vercel rewrite or serverless function proxies counseling data. Retired `/api`
paths return 410; clients with an older tab must reload before continuing.

Set the Vercel project Root Directory to `frontend` and disable including files
outside that directory. `frontend/vercel.json` then governs the static deployment;
the root configuration also rejects API paths during the transition. The CLI
ignore file alone is not the Git deployment boundary. Do not switch the shared
project settings until the candidate and iwinv backend are ready for promotion.

## Release prerequisites

- `api.remind.ai.kr` A record points directly to `49.247.174.195`, without a CDN proxy.
- Public TCP 443 and administrator SSH from the authorized `/32` are reachable.
- Provision only the existing OpenAI and CLOVA credentials, Supabase public
  URL/key, detector token/certificate, review signing key, and the current
  production feature settings. Do not upload a development environment file,
  private home directory, cloud administrator credential, or counseling data.
- Keep the existing worker/model, counselor SSH account, and their environments.

## Backend and HTTPS

1. Export the reviewed commit's `backend/app`, `backend/pyproject.toml`, and
   `backend/uv.lock` into `/opt/remind-api/releases/<sha>/backend`. Create a
   separate virtual environment with the locked dependencies; do not change the
   worker or counselor Python environments. Install the Linux PDF libraries and
   Korean fonts required by the existing export tests.
2. Create the dedicated `remind-api` account. Provision `/etc/remind-api/runtime.env`
   with root ownership and mode 0600. Preserve production flags and require real
   user authentication and de-identification review. Set
   `API_CORS_ALLOWED_ORIGINS` to the exact production frontend origins plus the
   specific candidate deployment being tested. Never use a wildcard preview suffix.
3. Point `/opt/remind-api/current` to the candidate release, install the supplied
   systemd unit, and check the loopback API before switching HTTPS. Uvicorn and
   Caddy access logging stay disabled; temporary uploads use the private runtime
   directory and existing success/failure cleanup.
4. Validate the supplied Caddy configuration with the installed Caddy version.
   Preserve the existing worker unit and certificate for rollback. Move that
   same worker to `127.0.0.1:8001`, without changing its model, packages, token,
   or request handling; Caddy terminates its existing pinned TLS endpoint.
   Copy only that certificate/key into the root-owned Caddy directory with
   private-key access restricted to Caddy. The API keeps the existing
   `DEID_SERVICE_URL=https://49.247.174.195` and certificate trust.
5. Start HTTPS on 443, verify the public API certificate without bypassing trust,
   and verify both the browser API and the legacy detector health route.

## Validation and promotion

- Run `frontend/scripts/verify-api-origin.mjs`, affected frontend workflows,
  the production frontend build, and `backend/test_api_host_boundary.py` with
  the existing review/auth/storage/export regressions.
- Review the final sensitive diff once. Verify a Vercel candidate contains no
  serverless functions and returns 410 for retired API paths.
- Use one synthetic browser run to cover WAV and document upload, real CLOVA,
  Qwen review, real summary generation, drafts, persistence, reload, and export.
  Record request origins and operation statuses, never credentials or bodies.
  Assert no counseling request/response reaches any Vercel frontend origin.
- Check guest access, owner isolation, missing/modified review receipts, and a
  detector failure without an external-AI fallback. Clean synthetic rows/users
  once and verify zero remaining rows.
- Promote only the tested commit/build. Run one production smoke and record
  the backend release, frontend deployment, DNS/TLS checks, and rollback target.

## Rollback

Keep the previous healthy Vercel deployment and worker configuration. A backend
rollback changes the `current` symlink to a validated previous API release and
restarts only `remind-api`. Restoring the previous Vercel frontend also restores
its previous data path through Vercel, so disclose that consequence before using
that fallback; do not describe it as retaining the direct-data-path guarantee.
No database migration, retention-policy change, or existing-data deletion is
part of this deployment.
