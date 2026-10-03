# ERD: SayyaraDMS Database Design

> Phase 0 design. Labels: **FACT** / **ASSUMPTION** / **DECISION** / **OPEN QUESTION** (see [DECISIONS.md](DECISIONS.md)). Table names follow SPEC §5. Every rename or addition is listed in §9.

---

## 1. Global conventions

| Convention | Rule | Label |
|---|---|---|
| Primary keys | `id uuid default gen_random_uuid()` | FACT |
| Tenant column | `tenant_id uuid not null` on every tenant-owned table, with RLS enabled | FACT |
| Tenant-safe FKs | `UNIQUE (tenant_id, id)` on every tenant table; FKs are composite `(tenant_id, x_id) → x(tenant_id, id)` | DECISION D-11 |
| Audit columns | `created_at, created_by, updated_at, updated_by` on every table (journal tables: `created_*` only, since they are immutable) | FACT |
| Money | `numeric(18,2)` with `check (amount >= 0)` unless a sign is meaningful | FACT |
| Percent / quantity | `numeric(9,4)` (but see Q-09, ownership precision) | FACT |
| Soft delete | Master data: `archived_at timestamptz null`. Financial documents: never deleted after posting; drafts can be hard-deleted | FACT |
| Document status | Financial documents: `status in ('DRAFT','POSTED','CANCELLED'/'REVERSED')`, plus `journal_entry_id` once posted | DECISION D-19 |
| Accounting dates | `date` in the tenant's timezone | DECISION D-18 |
| Enumerations | Lifecycle statuses are Postgres `text` + `check` constraints (fixed in code). Configurable lists are reference tables | FACT |

---

## 2. Platform and tenancy

```mermaid
erDiagram
    plans ||--o{ subscriptions : "priced by"
    tenants ||--|| subscriptions : has
    tenants ||--|| tenant_settings : has
    tenants ||--o{ branches : has
    branches ||--o{ locations : contains
    tenants ||--o{ memberships : has
    roles ||--o{ memberships : grants
    roles ||--o{ role_permissions : bundles
    permissions ||--o{ role_permissions : in
    tenants ||--o{ feature_flags : overrides
    plans ||--o{ feature_flags : defaults
    tenants ||--o{ support_access_grants : grants
    tenants ||--o{ tenant_counters : numbers
    subscriptions ||--o{ subscription_invoices : bills

    tenants {
        uuid id PK
        text name_ar
        text name_en
        text country_code "EG, QA"
        char currency "EGP, QAR"
        text timezone
        text status "ACTIVE, ARCHIVED"
    }
    tenant_settings {
        uuid tenant_id PK
        text commercial_reg_no
        text tax_reg_no
        smallint fiscal_year_start_month
        text default_language
        text digit_style "ARABIC_INDIC, WESTERN"
        text cash_negative_policy "WARN, BLOCK"
        text profit_policy "PERIODIC, PER_CAR (D-40)"
        text distribution_frequency "AD_HOC, MONTHLY, QUARTERLY, YEARLY"
        text loss_handling "ALLOCATE_TO_PARTNERS, CARRY_FORWARD"
        text prorata_method "DAY_WEIGHTED, SUB_PERIOD_PROFIT"
        text rounding_remainder "LARGEST_REMAINDER, LARGEST_SHARE"
        text sale_cancellation_method "REFUND_LIABILITY, MIRROR (D-41)"
        text overpayment_policy "BLOCK, ALLOW_AS_CREDIT"
        text installment_markup_mode "A, B_ENABLED"
        jsonb aging_thresholds "30,60,90"
        jsonb attention_thresholds
        text_arr expected_cost_categories
        bool partner_sees_summary
        text sale_post_permission_mode
    }
    memberships {
        uuid id PK
        uuid tenant_id FK
        uuid user_id "auth.users"
        uuid role_id FK
        uuid partner_id FK "nullable"
        text status "INVITED, ACTIVE, DISABLED"
    }
    roles {
        uuid id PK
        uuid tenant_id "null = system role"
        text code "OWNER, MANAGER, ..."
    }
    tenant_counters {
        uuid tenant_id PK
        text counter_key PK "journal, stock-2026, invoice-2026"
        bigint last_value
    }
    support_access_grants {
        uuid id PK
        uuid tenant_id FK
        uuid platform_user_id
        timestamptz expires_at
        text scope "READ_ONLY"
        uuid granted_by
    }
```

Additional tables:

