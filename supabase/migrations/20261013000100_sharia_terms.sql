-- =============================================================================
-- Sharia compliance (docs/SHARIA.md, D-132). Selling on installments at a price
-- above the cash price is a deferred-price sale, not a loan: its gain is sale
-- profit, never interest. The account names say so.
-- =============================================================================
-- Renames only: a suspended showroom's accounts are renamed too (D-113 guard off here).
alter table public.ledger_accounts disable trigger require_tenant_writable;

update public.coa_template
   set name_ar = 'أرباح البيع بالتقسيط', name_en = 'Installment sale profit'
 where system_key = 'INSTALLMENT_FINANCING_INCOME';
update public.ledger_accounts
   set name_ar = 'أرباح البيع بالتقسيط', name_en = 'Installment sale profit'
 where system_key = 'INSTALLMENT_FINANCING_INCOME';

update public.coa_template
   set name_ar = 'أرباح بيع بالتقسيط مؤجلة', name_en = 'Deferred installment sale profit'
 where system_key = 'DEFERRED_INSTALLMENT_INCOME';
update public.ledger_accounts
   set name_ar = 'أرباح بيع بالتقسيط مؤجلة', name_en = 'Deferred installment sale profit'
 where system_key = 'DEFERRED_INSTALLMENT_INCOME';

alter table public.ledger_accounts enable trigger require_tenant_writable;
