# BUSINESS_RULES: Catalogue of Enforced Rules

> SPEC §3.4: business rules live in the service layer (never only in routers or Angular). Each rule has an ID, the place it is enforced, and the test that proves it.
> **Status:** ✅ enforced and tested · ⏳ arrives with a later phase.
> Wherever the database also enforces a rule, that check is listed. The database is the final guard.

## Ledger and money (Phase 2)

| ID | Rule | Enforced in | Proven by |
|---|---|---|---|
| BR-L1 | A journal entry balances: Σ debit = Σ credit, at least 2 lines, total > 0 | `EntryDraft.validate()`; DB deferred constraint trigger `journal_entries_balanced` | `test_posting_rules.py::test_draft_rejects_unbalanced_entries`; pgTAP 05 "unbalanced entry is rejected by the database" ✅ |
| BR-L2 | Every line has exactly one side (debit **or** credit), non-negative, at most 2 decimals; amounts are never rounded silently | `Line.validate()`; `parse_money`; DB check `journal_lines_one_side`; `insert_journal_entry` decimals check | `test_money.py`; pgTAP 05 (negative, two-sided, 3 decimals) ✅ |
| BR-L3 | Posted entries are never edited or deleted; corrections only by reversal (business rule 9) | DB triggers on `journal_entries` / `journal_lines` (incl. owner and TRUNCATE); no write grants for client roles | pgTAP 05 "cannot update / delete, even by the owner" ✅ |
| BR-L4 | A reversal is the exact mirror, linked both ways, needs a reason, happens once, and cannot itself be reversed | `rules.reversal_lines`; `private.reverse_journal_entry` | `test_posting_rules.py::test_rule_24_*`; pgTAP 05; `test_ledger.py::test_reversal_*` ✅ |
| BR-L5 | Nothing is posted or reversed with a date inside a locked month | DB trigger `journal_entry_before_insert` (FOR SHARE on the period row); preview check `ensure_period_open` | pgTAP 05; `test_ledger.py::test_locked_month_rejects_postings_and_reversals` ✅ |
| BR-L6 | Only the owner unlocks a month, with a reason; lock and unlock are audit-logged | `period.unlock` permission (owner bundle only); `periods.unlock` | `test_ledger.py::test_only_the_owner_unlocks` ✅ |
| BR-L7 | Entry numbers are sequential per showroom with no gaps, even under concurrency or rollback | `tenant_counters` row updated inside the posting transaction | `test_ledger.py::test_concurrent_postings_get_gapless_numbers` ✅ |
| BR-L8 | No record may reference another showroom's data (business rule 8) | Composite `(tenant_id, id)` foreign keys; RLS for `app_api`; tenant taken from the request, never the payload | pgTAP 02, 05; `test_ledger.py::test_another_tenants_entry_or_account_is_invisible` ✅ |
| BR-L9 | Header accounts cannot receive postings; an account's code, type, side and subledger never change after creation | DB triggers `journal_line_before_insert`, `ledger_accounts_protect` | pgTAP 05 ✅ |
| BR-L10 | A line on a subledger account carries the matching id; a cash line's cash account must own that ledger account | DB trigger `journal_line_before_insert` | pgTAP 05 (cash, partner) ✅ |
| BR-L11 | Balances are always derived from journal lines; no editable balance field exists | Schema (no balance columns); `finance.list_cash_accounts`, `journal.list_accounts` | `test_ledger.py::test_cash_book_reconciles_with_the_balance` ✅ |
| BR-L12 | A money-moving request posts once, however often it is retried (Idempotency-Key) | `services/idempotency.run` | `test_ledger.py::test_retrying_with_the_same_key_posts_once` ✅ |
| BR-L13 | Nothing is posted with a future date (tenant timezone) | `finance.check_entry_date` (DECISION D-52) | `test_ledger.py::test_invalid_expenses_are_rejected[DATE_IN_FUTURE]` ✅ |

## Cash and bank (Phase 2)