- `permissions(code PK, description)`
- `role_permissions(role_id, permission_code)`
- `invitations(tenant_id, email/phone, role_id, partner_id, token_hash, expires_at)`
- `platform_admins(user_id PK)`
- `plans(code, limits jsonb)`
- `subscriptions(tenant_id, plan_id, status TRIAL|ACTIVE|PAST_DUE|SUSPENDED, trial_ends_at, current_period_end)`
- `subscription_invoices(manual billing: amount, currency, status, paid_marked_by)`
- `branches(name_ar, name_en, address)`
- `locations(branch_id null, type BRANCH_YARD|OUTDOOR_LOT|WORKSHOP|EXTERNAL_SHOWROOM|CUSTOMER, external_showroom_id null, name)`

**DECISION D-20.** `tenant_counters` is a single table for all gapless or sequential numbers:

- journal `entry_no`
- vehicle stock number `V-{YYYY}-{seq:04}`
- invoice numbers per CountryPack
- receipt numbers

Every number is taken with `SELECT … FOR UPDATE` inside the posting transaction.

---

## 3. Partners

```mermaid
erDiagram
    partners ||--o{ partner_share_history : "effective-dated %"
    partners ||--o{ partner_transactions : has
    partners ||--o{ vehicle_investors : "car-level (flagged)"
    vehicles ||--o{ vehicle_investors : "car-level (flagged)"
    partner_transactions }o--|| journal_entries : posts
    partners {
        uuid id PK
        uuid tenant_id FK
        text name
        text phone
        text national_id_enc "encrypted, masked in UI"
        date active_from
        date active_to
    }
    partner_share_history {
        uuid id PK
        uuid tenant_id FK
        uuid partner_id FK
        numeric percentage "9,4"
        date effective_from
        date effective_to "null = open"
        uuid change_batch_id "all rows of one change"
    }
    partner_transactions {
        uuid id PK
        uuid tenant_id FK
        uuid partner_id FK
        text type "CONTRIBUTION, CAPITAL_WITHDRAWAL, DRAWING, LOAN_TO_PARTNER, LOAN_TO_PARTNER_REPAYMENT, LOAN_FROM_PARTNER, LOAN_FROM_PARTNER_REPAYMENT"
        date txn_date
        numeric amount
        uuid cash_account_id FK
        text notes
        text status
        uuid journal_entry_id FK
    }
    vehicle_investors {
        uuid id PK
        uuid tenant_id FK
        uuid vehicle_id FK
        uuid partner_id FK
        numeric percentage
    }
```

- **FACT.** Share changes are effective-dated and never overwritten.
- **DECISION D-21.** A share change is a **batch**: one `change_batch_id`, all partners' new rows together. A deferred constraint trigger checks at commit that the active percentages sum to 100.0000 for every date touched. This avoids invalid intermediate states (G-04).
- Partner ownership has an exclusion constraint: no overlapping `[effective_from, effective_to)` per partner (`btree_gist`).
- **As built (Phase 3):** `partners` has `name_ar`, `name_en`, `national_id_enc` + `national_id_last4` (D-65) and `archived_at` instead of `active_from/active_to` (activity comes from share history, D-62); `partner_transactions` uses the `posted_document_before_update` trigger; `memberships.partner_id` links a user (D-66); `other_incomes` holds P-01 documents.
- An expense paid personally by a partner (rule 30) is **not** a `partner_transactions` row. It is a `vehicle_expenses`/`general_expenses` row with `paid_by_partner_id` and `partner_funding_mode CURRENT_ACCOUNT|LOAN`.

---

## 4. Customers, suppliers, external showrooms, CRM

