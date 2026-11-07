-- Require the same packet as the prepare endpoint for direct authenticated inserts.
-- The existing owner policy still applies. Reviews of historical rows use UPDATE.
create policy voucher_documents_packet_insert on public.voucher_documents
  as restrictive for insert to authenticated
  with check (snapshot #>> '{form,edition}' = 'ari-2026');