| ID | Rule | Enforced in | Proven by |
|---|---|---|---|
| BR-C1 | A cash box cannot go negative unless the showroom allows it: `WARN` (default) posts with a warning, `BLOCK` refuses (business rule 7) | `finance.check_cash` with row locks on the cash accounts | `test_ledger.py::test_cash_negative_policy_warns_or_blocks` ✅ |
| BR-C2 | A transfer needs two different, active accounts | `rules.transfer`; DB check on `transfers` | `test_posting_rules.py`; `test_ledger.py::test_transfer_to_the_same_account_is_refused` ✅ |
| BR-C3 | A general expense uses an active *general* category; vehicle categories are for vehicle costs only | `finance._plan_expense` | `test_ledger.py::test_vehicle_category_cannot_be_a_general_expense` ✅ |
| BR-C4 | A cash/bank account with a non-zero balance cannot be archived (D-53) | `finance.update_cash_account` | `test_ledger.py::test_cash_account_with_money_cannot_be_archived` ✅ |
| BR-C5 | Every cash box / bank account has its own ledger sub-account (1101…, 1201…), and every general category its own 62xx account | `finance.create_cash_account`, `finance.create_category` | `test_ledger.py::test_new_cash_account_*`, `test_new_general_category_*` ✅ |
| BR-C6 | A posted expense or transfer is never edited; it moves to REVERSED only together with its reversal entry | DB trigger `posted_document_before_update`; `journal.reverse` | `test_ledger.py::test_reversal_restores_balances_and_marks_the_document` ✅ |

## Partners (Phase 3)

| ID | Rule | Enforced in | Proven by |
|---|---|---|---|
| BR-P1 | Active partners' ownership percentages total 100% on every date | `partners.change_shares` (`SHARES_NOT_100`); DB deferred trigger `check_partner_shares` (SR010) | pgTAP 07; `test_partners.py` (share validations) ✅ |
| BR-P2 | Ownership history is never overwritten or deleted; periods never overlap; a new batch starts after the latest one (D-64) | DB update/delete triggers (SR003), exclusion constraint `partner_share_no_overlap`; `SHARE_DATE_INVALID` | pgTAP 07 ✅ |
| BR-P3 | A loan repayment cannot exceed what is owed (D-63) | `partners._plan_transaction` | `test_partners.py` (repayment cap) ✅ |
| BR-P4 | Drawings above the net position and negative capital post with a warning (D-63) | `partners._plan_transaction` | `test_partner_rules.py`, `test_partners.py` ✅ |
| BR-P5 | A capital withdrawal also needs `partner.equity.change` | `routers/partners.py` | `test_partners.py` (capital withdrawal permission) ✅ |
| BR-P6 | A partner with an open share or any balance cannot be archived (D-62) | `partners.update_partner` | `test_partners.py` (archive refused) ✅ |
| BR-P7 | National IDs are stored encrypted, shown masked, and every reveal is audited (D-65) | `core/crypto.py`; `partners.reveal_national_id` | `test_crypto.py`; `test_partners.py` (national ID) ✅ |
| BR-P8 | An expense paid by a partner leaves the cash box untouched (rule 30, D-67) | `finance._plan_expense`; DB check `general_expenses_one_funding` | `test_partners.py` (rule 30) ✅ |

## Vehicles and sales (Phase 4)