```mermaid
erDiagram
    customers ||--o{ follow_ups : has
    customers ||--o{ customer_requests : asks
    customer_requests ||--o{ customer_request_matches : matched
    vehicles ||--o{ customer_request_matches : matches
    customers {
        uuid id PK
        uuid tenant_id FK
        text name
        text phone_primary "normalized E.164, indexed"
        text_arr phones
        text national_id_enc
        bool is_buyer
        bool is_seller
        bool is_consignor
        uuid assigned_to
        timestamptz archived_at
    }
    follow_ups {
        uuid id PK
        uuid tenant_id FK
        uuid customer_id FK
        uuid request_id FK "nullable"
        text kind "CALL, VISIT, TEST_DRIVE, NOTE"
        timestamptz occurred_at
        text result
        text next_action
        date next_follow_up_date
        uuid assigned_to
        text priority
    }
    customer_requests {
        uuid id PK
        uuid tenant_id FK
        uuid customer_id FK
        text make
        text model
        smallint year_from
        smallint year_to
        numeric budget_min
        numeric budget_max
        text color_pref
        text status "NEW..WON, LOST, ON_HOLD"
        bool financing_needed
        bool trade_in_offered
        text source
        uuid assigned_to
    }
    customer_request_matches {
        uuid id PK
        uuid tenant_id FK
        uuid request_id FK
        uuid vehicle_id FK
        timestamptz matched_at
        bool contacted
        uuid contacted_by
        timestamptz contacted_at
    }
    suppliers {
        uuid id PK
        uuid tenant_id FK
        text name
        text kind "WORKSHOP, TRANSPORT, PARTS, AD_AGENCY, OTHER"
        text phone
    }
    external_showrooms {
        uuid id PK
        uuid tenant_id FK
        text name
        text contact_name
        text phone
        text address
    }
```

