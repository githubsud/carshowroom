-- =============================================================================
-- Pilot owner's answers (DECISIONS answer log 2026-10-03), second changes.
-- * Every purchase and sale keeps the power of attorney (توكيل) or the contract
--   and the ID card: a power of attorney is now its own document type.
-- Installment markup (Q-03) needs no schema change: it is part of the stored
-- installment plan and posts to the existing 4300.
-- =============================================================================
alter table public.documents drop constraint documents_doc_type_check;
alter table public.documents add constraint documents_doc_type_check
  check (doc_type in ('LICENSE', 'PURCHASE_CONTRACT', 'SELLER_RECEIPT', 'INSPECTION_REPORT', 'SALE_CONTRACT',
                      'ID_COPY', 'POWER_OF_ATTORNEY', 'OTHER'));
