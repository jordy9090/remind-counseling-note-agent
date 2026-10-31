-- Extend the allowed template only. Ownership, immutable review and cascade
-- cleanup policies remain shared with the existing voucher documents.
alter table public.voucher_documents drop constraint voucher_documents_template_check;
alter table public.voucher_documents add constraint voucher_documents_template_check
  check (template in ('form10', 'form25', 'form26'));
