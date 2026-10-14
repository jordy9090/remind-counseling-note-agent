-- Non-destructive additional RLS integrity checks for authenticated writes.
-- Existing permissive user_owns_rows policies continue to require auth.uid() = user_id.
-- These RESTRICTIVE policies add AND conditions for new INSERT/UPDATE values only.
-- They do not change SELECT/DELETE, historical records, or service_role bypass.
-- Guest feature, counseling_drafts and retrieval_logs are intentionally excluded pending separate product integration.
-- Rollback: DROP POLICY tenant_parent_write_insert and tenant_parent_write_update on each table below.

CREATE POLICY tenant_parent_write_insert ON public.sessions
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = sessions.case_id AND p.user_id = sessions.user_id));

CREATE POLICY tenant_parent_write_update ON public.sessions
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (true)
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = sessions.case_id AND p.user_id = sessions.user_id));

CREATE POLICY tenant_parent_write_insert ON public.generated_notes
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = generated_notes.case_id AND p.user_id = generated_notes.user_id) AND (generated_notes.session_id IS NULL OR EXISTS (SELECT 1 FROM public.sessions s WHERE s.id = generated_notes.session_id AND s.case_id = generated_notes.case_id AND s.user_id = generated_notes.user_id)));

CREATE POLICY tenant_parent_write_update ON public.generated_notes
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (true)
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = generated_notes.case_id AND p.user_id = generated_notes.user_id) AND (generated_notes.session_id IS NULL OR EXISTS (SELECT 1 FROM public.sessions s WHERE s.id = generated_notes.session_id AND s.case_id = generated_notes.case_id AND s.user_id = generated_notes.user_id)));

CREATE POLICY tenant_parent_write_insert ON public.evidence_items
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = evidence_items.case_id AND p.user_id = evidence_items.user_id) AND (evidence_items.session_id IS NULL OR EXISTS (SELECT 1 FROM public.sessions s WHERE s.id = evidence_items.session_id AND s.case_id = evidence_items.case_id AND s.user_id = evidence_items.user_id)));

CREATE POLICY tenant_parent_write_update ON public.evidence_items
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (true)
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = evidence_items.case_id AND p.user_id = evidence_items.user_id) AND (evidence_items.session_id IS NULL OR EXISTS (SELECT 1 FROM public.sessions s WHERE s.id = evidence_items.session_id AND s.case_id = evidence_items.case_id AND s.user_id = evidence_items.user_id)));

CREATE POLICY tenant_parent_write_insert ON public.verification_reports
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = verification_reports.case_id AND p.user_id = verification_reports.user_id) AND (verification_reports.session_id IS NULL OR EXISTS (SELECT 1 FROM public.sessions s WHERE s.id = verification_reports.session_id AND s.case_id = verification_reports.case_id AND s.user_id = verification_reports.user_id)) AND (verification_reports.note_id IS NULL OR EXISTS (SELECT 1 FROM public.generated_notes n WHERE n.id = verification_reports.note_id AND n.case_id = verification_reports.case_id AND n.user_id = verification_reports.user_id)));

CREATE POLICY tenant_parent_write_update ON public.verification_reports
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (true)
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = verification_reports.case_id AND p.user_id = verification_reports.user_id) AND (verification_reports.session_id IS NULL OR EXISTS (SELECT 1 FROM public.sessions s WHERE s.id = verification_reports.session_id AND s.case_id = verification_reports.case_id AND s.user_id = verification_reports.user_id)) AND (verification_reports.note_id IS NULL OR EXISTS (SELECT 1 FROM public.generated_notes n WHERE n.id = verification_reports.note_id AND n.case_id = verification_reports.case_id AND n.user_id = verification_reports.user_id)));

CREATE POLICY tenant_parent_write_insert ON public.case_memory_chunks
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = case_memory_chunks.case_id AND p.user_id = case_memory_chunks.user_id) AND (case_memory_chunks.session_id IS NULL OR EXISTS (SELECT 1 FROM public.sessions s WHERE s.id = case_memory_chunks.session_id AND s.case_id = case_memory_chunks.case_id AND s.user_id = case_memory_chunks.user_id)) AND (case_memory_chunks.source_note_id IS NULL OR EXISTS (SELECT 1 FROM public.generated_notes n WHERE n.id = case_memory_chunks.source_note_id AND n.case_id = case_memory_chunks.case_id AND n.user_id = case_memory_chunks.user_id)) AND case_memory_chunks.counselor_id = case_memory_chunks.user_id);

CREATE POLICY tenant_parent_write_update ON public.case_memory_chunks
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (true)
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = case_memory_chunks.case_id AND p.user_id = case_memory_chunks.user_id) AND (case_memory_chunks.session_id IS NULL OR EXISTS (SELECT 1 FROM public.sessions s WHERE s.id = case_memory_chunks.session_id AND s.case_id = case_memory_chunks.case_id AND s.user_id = case_memory_chunks.user_id)) AND (case_memory_chunks.source_note_id IS NULL OR EXISTS (SELECT 1 FROM public.generated_notes n WHERE n.id = case_memory_chunks.source_note_id AND n.case_id = case_memory_chunks.case_id AND n.user_id = case_memory_chunks.user_id)) AND case_memory_chunks.counselor_id = case_memory_chunks.user_id);

CREATE POLICY tenant_parent_write_insert ON public.document_exports
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = document_exports.case_id AND p.user_id = document_exports.user_id));

CREATE POLICY tenant_parent_write_update ON public.document_exports
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (true)
  WITH CHECK (EXISTS (SELECT 1 FROM public.cases p WHERE p.id = document_exports.case_id AND p.user_id = document_exports.user_id));