| ID | Rule | Enforced in | Proven by |
|---|---|---|---|
| BR-V1 | A car follows the lifecycle of SPEC §4.3; SOLD only with a posted sale, back to AVAILABLE only after the sale is cancelled | `vehicles.change_status` / flows (D-70); DB trigger `vehicle_before_update` (SR020) | pgTAP 08; `test_vehicles_sales.py::test_vehicle_rules_through_the_api` ✅ |
| BR-V2 | One VIN per car still with the showroom (D-69) | `vehicles._check_vin_free`; partial unique index | pgTAP 08; `test_vin_must_be_unique_in_stock` ✅ |
| BR-V3 | Status, location and price history are never edited or deleted | DB triggers | pgTAP 08 ✅ |
| BR-V4 | Cost is derived from the ledger; profit uses recorded costs only (D-71, business rule 5) | `vehicles.cost_totals`; `VEHICLE_COST_MISSING` | `test_purchase_expenses_sale_cycle_matches_hand_calculation` ✅ |
| BR-V5 | Sales staff never receive cost, profit or minimum price through the API, the Supabase client, search or documents | `api/masking.py`; RLS on base tables; `vehicles_catalog`; `documents.sensitivity` | pgTAP 08; `test_sales_staff_never_receive_cost_data`; E2E sales staff ✅ |
| BR-V6 | An expense on a sold car goes to cost of sales (P-04); a capitalised cost of a sold car cannot be reversed (D-75) | `rules.vehicle_expense`; `journal._guard_document` | unit `test_p04_*`; `test_sale_entries_are_undone_only_by_cancelling` ✅ |
| BR-S1 | A vehicle can be sold only once, unless its sale was cancelled | `sales._plan_post`; partial unique index `sales_one_posted_per_vehicle_idx` | pgTAP 08; cycle test ✅ |
| BR-S2 | A cancelled sale never changes and takes no new payments | DB trigger `sale_before_change` | pgTAP 08 ✅ (installment payments: Phase 5) |
| BR-S6 | Payments + deposit + trade-in equal the sale price (D-73) | `rules.sale`; `SALE_AMOUNTS_MISMATCH` | unit `test_sale_amounts_must_add_up_to_the_price` ✅ |
| BR-S7 | A sale is posted only by `sale.post`; staff edit only their own drafts (D-78) | routers + `sales._editable_draft` | `sold_car` fixture (403 for sales) ✅ |
| BR-S8 | A delivered sale, or one whose trade-in car has been used, cannot be cancelled (Q-30, D-76) | `sales._plan_cancel` | `test_vehicle_rules_through_the_api` ✅ |
| BR-R1 | A deposit reserves an available car only; it is applied to that buyer's sale, or refunded or forfeited in full (D-72) | `sales._plan_reservation`, `_plan_settle`, `_plan_post` | `test_deposit_refund_frees_the_car`, MIRROR test ✅ |
| BR-M1 | Payments to sellers and suppliers and refunds of credit never exceed what is owed (D-79) | `vehicles`, `suppliers`, `customers` services | cycle test, trade-in test ✅ |

## Access (Phases 1–4)

| ID | Rule | Enforced in | Proven by |
|---|---|---|---|
| BR-A1 | Sales staff never receive cost data and no configuration can grant it | `role_permission_restrictions` + trigger | pgTAP 01, 03 ✅ |
| BR-A2 | Sales and partners cannot see or move money | Permission checks (API) + RLS (`cash.view`, `journal.view`) | `test_ledger.py::test_sales_and_partner_cannot_move_or_see_money`; E2E "sales staff have no access" ✅ |
| BR-A3 | Debit/credit wording is shown only to users with journal access (SPEC §9.3) | `Preview.lines` only with `journal.view`; journal page behind `journal.view` | `test_ledger.py::test_manager_preview_hides_debit_credit_lines` ✅ |
| BR-A4 | A showroom always keeps at least one active owner | `users.update_member` | `test_users.py::test_last_owner_cannot_be_demoted_or_disabled` ✅ |
| BR-A5 | A suspended showroom is read-only | `require_writable`; `private.tenant_writable` | `test_tenant_access.py::test_suspended_tenant_is_read_only` ✅ |
| BR-A6 | A partner user sees only their own partner record and statement; the summary only if the showroom allows it | RLS (`my_partner_id`); `_can_see_partner`; `partner_sees_summary` | pgTAP 07; `test_partners.py` (partner own access); E2E partner user ✅ |

## From SPEC §3.4, arriving later

| ID | Rule | Phase |
|---|---|---|
| BR-S3 | A payment cannot exceed the outstanding amount unless the excess is recorded as customer credit (setting D-41) | ⏳ 5 |
| BR-S4 | Installment remaining = amount due − payments, always derived | ⏳ 5 |
