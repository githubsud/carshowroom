# API: FastAPI Specification (v1)

> Phase 0 design. Labels: **FACT** / **ASSUMPTION** / **DECISION** / **OPEN QUESTION** ([DECISIONS.md](DECISIONS.md)).
> Permissions refer to the catalogue in [ARCHITECTURE.md §7](ARCHITECTURE.md#7-permissions-and-roles). Posting rules refer to [ACCOUNTING.md](ACCOUNTING.md).
> This document defines contracts. The OpenAPI schema generated in Phase 1+ is the machine-readable source, and the typed Angular client is generated from it (FACT, SPEC §8).

---

## 1. Conventions

| Topic | Rule | Label |
|---|---|---|
| Base path | `/api/v1` | FACT |
| Auth | `Authorization: Bearer <Supabase access token>`, verified via JWKS | FACT |
| Tenant | `X-Tenant-Id: <uuid>` on every tenant endpoint | FACT |
| Idempotency | `Idempotency-Key: <uuid>` **required** on every money-moving POST (a missing key returns `400 IDEMPOTENCY_KEY_REQUIRED`). A replay returns the original status and body plus the header `Idempotent-Replay: true` | FACT; "required" is a DECISION |
| Money | JSON **strings** with 2 decimals (`"125000.00"`). Requests with more than 2 decimals are rejected (`422 MONEY_PRECISION`); they are not rounded | FACT / DECISION |
| Percent | String with up to 4 decimals (`"33.3334"`) | FACT |
| Dates | `YYYY-MM-DD` (tenant-local accounting date); timestamps are ISO 8601 UTC | DECISION D-18 |
| Lists | `?page=1&page_size=25` (maximum 200), `?sort=-created_at,stock_no`, `?q=search`, field filters `?status=AVAILABLE&make=Toyota`. Response: `{ "items": [...], "page": 1, "page_size": 25, "total": 312 }` | FACT (server-side pagination) |
| Money-command response | `201 { "document": {...}, "journal_entries": [{ "id", "entry_no": 1042 }], "warnings": [...] }` | FACT ("return the created document with its journal entry number") |
| Preview | Every money command has a `POST …/preview` twin (where noted) that runs validation and posting-rule generation **without** committing. It returns `{ "summary_ar", "summary_en", "effects": [{ "label_key", "account_label", "direction": "IN"/"OUT"/"OWED_TO_US"/"WE_OWE", "amount" }], "warnings": [...] }`. It powers the plain-language preview (SPEC §9.3). Raw Dr/Cr lines are included only if the caller has `journal.view` | DECISION D-31 |
| Masking | Response models are selected by permission (e.g. `VehicleOut` vs `VehicleWithCostOut`). Fields are **absent**, not null, when masked | FACT / DECISION |
| Errors | `{"error": {"code": "VEHICLE_ALREADY_SOLD", "message": "…", "details": {}}}`. `message` is English for logs; the UI translates `code` | FACT |
| Versioning | Breaking changes go to `/api/v2`; additive changes are allowed in v1 | DECISION |

Endpoint status codes: `200` read, `201` created/posted, `204` no content, `400` malformed or missing header, `401` bad token, `403` permission, `404` not found **in this tenant**, `409` state conflict, `422` validation/business rule, `423` tenant read-only, `429` rate limit.

---

## 2. Error code catalogue (initial)

| Code | HTTP | Meaning |
|---|---|---|
| `AUTH_INVALID_TOKEN` | 401 | JWT missing, expired or invalid |
| `TENANT_HEADER_MISSING` | 400 | No `X-Tenant-Id` |
| `TENANT_ACCESS_DENIED` | 403 | No active membership (identical whether or not the tenant exists) |
| `PERMISSION_DENIED` | 403 | `details.permission` names the missing permission |
| `TENANT_READ_ONLY` | 423 | Subscription suspended |
| `PLAN_LIMIT_REACHED` | 422 | `details.limit`: users, branches or vehicles in stock |
| `FEATURE_DISABLED` | 403 | Feature flag off (installments, consignment, multi-branch, car-level investors) |
| `IDEMPOTENCY_KEY_REQUIRED` / `IDEMPOTENCY_KEY_REUSED` / `IDEMPOTENCY_IN_PROGRESS` | 400 / 409 / 409 | |
| `VALIDATION_ERROR` | 422 | `details.fields: {field: [codes]}` |
| `MONEY_PRECISION` | 422 | More than 2 decimals |
| `NOT_FOUND` | 404 | |
| `PERIOD_LOCKED` | 422 | `details.period: "2026-09"` |
| `ENTRY_UNBALANCED` | 500→422 | Should be impossible; signals a posting-rule bug and is alerted to Sentry |
| `ENTRY_ALREADY_REVERSED` / `ENTRY_IS_REVERSAL` | 409 | |
| `CASH_INSUFFICIENT` | 422 | Cash box would go negative and the policy is BLOCK. Under WARN, the response is 201 with `warnings: ["CASH_NEGATIVE"]` |
| `VEHICLE_ALREADY_SOLD` | 409 | Business rule 1 |
| `VEHICLE_INVALID_TRANSITION` | 409 | `details.from`, `details.to` |
| `VEHICLE_VIN_DUPLICATE` | 409 | Active vehicle with the same VIN in the tenant |
| `VEHICLE_NOT_OWNED` / `VEHICLE_NOT_CONSIGNED_IN` | 422 | Operation needs a specific ownership type |
| `VEHICLE_ALREADY_PURCHASED` | 409 | |
| `SALE_NOT_DRAFT` / `SALE_CANCELLED` | 409 | Business rule 2 |
| `SALE_AMOUNTS_MISMATCH` | 422 | Payments + deposit + trade-in + receivable ≠ sale price |
| `PAYMENT_EXCEEDS_OUTSTANDING` | 422 | Business rule 3 (unless `as_customer_credit=true`, after Q-13) |
| `RESERVATION_NOT_ACTIVE` | 409 | |
| `INSTALLMENT_SCHEDULE_MISMATCH` | 422 | Σ schedule ≠ financed amount |
| `PAPER_INVALID_TRANSITION` | 409 | Deferred paper status |
| `SHARES_NOT_100` | 422 | `details.date`, `details.total` |
| `PARTNER_INACTIVE` | 422 | |
| `PARTNER_INVALID` | 422 | Unknown, archived or another showroom's partner |
| `SHARE_DATE_INVALID` | 422 | New batch not after the latest change (D-64) |
| `REPAYMENT_EXCEEDS_LOAN` | 422 | More than is owed (D-63) |
| `PARTNER_NOT_SETTLED` | 409 | Archive refused: open share or balance (D-62) |
| `PARTNER_ALREADY_LINKED` | 409 | Partner already linked to another user (D-66) |
| `VEHICLE_INVALID_TRANSITION` | 409 | `details.from`, `details.to`; also raised by the database (SR020) |
| `VEHICLE_NOT_AVAILABLE` / `VEHICLE_RESERVED` / `VEHICLE_ARCHIVED` | 409 | The car's status does not allow the action |
| `VEHICLE_HAS_COST` | 409 | A car with recorded cost cannot be archived (D-70) |
| `VEHICLE_COST_MISSING` | 422 | Record the purchase before selling (business rule 5) |
| `VIN_INVALID` | 422 | |
| `CUSTOMER_PHONE_EXISTS` | 409 | `details.customer_id`, `details.name` (D-68) |
| `PHONE_INVALID` / `CUSTOMER_INVALID` / `SUPPLIER_INVALID` / `LOCATION_INVALID` | 422 | |
| `PAYMENT_EXCEEDS_BALANCE` / `REFUND_EXCEEDS_CREDIT` / `NOTHING_OWED` | 422 | More than is owed (D-79) |
| `PURCHASE_PAYMENTS_EXCEED_PRICE` | 422 | |
| `RESERVATION_NOT_ACTIVE` / `RESERVATION_MISMATCH` | 409 / 422 | |
| `SALE_NOT_POSTED` / `SALE_DISCOUNT_INVALID` | 409 / 422 | |
| `SALE_DELIVERED` / `SALE_TRADE_IN_USED` | 409 | Cancellation refused (Q-30, D-76) |
| `USE_DOCUMENT_ACTION` / `PURCHASE_HAS_PAYMENTS` | 409 | Journal reversal refused; use the sale or deposit screen (D-75) |
| `UPLOAD_INVALID` / `UPLOAD_MISSING` / `STORAGE_UNAVAILABLE` | 422 / 422 / 503 | Signed-URL uploads (D-74) |
| `ENCRYPTION_UNAVAILABLE` | 503 | `NATIONAL_ID_KEY` not configured |
| `CONSIGNMENT_TERMS_INVALID` | 422 | |
| `DISTRIBUTION_PERIOD_OVERLAP` | 409 | Period already distributed |
| `IMPORT_NOT_VALIDATED` / `IMPORT_HAS_ERRORS` | 409 / 422 | |
| `REASON_REQUIRED` | 422 | Reversal, cancellation, unlock |
| `RATE_LIMITED` | 429 | |
| `INTERNAL_ERROR` | 500 | Generic; includes `request_id`, never a stack trace |

---

## 3. Endpoints

Legend: 💰 money-moving (Idempotency-Key, transaction, journal entry); 👁 preview twin available; **Perm** = required permission(s).

### 3.1 Session and tenant

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| GET | `/me` | authenticated | → `{ user: {id, email, phone, full_name, locale}, memberships: [{tenant_id, tenant_name_ar, tenant_name_en, role_code, permissions: [..], partner_id, subscription_status, feature_flags: {..}}] }` |
| GET | `/tenant` | member | → profile + settings (masked by permission) |
| PATCH | `/tenant/profile` | `tenant.settings.manage` | `{name_ar, name_en, commercial_reg_no, tax_reg_no, address, phones, logo_path, timezone, default_language, digit_style, fiscal_year_start_month}` → profile |
| PATCH | `/tenant/settings` | `tenant.settings.manage` | `{cash_negative_policy, aging_thresholds, attention_thresholds, expected_cost_categories, partner_sees_summary, sale_post_permission_mode, installment_markup_mode, profit_policy}` → settings |
| CRUD | `/branches`, `/locations` | `tenant.settings.manage` (write), member (read) | |
| CRUD | `/cash-accounts` | `tenant.settings.manage` | `{kind: CASH_BOX/BANK, name, branch_id, bank_name, iban, is_default}` → creates the ledger sub-account automatically |
| CRUD | `/expense-categories`, `/payment-methods` | `tenant.settings.manage` | General categories create a 62xx ledger account |
| GET/POST | `/users`, `/users/invite` | `users.manage` | `{email or phone, role_code, partner_id?}` → invitation |
| PATCH/DELETE | `/users/{membership_id}` | `users.manage` | Role change or disable (audit-logged) |
| POST | `/support-access` | `support.grant` | `{hours: 1-72, reason}` → grant (audit-logged) |
| DELETE | `/support-access/{id}` | `support.grant` | Revoke |

### 3.2 Ledger core

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| GET | `/ledger-accounts` | `journal.view` | Chart of accounts tree with derived balances `?as_of=` |
| GET | `/journal-entries` | `journal.view` | Filters: date range, source_type, account, entry_no, subledger ids |
| GET | `/journal-entries/{id}` | `journal.view` | Header + lines + reversal links |
| POST | `/journal-entries/{id}/reverse/preview` | `journal.reverse` | `{reason, reversal_date?}` → plain-language preview (added in Phase 2) |
| POST 💰 | `/journal-entries/{id}/reverse` | `journal.reverse` | `{reason (required), reversal_date?}` → reversal entry (rule 24). Reversing a document's entry also marks the document `REVERSED` |
| GET | `/periods` | `cash.view` | `[{month, status, locked_at, locked_by}]` |
| POST | `/periods/{yyyy-mm}/lock` | `period.lock` | `{}` → period |
| POST | `/periods/{yyyy-mm}/unlock` | `period.unlock` (owner only) | `{reason}` → period (audit-logged) |
| GET | `/cash-accounts/balances` | `cash.view` | `[{cash_account_id, name, kind, balance}]` |
| POST 💰👁 | `/transfers` | `cash.transact` | `{date, from_cash_account_id, to_cash_account_id, amount, notes}` → rule 21 |
| POST 💰👁 | `/general-expenses` | `cash.transact` | `{date, category_id, amount, description, funding: {type: CASH_ACCOUNT, cash_account_id} \| {type: SUPPLIER_CREDIT, supplier_id} \| {type: PARTNER, partner_id, mode: CURRENT_ACCOUNT\|LOAN}, attachment_ids[]}` → rule 20 / 31 / 30 |
| POST 💰👁 | `/other-incomes` | `cash.transact` | `{date, amount, description, cash_account_id}` → **P-01, blocked until Q-26 is approved** |
| GET | `/suppliers` … CRUD | `supplier.manage` | |
| POST 💰👁 | `/suppliers/{id}/payments` | `supplier.pay` | `{date, amount, cash_account_id, notes}` → rule 32 |

### 3.3 Partners

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| GET | `/partners` | `partner.view_all` | List with current % and summary balances |
| POST/PATCH | `/partners`, `/partners/{id}` | `partner.equity.change` | Master data (name, phone, national_id, notes) |
| GET | `/partners/shares?as_of=` | `partner.view_all` | Active shares on a date |
| POST | `/partners/shares` | `partner.equity.change` | `{effective_from, shares: [{partner_id, percentage}]}` → **a batch that must sum to 100.0000** (D-21) |
| GET | `/partners/shares/history` | `partner.view_all` (or own rows) | Every share row, newest batch first |
| GET | `/partners/{id}/national-id` | `partner.equity.change` | Full number; audit-logged (D-65) |
| POST 💰👁 | `/partners/{id}/transactions` (+ `/preview`) | `partner.transact`; `CAPITAL_WITHDRAWAL` also `partner.equity.change` | One endpoint for all seven movements (as built; replaces the per-rule paths of the design). `type` = `CONTRIBUTION` (rule 1), `CAPITAL_WITHDRAWAL` (2), `DRAWING` (3), `LOAN_TO_PARTNER` (4), `LOAN_TO_PARTNER_REPAYMENT` (5), `LOAN_FROM_PARTNER` (28), `LOAN_FROM_PARTNER_REPAYMENT` (29). Warnings `DRAWING_EXCEEDS_BALANCE`, `CAPITAL_NEGATIVE` (D-63) |
| GET | `/partners/{id}/transactions` | as statement | Posted movements |
| GET | `/partners/{id}/statement?from=&to=&format=json\|pdf\|xlsx` | `partner.view_all` or (`partner.view_own` and own id) | → `{partner, opening: {capital, current, loans_to, loans_from, net}, lines: [{date, entry_no, description, bucket: CAPITAL\|CURRENT\|LOAN_TO\|LOAN_FROM, amount_in, amount_out, running_net}], closing: {...}}` |
| GET | `/partners/summary?as_of=` | `partner.view_all` | `[{partner_id, name, percentage, capital, allocated_profit, drawings, loans_outstanding, loans_from_partner, net_balance}]` |

### 3.4 Vehicles

As built in Phase 4. Every vehicle response passes through cost masking (ARCHITECTURE §5): without `vehicle.view_cost` the keys `cost`, `total_cost`, `cost_complete`, `missing_categories`, `profit` and `purchase` are absent (not null); without `vehicle.view_min_price`, `min_price` is absent.

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| GET | `/vehicles` | `vehicle.view` | Filters: `status` (repeatable), `make`, `year`, `location_id`, `ownership_type`, `aging` (FRESH/AGING/OLD/STALE), `q` (stock no., plate, VIN, make/model), `sort`, page. Rows: `days_in_stock`, `aging`, first photo URL; with cost permission `total_cost`, `cost_complete` |
| POST | `/vehicles` | `vehicle.manage` | Master data → vehicle file (DRAFT, stock no. `V-YYYY-NNNN`). `min_price` needs `vehicle.view_min_price` |
| GET | `/vehicles/{id}` | `vehicle.view` | Vehicle file: details, status/location/price history, photos (signed URLs), documents (cost-sensitive ones only with `vehicle.view_cost`), active reservation, posted sale, days in stock. With `vehicle.view_cost`: `purchase`, `cost {total_cost, lines, cost_complete, missing_categories}`, `profit {sale_price, cost, gross_profit, profit_pct, estimate}` |
| PATCH | `/vehicles/{id}` | `vehicle.manage` | Master data only; price changes are recorded in the price history |
| POST | `/vehicles/{id}/status` | `vehicle.manage` | `{status, reason?}`. Allowed directly: DRAFT→IN_PREPARATION, IN_PREPARATION→AVAILABLE, SOLD→DELIVERED, DRAFT/IN_PREPARATION/AVAILABLE→ARCHIVED (D-70). RESERVED, SOLD, back to AVAILABLE after a sale, AT_OTHER_SHOWROOM and RETURNED_TO_OWNER only through their commands |
| POST | `/vehicles/{id}/move` | `vehicle.manage` | `{location_id, reason?}` |
| POST 💰👁 | `/vehicles/{id}/purchase` (+ `/preview`) | `vehicle.purchase` | `{seller_customer_id, purchase_date, price, payments: [{cash_account_id, amount}], ready_for_sale}`; the unpaid part is owed to the seller → rules 6/7 |
| POST 💰👁 | `/vehicles/{id}/seller-payments` (+ `/preview`) | `vehicle.purchase` + `cash.transact` | `{payment_date, amount, cash_account_id}` → rule 8; at most what is owed |
| GET | `/vehicles/{id}/expenses` | `vehicle.view_cost` | Expense documents |
| POST 💰👁 | `/vehicles/{id}/expenses` (+ `/preview`) | `vehicle.expense.record` | `{expense_date, category_id, amount, funding: CASH_ACCOUNT\|SUPPLIER_CREDIT\|PARTNER, cash_account_id\|supplier_id\|paid_by_partner_id+partner_funding_mode}` → rule 9 / 31 / 30; on a sold car P-04 (cost of sales). Consigned-in cars (rule 10) arrive in Phase 6 |
| POST | `/vehicles/{id}/media/upload-url` | `vehicle.manage` | `{content_type, size_bytes}` → `{upload_url, storage_path}` (15 min); then `POST /vehicles/{id}/media {storage_path, content_type, size_bytes}`; `DELETE /vehicles/{id}/media/{media_id}` archives |
| POST | `/documents/upload-url`, `/documents` | per entity (`vehicle.manage`, `customer.manage`, `sale.draft`, `supplier.manage`; cost documents also `vehicle.view_cost`) | Same two-step upload; `GET /documents?entity_type=&entity_id=`, `GET /documents/{id}/url` (5 min), `DELETE /documents/{id}` |
| GET/POST/PATCH | `/locations` | read: `vehicle.view`; write: `tenant.settings.manage` | Yard, outdoor lot, workshop, external showroom, with customer |
| GET | `/search?q=` | `vehicle.view` or `customer.view` | `{vehicles: [{id, stock_no, label, plate_no, vin, status}], customers: [{id, name, phone_primary}]}`; no cost data |
| POST | `/vehicles/{id}/consign-out`, `/return-from-external` | `consignment.manage` | ⏳ Phase 6 |

### 3.5 Customers, suppliers, requests, follow-ups

**As built (D-68):** customers are written through the API (phone normalisation, duplicate check, national-ID encryption), not directly through Supabase.

| Method | Path | Perm | Notes |
|---|---|---|---|
| GET | `/customers?q=&role=` | `customer.view` | `q` matches name or phone digits ("0100 12" finds +2010012…); paginated |
| POST / PATCH | `/customers`, `/customers/{id}` | `customer.manage` | `{name, phone, other_phones, national_id?, address, notes}`; phone stored as E.164; an existing phone → `409 CUSTOMER_PHONE_EXISTS` with the existing customer's id |
| GET | `/customers/{id}` | `customer.view` | `{customer, balances?: {deposits_held, credit_owed} (cash.view), seller_payables?: [...] (vehicle.view_cost)}` |
| GET | `/customers/{id}/national-id` | `customer.view_national_id` | Unmasked; audit-logged |
| POST 💰👁 | `/customers/{id}/refunds` (+ `/preview`) | `cash.transact` | Refund of customer credit (P-02 refund leg); at most what is owed |
| GET / POST / PATCH | `/suppliers`, `/suppliers/{id}` | `supplier.manage` | With `balance` (owed to the supplier) |
| GET | `/suppliers/{id}/statement?date_from=&date_to=` | `supplier.manage` | Opening, lines, running balance |
| POST 💰👁 | `/suppliers/{id}/payments` (+ `/preview`) | `supplier.pay` | Rule 32; at most what is owed |
| GET | `/customers/{id}/summary`, `/vehicles/{id}/matches`, `/request-matches/{id}/contacted` | `request.manage` | ⏳ Phase 6 |

### 3.6 Reservations and sales

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| GET | `/reservations?status=&vehicle_id=` | `sale.view` or `reservation.manage` | With derived `expired` |
| POST 💰👁 | `/reservations` (+ `/preview`) | `reservation.manage` | `{vehicle_id, customer_id, reservation_date, deposit_amount, cash_account_id, expires_on?}` → rule 11; vehicle → RESERVED |
| POST 💰👁 | `/reservations/{id}/settle` (+ `/preview`) | `reservation.manage` | `{action: REFUND\|FORFEIT, settle_date, cash_account_id?}` → rule 34 / 35 (whole deposit, D-72); vehicle → AVAILABLE if still reserved |
| GET | `/sales?status=&q=&date_from=&date_to=` | `sale.view` | Sales staff see posted sales and their own drafts |
| POST / PUT / DELETE | `/sales`, `/sales/{id}` | `sale.draft` | Draft: `{vehicle_id, buyer_customer_id, sale_date, list_price, discount, reservation_id?, payments: [{cash_account_id, amount, payment_method_id?, reference?}], trade_in?: {make, model, year, vin, plate_no, …, agreed_value}, notes}`; response has `remaining`. Drafts only; sales staff edit only their own |
| GET | `/sales/{id}` | `sale.view` | `profit` only with `vehicle.view_cost` |
| POST 👁 | `/sales/{id}/post/preview` | `sale.post` | Plain-language preview (profit only with cost permission) |
| POST 💰 | `/sales/{id}/post` | `sale.post` | Rule 12/26 + cost entry (D-28); vehicle → SOLD; deposit applied; trade-in car created with its own cost file; invoice number assigned (D-77). Installment and deferred sales arrive in Phase 5 |
| POST 💰👁 | `/sales/{id}/cancel` (+ `/preview`) | `sale.cancel` | `{reason, cancel_date?}` → the tenant's method (D-41): REFUND_LIABILITY (P-03) or MIRROR (rule 33); vehicle → AVAILABLE |
| GET | `/sales/{id}/document?kind=invoice\|contract&lang=ar\|en` | `sale.view` | PDF (D-56, D-80) |
| POST 💰 | `/sales/external` | `consignment.manage` + `sale.post` | ⏳ Phase 6 (rule 18) |

### 3.7 Installments and deferred papers

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| POST | `/installment-plans/preview-schedule` | `sale.draft` | `{amount, count, frequency, first_due_date}` → `[{seq, due_date, amount}]` (remainder on the last installment) |
| GET | `/installments?state=DUE\|OVERDUE\|PAID&from=&to=&customer_id=` | `installment.view` | `[{id, customer, vehicle, seq, due_date, amount_due, paid, remaining, days_late, state, paper}]` |
| GET | `/installments/calendar?month=` | `installment.view` | Per-day buckets by state |
| POST 💰👁 | `/customers/{id}/receipts` | `installment.collect` | `{date, amount, cash_account_id, deferred_paper_id?, allocations?: [{installment_id, amount}]}`. Default allocation: oldest due first → rule 15. The spec endpoint `POST /installments/{id}/payments` is kept as a shortcut for a single installment |
| GET/POST | `/deferred-papers` | `deferred_paper.manage` | Register list/create (filters: type, status, due range) |
| POST | `/deferred-papers/{id}/transitions` | `deferred_paper.manage` | `{to_status: DEPOSITED\|COLLECTED\|BOUNCED\|RETURNED\|DEFAULTED\|LEGAL, date, cash_account_id?, reason?}`. `COLLECTED` posts rule 15 via a receipt (💰); `BOUNCED` after `COLLECTED` posts rule 27 (💰) and flags the customer |

### 3.8 Consignment

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| POST | `/consignments-in` | `consignment.manage` | `{vehicle: {...VehicleCreate}, consignor_id, agreement_date, end_date, terms_type, net_price_to_owner?, commission_value?, expenses_borne_by, attachment_ids}` → consignment + vehicle (CONSIGNED_IN) |
| GET | `/consignments-in/{id}/statement?format=` | `consignment.manage` | Consignor statement |
| GET | `/consignments-in/{id}/agreement?format=pdf` | `consignment.manage` | Printable Arabic agreement |
| POST 💰👁 | `/consignments-in/{id}/settle` | `consignment.settle` | `{date, amount, cash_account_id}` → rule 17 |
| POST 💰 | `/consignments-in/{id}/return` | `consignment.settle` | `{date, recoverable_settlement?: {amount, cash_account_id}}` → RETURNED_TO_OWNER (+ P-06 once approved) |
| GET/CRUD | `/external-showrooms` | `consignment.manage` | |
| POST 💰👁 | `/external-showrooms/{id}/collections` | `consignment.settle` | `{date, amount, cash_account_id}` → rule 19 |
| GET | `/external-showrooms/{id}/statement?format=` | `consignment.manage` | |

### 3.9 Profit distribution

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| POST | `/profit-distributions/preview` | `profit.distribute` | `{period_from, period_to}` → `{net_profit, breakdown: {revenue, cogs, expenses}, partners: [{partner_id, name, weighted_pct, amount}], rounding_adjustment, warnings}` |
| POST 💰 | `/profit-distributions` | `profit.distribute` | Same body → rules 23 + 22, with both entry numbers |
| GET | `/profit-distributions` | `partner.view_all` | History |

### 3.10 Reports

`GET /reports/{report}?format=json|pdf|xlsx&lang=ar|en&from=&to=&...` (FACT). Every report applies masking.

| `report` | Perm | Notes |
|---|---|---|
| `dashboard` | `dashboard.view` (+`dashboard.financial` for cash/partner blocks) | |
| `needs-attention` | `dashboard.view` | Alerts filtered by permission |
| `partner-statement`, `partners-summary` | see §3.3 | |
| `cash-book` (`cash_account_id`) | `cash.view` | Opening, movements, running balance, closing |
| `vehicle-profit` | `vehicle.view_cost` | |
| `inventory-aging` | `vehicle.view` (cost columns with `vehicle.view_cost`) | Buckets 0–30 / 31–60 / 61–90 / 90+ |
| `installments` | `installment.view` | |
| `deferred-papers` | `deferred_paper.manage` | |
| `consignment-in`, `consignment-out` | `consignment.manage` | |
| `general-expenses` | `cash.view` | By category |
| `profit-and-loss` | `report.financial` | Owner-friendly wording; excludes closing entries |
| `trial-balance`, `general-ledger` | `journal.view` | |
| `balance-check` | `journal.view` | Assets = liabilities + equity (C-07) |
| `audit-log` | `audit.view` | |

### 3.11 Imports

| Method | Path | Perm | Request → Response |
|---|---|---|---|
| GET | `/imports/templates/{kind}` | `import.run` | xlsx template |
| POST | `/imports` | `import.run` | multipart `{kind, file, go_live_date}` → `{id, detected_columns, sample_rows, suggested_mapping}` |
| POST | `/imports/{id}/mapping` | `import.run` | `{column_map, save_as?}` |
| POST | `/imports/{id}/validate` | `import.run` | → `{ok_rows, error_rows, rows: [{row_no, errors: [{field, code}]}]}` |
| POST 💰 | `/imports/{id}/commit` | `import.run` | All or nothing; posts the opening entry (rule 25) → `{created: {...}, opening_entry_no}` |

### 3.12 Notifications and jobs

| Method | Path | Perm | Notes |
|---|---|---|---|
| GET | `/notifications?unread=true` | member | Also readable through Supabase |
| POST | `/notifications/read` | member | `{ids}` or `{all: true}` |
| — | worker jobs | system | `installment_reminders` (daily, default 2 days ahead plus overdue), `license_expiry`, `aging_alerts`, `follow_up_due`, `tenant_nightly_export` |

### 3.13 Platform (super admin), `/api/v1/admin/*`, no `X-Tenant-Id`

| Method | Path | Perm | Notes |
|---|---|---|---|
| GET/POST/PATCH | `/admin/tenants` | `platform.tenants.manage` | List with plan, status, usage; create tenant (also self-serve signup via `POST /signup`) |
| GET/PATCH | `/admin/plans`, `/admin/feature-flags` | `platform.tenants.manage` | |
| POST | `/admin/tenants/{id}/subscription` | `platform.billing.manage` | Change status (trial/active/past_due/suspended) |
| POST | `/admin/invoices/{id}/mark-paid` | `platform.billing.manage` | Manual billing |
| POST | `/admin/tenants/{id}/support-session` | `platform.support.access` | Only with an active tenant grant; returns a short-lived scoped token; audit-logged |

### 3.14 Health

`GET /healthz`, `GET /readyz`, `GET /metrics` (internal network only).
