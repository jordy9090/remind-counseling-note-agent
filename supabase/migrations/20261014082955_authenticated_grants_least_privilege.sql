-- 2026-10-14: narrow authenticated table privileges.
-- Read/write permissions and existing RLS policies are intentionally unchanged.
-- Ordinary counselor requests need SELECT/INSERT/UPDATE/DELETE, not these DDL-like rights.
--
-- Exact rollback (only for these three tables):
-- GRANT TRUNCATE, REFERENCES, TRIGGER ON
--   public.document_exports, public.transcript_turns, public.transcript_windows
-- TO authenticated;
--
-- No table data, defaults, RLS, or deployed application settings are modified.

REVOKE TRUNCATE, REFERENCES, TRIGGER
  ON public.document_exports,
     public.transcript_turns,
     public.transcript_windows
  FROM authenticated;

DO $verify_narrow_authenticated_grants$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.role_table_grants
    WHERE table_schema = 'public'
      AND grantee = 'authenticated'
      AND table_name IN ('document_exports', 'transcript_turns', 'transcript_windows')
      AND privilege_type IN ('TRUNCATE', 'REFERENCES', 'TRIGGER')
  ) THEN
    RAISE EXCEPTION 'Least-privilege migration failed: excess authenticated grants remain';
  END IF;

  IF (
    SELECT count(*)
    FROM information_schema.role_table_grants
    WHERE table_schema = 'public'
      AND grantee = 'authenticated'
      AND table_name IN ('document_exports', 'transcript_turns', 'transcript_windows')
      AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
  ) <> 12 THEN
    RAISE EXCEPTION 'Least-privilege migration failed: ordinary CRUD permissions changed';
  END IF;
END
$verify_narrow_authenticated_grants$;