- DECISION D-22: the spec's `call_logs` is renamed `follow_ups`, because it also holds visits, test drives and notes.
- DECISION D-23: a `suppliers` table is added (the spec's COA has 2700 "subledger by supplier", but §5 has no table; see C-05).
- Sellers and consignors are `customers` with flags (FACT).

---

## 5. Vehicles and consignment

```mermaid
erDiagram
    vehicles ||--o{ vehicle_status_history : has
    vehicles ||--o{ vehicle_location_history : has
    vehicles ||--o{ vehicle_price_history : has
    vehicles ||--o{ vehicle_media : has
    vehicles ||--o| vehicle_purchases : "bought by"
    vehicle_purchases ||--o{ purchase_payments : "paid by"
    vehicles ||--o{ vehicle_expenses : has
    vehicles ||--o| consignments_in : "if CONSIGNED_IN"
    vehicles ||--o{ consignments_out : "sent out"
    consignments_in ||--o{ consignor_settlements : settled
    consignments_out ||--o{ external_collections : collected
    vehicles {
        uuid id PK
        uuid tenant_id FK
        text stock_no "V-2026-0042, unique per tenant"
        text vin "unique per tenant where archived_at is null"
        text vin_normalized
        text plate_no
        text make
        text model
        text trim
        smallint year
        text color_ext
        text color_int
        text body_type
        text transmission
        text fuel
        int engine_cc
        int mileage_km
        date license_expiry
        text license_governorate
        text ownership_type "OWNED, CONSIGNED_IN"
        text acquisition_source "DIRECT_PURCHASE, TRADE_IN, CONSIGNMENT_IN, AUCTION, IMPORT"
        text status "state machine"
        uuid current_location_id FK
        numeric asking_price
        numeric min_price "masked"
        date stock_date "days-in-stock start (Q-24)"
        timestamptz last_price_change_at
        text notes
        timestamptz archived_at
    }
    vehicle_purchases {
        uuid id PK
        uuid tenant_id FK
        uuid vehicle_id FK "unique"
        uuid seller_customer_id FK
        date purchase_date
        numeric price
        numeric deferred_amount
        text status
        uuid journal_entry_id FK
    }
    vehicle_expenses {
        uuid id PK
        uuid tenant_id FK
        uuid vehicle_id FK
        uuid category_id FK
        date expense_date
        numeric amount
        text funding "CASH_ACCOUNT, SUPPLIER_CREDIT, PARTNER"
        uuid cash_account_id FK
        uuid supplier_id FK
        uuid paid_by_partner_id FK
        text partner_funding_mode "CURRENT_ACCOUNT, LOAN"
        text treatment "CAPITALIZE, RECOVERABLE, SHOWROOM_EXPENSE"
        text status
        uuid journal_entry_id FK
    }
    consignments_in {
        uuid id PK
        uuid tenant_id FK
        uuid vehicle_id FK
        uuid consignor_id FK "customers"
        date agreement_date
        date end_date
        text terms_type "NET_PRICE, COMMISSION_FIXED, COMMISSION_PCT"
        numeric net_price_to_owner
        numeric commission_value
        text expenses_borne_by "OWNER, SHOWROOM, SHARED"
        numeric shared_owner_pct "Q-15"
        text status "ACTIVE, SOLD, SETTLED, RETURNED"
    }
    consignments_out {
        uuid id PK
        uuid tenant_id FK
        uuid vehicle_id FK
        uuid external_showroom_id FK
        date sent_date
        date returned_date
        text commission_type "FIXED, PCT"
        numeric commission_value
        numeric expected_price
        text status "OUT, SOLD, RETURNED"
    }
```

Other vehicle tables:

- `vehicle_status_history(vehicle_id, from_status, to_status, changed_at, changed_by, reason)`
- `vehicle_location_history(vehicle_id, from_location_id, to_location_id, moved_at, moved_by, reason)`
- `vehicle_price_history(vehicle_id, asking_price, min_price, changed_at, changed_by)`
- `vehicle_media(vehicle_id, storage_path, kind PHOTO, sort_order)`
- `purchase_payments(purchase_id, cash_account_id, payment_method_id, amount)`
- `consignor_settlements(consignment_in_id, kind PAYOUT|RECOVERY, amount, cash_account_id, journal_entry_id)`
- `external_collections(consignment_out_id, external_showroom_id, amount, cash_account_id, journal_entry_id)`

**Status state machine (FACT, SPEC §4.3).** Enforced in the backend service and mirrored by a DB trigger that rejects transitions not in this table:

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> IN_PREPARATION
    IN_PREPARATION --> AVAILABLE
    AVAILABLE --> RESERVED
    RESERVED --> AVAILABLE
    RESERVED --> SOLD
    AVAILABLE --> SOLD
    IN_PREPARATION --> AT_OTHER_SHOWROOM
    AVAILABLE --> AT_OTHER_SHOWROOM
    AT_OTHER_SHOWROOM --> AVAILABLE
    AT_OTHER_SHOWROOM --> SOLD
    SOLD --> DELIVERED
    SOLD --> AVAILABLE: sale cancelled
    DRAFT --> ARCHIVED
    IN_PREPARATION --> RETURNED_TO_OWNER: consigned-in only
    AVAILABLE --> RETURNED_TO_OWNER: consigned-in only
    RESERVED --> RETURNED_TO_OWNER: consigned-in only
    IN_PREPARATION --> ARCHIVED
    AVAILABLE --> ARCHIVED
```

- **As built (Phase 4):** `vehicle_status_history`, `vehicle_location_history` and `vehicle_price_history` are written by DB triggers (append-only); `vehicle_media` and `documents` hold storage paths only; `vehicle_purchases` also records trade-ins (`source = TRADE_IN`, posted inside the sale entry); `seller_payments` (rule 8) and `supplier_payments` (rule 32) are documents of their own; `vehicle_expenses.treatment` is `CAPITALIZE` or `COGS` (P-04; consigned-car treatments were added in Phase 6, D-93); `locations` is seeded per tenant (showroom, workshop, with customer).
- **ASSUMPTION.** `RESERVED → SOLD` and `AVAILABLE → SOLD` are both allowed (a sale without a prior reservation).
- **OPEN QUESTION Q-30.** Whether `DELIVERED → AVAILABLE` (cancellation after delivery) is allowed. It is not allowed by default.
- **OPEN QUESTION.** Whether a consigned-in car can go to `AT_OTHER_SHOWROOM` (re-consignment). It is not allowed by default.
- **As built (Phase 8):** `import_jobs` (go-live date, sheets with headers/rows/mapping as JSON, validation, result, the opening entry; immutable once COMMITTED) and `import_mappings` (per tenant, kind and header signature). `installment_plans.sale_id` is nullable for imported plans (`opening_reference`, `opening_vehicle`, D-107); `vehicle_purchases.source` adds OPENING with an optional seller (D-108).
- **As built (Phase 7):** `profit_distributions` (range, the options used, net profit, allocated in advance, carried-in loss, distributed, the closing / netting / distribution entries; POSTED → REVERSED only; no two posted ranges overlap) with `profit_distribution_lines` (partner, weight %, amount; immutable); `profit_allocations` (per-car allocation of a sale, POSTED → REVERSED). `journal_entries.is_closing` marks rules 22/23 entries, which alone may be dated inside a distributed range.
- **As built (Phase 6):** `consignments_in` holds one agreement per car (unique on the vehicle) with `terms_type`, `net_price_to_owner` / `commission_value`, `expenses_borne_by` and `shared_owner_pct`, status ACTIVE → SOLD / RETURNED; `consignor_settlements` (PAYOUT rule 17, RECOVERY P-06) and `external_collections` are posted documents (POSTED → REVERSED only). Collections belong to the **showroom**, not to one car (D-95). `consignments_out` allows one open row per car; a sale by the showroom is a `sales` row with `channel = EXTERNAL_SHOWROOM`, `external_showroom_id`, `external_commission` and `commission_journal_entry_id`, and no buyer or invoice. `vehicle_expenses.treatment` adds RECOVERABLE, SHOWROOM and SHARED (D-93). `journal_lines.consignor_id` and `external_showroom_id` now have foreign keys. `follow_ups` is append-only (trigger); `customer_request_matches` is filled by the `vehicles_available_match` trigger (D-97). A RESERVED consigned car is not returned to its owner until its deposit is settled.

---

## 6. Sales, installments and deferred papers

```mermaid
erDiagram
    customers ||--o{ reservations : makes
    vehicles ||--o{ reservations : "reserved by"
    reservations |o--o| sales : "applied to"
    vehicles ||--o{ sales : "sold in"
    customers ||--o{ sales : buys
    sales ||--o{ sale_payments : "paid by"
    sales |o--o| vehicles : "trade-in vehicle"
    sales ||--o| installment_plans : "financed by"
    installment_plans ||--o{ installments : schedules
    customers ||--o{ customer_receipts : pays
    customer_receipts ||--o{ installment_payments : allocates
    installments ||--o{ installment_payments : "paid by"
    installments ||--o{ deferred_papers : "secured by"
    deferred_papers ||--o{ deferred_paper_events : history
    sales {
        uuid id PK
        uuid tenant_id FK
        text sale_no
        uuid vehicle_id FK
        uuid buyer_customer_id FK
        text channel "DIRECT, EXTERNAL_SHOWROOM"
        uuid external_showroom_id FK
        date sale_date
        numeric list_price
        numeric discount
        numeric sale_price "= list - discount"
        numeric trade_in_value
        uuid trade_in_vehicle_id FK
        uuid reservation_id FK
        numeric deposit_applied
        numeric receivable_amount
        text status "DRAFT, POSTED, CANCELLED"
        uuid journal_entry_id FK
        uuid cost_journal_entry_id FK
        text cancel_reason
        uuid cancel_journal_entry_id FK
        text invoice_no
        text einvoice_status
        uuid einvoice_uuid
    }
    reservations {
        uuid id PK
        uuid tenant_id FK
        uuid vehicle_id FK
        uuid customer_id FK
        date reservation_date
        numeric deposit_amount
        uuid cash_account_id FK
        date expires_on
        text status "ACTIVE, APPLIED, REFUNDED, FORFEITED"
        uuid journal_entry_id FK
    }
    sale_payments {
        uuid id PK
        uuid tenant_id FK
        uuid sale_id FK
        uuid cash_account_id FK
        uuid payment_method_id FK
        numeric amount
        text reference
    }
    installment_plans {
        uuid id PK
        uuid tenant_id FK
        uuid sale_id FK
        text mode "A, B"
        numeric financed_principal
        numeric markup_amount
        text frequency
        smallint count
        date first_due_date
    }
    installments {
        uuid id PK
        uuid tenant_id FK
        uuid plan_id FK
        smallint seq
        date due_date
        numeric amount_due
        numeric markup_portion
    }
    customer_receipts {
        uuid id PK
        uuid tenant_id FK
        uuid customer_id FK
        date receipt_date
        numeric amount
        uuid cash_account_id FK
        uuid deferred_paper_id FK
        text status
        uuid journal_entry_id FK
    }
    installment_payments {
        uuid id PK
        uuid tenant_id FK
        uuid receipt_id FK
        uuid installment_id FK
        numeric amount
    }
    deferred_papers {
        uuid id PK
        uuid tenant_id FK
        text paper_type "PROMISSORY_NOTE, PDC"
        text number
        uuid customer_id FK
        uuid installment_id FK
        numeric amount
        date issue_date
        date due_date
        text storage_location
        text drawer_bank
        text drawer_branch
        text account_holder
        text status "HELD, DEPOSITED, COLLECTED, BOUNCED, RETURNED, OVERDUE, DEFAULTED, LEGAL"
    }
```

- **FACT.** Installment remaining is **derived**: `amount_due − Σ installment_payments`. There is no `paid_amount` column (business rule 4). A view `v_installment_status` gives `paid`, `remaining`, `days_late` and `state`.
- **DECISION D-24.** The spec's `promissory_notes` table is renamed `deferred_papers`, because it covers notes and post-dated cheques (FACT, SPEC §4.8). Status changes are logged in `deferred_paper_events`.
- **DECISION.** A sale by an external showroom (rule 18) is a `sales` row with `channel = EXTERNAL_SHOWROOM`. There is one sales table and one "sold once" rule.
- **DECISION.** `OVERDUE` is derived (due date passed and remaining > 0) and **not** stored as a paper status, because a stored value would go stale. The stored statuses are the physical states. FACT: the spec lists "overdue" as a status; this is a deliberate deviation (C-10).

Partial unique index: `unique (tenant_id, vehicle_id) where status = 'POSTED'` on `sales` (business rule 1).

**As built (Phase 5):** `installment_plans` (one per sale, status ACTIVE/CANCELLED) and `installments` are immutable once created; `customer_receipts` belong to one plan (`source` CASH_ACCOUNT / CREDIT / PAPER, `excess_to_credit`, status POSTED / REVERSED / BOUNCED); `installment_payments` are the allocations; the `installment_status` view derives paid and remaining; `deferred_papers` (status machine in the database, `receipt_id` of the collection) and `deferred_paper_events` are append-only; `sales.receivable_amount` and `sales.installment_plan` (draft JSON). `notifications` (dedupe key per user) and `reminder_jobs` (per tenant per day) are in §8.

**As built (Phase 4):** `sales` also stores `sale_no`, the trade-in details as JSON until posting (`trade_in`), `cancellation_method` and both cancellation entries; `sale_payments.line_no` keeps the order of payment lines; `reservations.status` adds `RELEASED` (D-72); `customer_refunds` holds refunds of customer credit (P-02); `customers` has `national_id_last4` and E.164 `phone_primary` (D-68). `receivable_amount`, installments and deferred papers arrive in Phase 5.

---

## 7. Cash, expenses and ledger

```mermaid
erDiagram
    ledger_accounts ||--o{ ledger_accounts : parent
    cash_accounts ||--|| ledger_accounts : "maps to"
    expense_categories }o--o| ledger_accounts : "general → 62xx"
    payment_methods }o--|| cash_accounts : "default account"
    journal_entries ||--|{ journal_lines : contains
    journal_entries |o--o| journal_entries : "reversal_of / reversed_by"
    accounting_periods ||--o{ journal_entries : contains
    ledger_accounts ||--o{ journal_lines : "posted to"
    ledger_accounts {
        uuid id PK
        uuid tenant_id FK
        text code "1100, 1101, 6210"
        text name_ar
        text name_en
        text type "ASSET, LIABILITY, EQUITY, INCOME, EXPENSE"
        text normal_side "DEBIT, CREDIT"
        uuid parent_id FK
        bool is_system
        bool is_postable "headers false"
        text subledger "NONE, PARTNER, CUSTOMER, VEHICLE, CONSIGNOR, EXTERNAL_SHOWROOM, SUPPLIER, CASH_ACCOUNT"
        text system_key "e.g. VEHICLE_INVENTORY"
    }
    cash_accounts {
        uuid id PK
        uuid tenant_id FK
        text kind "CASH_BOX, BANK"
        text name
        uuid branch_id FK
        uuid ledger_account_id FK
        text bank_name
        text iban
        bool is_default
    }
    journal_entries {
        uuid id PK
        uuid tenant_id FK
        bigint entry_no "gapless per tenant"
        date entry_date
        text description
        text source_type "SALE, PURCHASE, ..."
        uuid source_id
        text status "POSTED"
        uuid reversal_of_id FK
        uuid reversed_by_id FK
        text reversal_reason
        uuid period_id FK
        bool is_closing
        bool is_opening
        uuid created_by
        timestamptz posted_at
    }
    journal_lines {
        uuid id PK
        uuid tenant_id FK
        uuid journal_entry_id FK
        smallint line_no
        uuid ledger_account_id FK
        numeric debit
        numeric credit
        date entry_date "denormalized for indexes"
        uuid partner_id FK
        uuid customer_id FK
        uuid vehicle_id FK
        uuid consignor_id FK
        uuid external_showroom_id FK
        uuid supplier_id FK
        uuid cash_account_id FK
        text memo
    }
    accounting_periods {
        uuid id PK
        uuid tenant_id FK
        date month "first day"
        text status "OPEN, LOCKED"
        timestamptz locked_at
        uuid locked_by
    }
```

Other tables:

- `expense_categories(kind VEHICLE|GENERAL, name_ar, name_en, ledger_account_id null, is_seeded, archived_at)`
- `payment_methods(code, name, cash_account_id)`
- `general_expenses(category_id, date, amount, funding, cash_account_id|supplier_id|paid_by_partner_id, journal_entry_id)`
- `other_incomes(date, amount, description, cash_account_id, journal_entry_id)`
- `transfers(date, from_cash_account_id, to_cash_account_id, amount, journal_entry_id)`
- `supplier_payments(supplier_id, date, amount, cash_account_id, journal_entry_id)`
- `bank_reconciliations`, `bank_statement_lines` (placeholders only, FACT §4.10)

### 7.1 Ledger integrity in the database (FACT, SPEC §5)

| Invariant | Mechanism |
|---|---|
| One side per line | `check ((debit > 0 and credit = 0) or (credit > 0 and debit = 0))` |
| Balanced, ≥ 2 lines | `CONSTRAINT TRIGGER … DEFERRABLE INITIALLY DEFERRED` on `journal_lines` insert, which checks the entry at commit |
| Immutable | `BEFORE UPDATE OR DELETE` triggers raise, except an update that changes **only** `reversed_by_id` from null, made while the `app.allow_reversal_link` setting is set by `reverse_journal_entry()` |
| Open period | `post_journal_entry` and a `BEFORE INSERT` trigger on `journal_entries` both check `accounting_periods` (a missing period row is auto-created as OPEN; D-25) |
| Gapless `entry_no` | `tenant_counters` row `FOR UPDATE`; `unique (tenant_id, entry_no)` |
| Sole entry point | No `INSERT` grant on journal tables for `app_api`/`authenticated`; only `post_journal_entry` (`SECURITY DEFINER`) |
| Account belongs to tenant | Composite FK `(tenant_id, ledger_account_id)` |
| Subledger required | Trigger: if `ledger_accounts.subledger = 'PARTNER'`, then `partner_id` is not null (same for each subledger type) |
| Postable only | Trigger: header accounts (`is_postable = false`) are rejected |

---

## 8. Distribution, imports, notifications, audit, documents, idempotency

| Table | Key columns | Notes |
|---|---|---|
| `profit_distributions` | `period_from, period_to, policy, net_profit, status DRAFT/POSTED, closing_entry_id, distribution_entry_id` | Preview is computed live, not stored; posting writes both entries |
| `profit_distribution_lines` | `distribution_id, partner_id, weighted_pct, amount` | Σ amount = net_profit (rounding: Q-18) |
| `import_jobs` | `kind VEHICLES/CUSTOMERS/PARTNERS/INSTALLMENTS, storage_path, status UPLOADED/MAPPED/VALIDATED/COMMITTED/FAILED, go_live_date, stats jsonb, opening_entry_id` | |
| `import_mappings` | `tenant_id, kind, name, column_map jsonb` | Remembered per tenant (FACT) |
| `import_job_rows` | `job_id, row_no, raw jsonb, normalized jsonb, errors jsonb, status` | Drives the validation preview |
| `notifications` | `user_id, kind, title_key, params jsonb, entity_type, entity_id, read_at, dedupe_key` | `unique(tenant_id, user_id, dedupe_key)` avoids duplicate daily alerts |
| `reminder_jobs` | `job_name, run_date, status, started_at, finished_at, stats` | One row per job run; `unique(job_name, run_date)` |
| `audit_log` | `id bigserial, tenant_id null, actor_user_id, actor_kind USER/PLATFORM/SYSTEM, action, entity_type, entity_id, before jsonb, after jsonb, ip inet, user_agent, request_id, occurred_at` | Append-only; partitioned by month (DECISION) |
| `documents` | `entity_type, entity_id, doc_type, storage_path, file_name, mime, size, sensitivity NORMAL/COST` | `sensitivity = COST` is hidden from sales (G-09). Replaces `vehicle_documents` (DECISION) |
| `idempotency_keys` | see ARCHITECTURE §10 | Added (G-06) |
| `support_grants` | `tenant_id, granted_by, reason, starts_at, expires_at (≤ 72 h), revoked_at` | Phase 9 (D-117); the planned `support_access_grants` |
| `invoices` | `tenant_id, period_start, period_end, amount, currency_code, status ISSUED/PAID/VOID, paid_at, reference, marked_by` | Phase 9 manual billing (D-116); the planned `subscription_invoices` |
| `country_packs.terminology` | `jsonb` translation key → country wording | Phase 9 (D-121, Q-25) |

---

## 9. Changes against SPEC §5 (all need approval)

| Spec name | Our design | Reason |
|---|---|---|
| `memberships.role` (text) | `role_id` → `roles` + `role_permissions` + `permissions` | Permission-based auth in SQL (C-02) |
| `call_logs` | `follow_ups` | Covers calls, visits, test drives, notes |
| `promissory_notes` | `deferred_papers` (+ `deferred_paper_events`) | Notes **and** PDCs |
| `vehicle_documents` | generic `documents` with `sensitivity` | One attachment mechanism |
| `sale_payments` | kept; plus `purchase_payments` | Split payments on purchases |
| `installment_payments` | kept, as allocations of `customer_receipts` | One receipt can pay several installments |
| (none) | added `suppliers`, `supplier_payments`, `supplier_id` on `journal_lines` | COA 2700 needs it (C-05) |
| (none) | added `vehicle_purchases`, `vehicle_location_history`, `vehicle_price_history`, `locations` | Required by §4.3 |
| (none) | added `consignor_settlements`, `external_collections`, `reservations.status` | Required by §4.4/§4.5 |
| (none) | added `tenant_counters`, `idempotency_keys`, `support_access_grants`, `invitations`, `subscription_invoices`, `import_job_rows`, `platform_admins`, `payment_methods`, `expense_categories` | Implied by spec text, missing from §5 |
| (none) | added `journal_lines.entry_date` (denormalized) | Date-range indexes on lines without a join |
| (none) | Phase 2: `coa_template` (reference chart copied into each tenant), `tenant_counters` key `journal_entry` | Seeding by trigger; gapless numbers |
| `idempotency_keys` (ARCHITECTURE §10) | stores the final response only, written in the operation's transaction (no IN_PROGRESS row) | A failed operation leaves no key, so retries run again |

---

## 10. Important indexes

**FACT (SPEC §11):** `tenant_id` plus common filters; journal lines indexed by account, partner, vehicle, customer and date.

| Table | Index | Serves |
|---|---|---|
| all tenant tables | `unique (tenant_id, id)` | Composite FKs |
| `vehicles` | `unique (tenant_id, vin_normalized) where archived_at is null` | VIN uniqueness (FACT) |
| `vehicles` | `unique (tenant_id, stock_no)` | |
| `vehicles` | `(tenant_id, status, stock_date)` | Inventory list, aging |
| `vehicles` | `(tenant_id, make, model, year)` | Filters, request matching |
| `vehicles` | trigram GIN on `vin_normalized`, `plate_no`; `(tenant_id, right(vin_normalized, 6))` | Quick search by last digits |
| `customers` | `(tenant_id, phone_primary)`; trigram GIN on `name`, `phones` | Phone-first search |
| `journal_lines` | `(tenant_id, ledger_account_id, entry_date)` include `(debit, credit)` | Balances, cash book, TB |
| `journal_lines` | `(tenant_id, partner_id, entry_date) where partner_id is not null` | Partner statement |
| `journal_lines` | `(tenant_id, vehicle_id) where vehicle_id is not null` | Vehicle cost/profit |
| `journal_lines` | `(tenant_id, customer_id, entry_date) where customer_id is not null` | Customer balances |
| `journal_lines` | `(tenant_id, cash_account_id, entry_date) where cash_account_id is not null` | Cash/bank book |
| `journal_lines` | partial indexes for `consignor_id`, `external_showroom_id`, `supplier_id` | Statements |
| `journal_entries` | `unique (tenant_id, entry_no)`; `(tenant_id, entry_date)`; `(tenant_id, source_type, source_id)` | |
| `installments` | `(tenant_id, due_date)` | Due/overdue board, reminder job |
| `deferred_papers` | `(tenant_id, status, due_date)`; `unique (tenant_id, paper_type, number, drawer_bank)` | Register |
| `sales` | `unique (tenant_id, vehicle_id) where status = 'POSTED'`; `(tenant_id, sale_date)` | Rule 1, reports |
| `customer_requests` | `(tenant_id, status, make, model)` | Matching |
| `follow_ups` | `(tenant_id, assigned_to, next_follow_up_date)` | "Follow-ups due today" |
| `partner_share_history` | GiST exclusion `(tenant_id, partner_id, daterange(effective_from, effective_to))` | No overlaps |
| `memberships` | `unique (tenant_id, user_id)`; `(user_id)` | RLS helper lookups |
| `audit_log` | `(tenant_id, occurred_at desc)`; `(tenant_id, entity_type, entity_id)` | Viewer |
| `notifications` | `(tenant_id, user_id, read_at)` | Bell counter |

**ASSUMPTION.** With these indexes and 100k lines per tenant, aggregate balance queries stay well under 100 ms. This is verified in the Phase 9 performance tests (D-12).
