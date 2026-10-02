## 0. Your Role and How to Work

You are a senior full-stack engineer and accounting-systems architect. You will build a production-grade, multi-tenant SaaS for car showrooms, starting with Egypt and Qatar.

Working rules:

1. **Work in phases** (Section 13). Finish one phase, with passing tests, before starting the next. At the end of each phase, summarize what was built, what was tested, and any open decisions.
2. **Never guess business rules.** If something in this spec is ambiguous or marked `OPEN QUESTION`, implement the configurable/default behavior described and list the question in `docs/DECISIONS.md`. Do not invent accounting rules.
3. **Money correctness beats everything.** No floating-point money. No edits or deletes of posted financial entries. Every money-moving operation is atomic and tested.
4. **Tests first for the ledger.** Write unit tests for every posting rule (Section 7) before writing the endpoint.
5. **Keep it simple for the end user.** The owners are non-accountants who currently use Excel. The UI must feel as simple as a spreadsheet; the double-entry accounting stays hidden underneath.
6. Write clean, typed, documented code. Prefer boring, proven solutions.
7. In design documents and phase summaries, label statements as **FACT / ASSUMPTION / DECISION / OPEN QUESTION**.
8. For every feature ask: *does this help the owner make money, protect cash, reduce mistakes, save time, or control the business?* If not, defer it.
9. Do not refactor unrelated code while building a feature, and do not swap parts of the stack because another tool is fashionable.

**Golden rule:** give the showroom owner one reliable picture of the vehicles, the money, the customers, and the real profit.

---

## 1. Product Context

Working product name: **SayyaraDMS (سيارة)**, a placeholder. Keep the name in one config constant so it can change.

### 1.1 The problem (from real customer discovery)

Interviews with a used-car showroom in Egypt revealed:

- **The #1 pain is financial, not marketing.** The showroom is funded by **several partners**, each owning a **percentage share** of capital. Partners **withdraw money or borrow against their share**. Many cash movements happen daily. Everything is tracked in **one Excel sheet**, and nobody can quickly and confidently answer: *what came in, what went out, what is the cash balance, and what is each partner's balance?*
- Each car is recorded from purchase to sale: model, color, year, chassis number (VIN), plate number, seller details, purchase price, all preparation expenses, buyer details, sale price.
- **Two-way consignment exists:** other people's cars are displayed and sold in this showroom, AND this showroom's cars are displayed in other showrooms.
- **Installment sales exist**, backed by **promissory notes (إيصالات أمانة)** and deferred payments. Payment reminders are wanted.
- Customers ask for cars that are not in stock; recording these requests and getting notified when a matching car arrives is wanted.
- There are **no sales commissions**. Occasional tips (إكرامية) are treated as expenses.
- Customer contact is by **phone calls**, not chat. Ads are run by an outside agency.
- Invoices and taxes exist (Egypt e-invoice / e-receipt system).

The product must let the owner answer at a glance: How much cash do I have, and where? What is my stock worth at cost? Who owes me, and what do I owe? What is each partner's position? Which cars made or lost money? Which cars have sat too long? What needs my attention today?

### 1.2 Target users (roles)

| Role | Description |
|---|---|
| Owner / Managing Partner | Full access, approves sensitive operations, sees everything |
| Manager | Day-to-day operations and finance as granted; cannot change settings, partner equity, or unlock periods |
| Partner | Read-only view of own statement, own balance, overall showroom summary (configurable) |
| Accountant | Records all financial transactions, runs reports, cannot change settings |
| Sales / Showroom staff | Manages vehicles, customers, requests; records sales drafts; no access to partner accounts. **Must never see purchase price, vehicle expenses, total cost, minimum price, or profit** (field-level masking, Section 10) |
| Viewer | Read-only |
| Platform Super Admin | (Our company) manages tenants, plans, support. Never sees tenant financial data unless granted support access, and access is audit-logged |

Authorization is **permission-based**: roles are bundles of permissions (e.g. `vehicle.view_cost`, `sale.post`, `journal.reverse`, `partner.view_all`). Code checks permissions, never role names, so tenants can customize roles later.

### 1.3 Markets

- **Phase 1:** Egypt (EGP) and Qatar (QAR).
- **Later:** UAE (AED), Saudi Arabia (SAR), Sudan (SDG).
- The design must make adding a country a matter of **configuration** (currency, tax rules, invoice format, language defaults), not code rewrites.

### 1.4 Explicitly OUT of scope for the MVP

WhatsApp chat CRM, marketplace multi-posting, sales commissions module, public marketplace website, AI pricing. Design so they can be added later, but do not build them now. Also do not build: payroll/HR, workshop or spare-parts management, insurance, a general-purpose ERP, a website builder, native iOS/Android apps, microservices, Kubernetes, GraphQL, or event-driven infrastructure.

**Discovery principle:** the financial pain comes from early interviews and must keep being validated with more showrooms. Keep modules loosely coupled so priorities can shift with real feedback.

---

## 2. Tech Stack (fixed)

| Layer | Technology |
|---|---|
| Frontend | **Angular** (latest stable, standalone components, signals, strict TypeScript), **PrimeNG** UI components, **PWA** via `@angular/pwa` |
| i18n | Runtime language switching (use **Transloco** or ngx-translate). Arabic (default, RTL) and English (LTR) |
| Backend API | **Python 3.12+, FastAPI**, Pydantic v2, SQLAlchemy 2.x (or asyncpg + typed queries), Alembic **not** used; migrations live in Supabase |
| Database / Auth / Storage | **Supabase**: PostgreSQL, Supabase Auth, Supabase Storage, Row Level Security |
| Migrations | Supabase CLI SQL migrations in `supabase/migrations/`: the single source of truth for tables, RLS policies, functions and triggers. Do not add Alembic; two migration systems would drift |
| PDF reports | Server-side (WeasyPrint with Arabic font support, e.g. Noto Naskh Arabic / Cairo / Tajawal) |
| Excel import/export | `openpyxl` on the backend |
| Testing | `pytest` (backend + accounting), Angular unit tests, **Playwright** E2E |
| CI | GitHub Actions: lint, type-check, tests, migration check |
| Containerization | Docker for the FastAPI service |

---

## 3. Architecture

### 3.1 Responsibility split (critical)

```
Angular PWA
   │
   ├── Supabase JS client ──► Auth (login, session, password reset)
   │                         Simple READS and non-financial CRUD
   │                         (vehicles master data, customers, requests, documents)
   │                         Protected by RLS.
   │
   └── FastAPI (JWT from Supabase) ──► ALL money-moving operations
                                     (purchases, expenses, sales, payments,
                                      partner transactions, consignment settlement,
                                      profit distribution, reversals, period close)
                                     Reports, PDF, Excel import/export,
                                     scheduled jobs (reminders), integrations.
```

**Rule:** The browser must NEVER insert, update or delete rows in financial tables directly. Enforce this with RLS: financial tables get `SELECT` policies for authorized roles only; no `INSERT/UPDATE/DELETE` policies for the `authenticated` role. FastAPI writes using a dedicated database role, always inside a transaction, always with explicit `tenant_id` checks.

### 3.2 Multi-tenancy

- Shared database, shared schema, `tenant_id uuid not null` on every tenant-owned table.
- A `memberships(user_id, tenant_id, role, partner_id null)` table links users to tenants. A user may belong to more than one tenant (e.g. a partner in two showrooms) and switches tenant in the UI.
- RLS on every tenant table: access only if a membership exists for `auth.uid()` and `tenant_id` with an allowed role. Write SQL helper functions (`is_member(tenant_id)`, `has_role(tenant_id, roles[])`) and reuse them.
- FastAPI validates the Supabase JWT, resolves the active tenant from a header (`X-Tenant-Id`), verifies membership and role, and sets `app.tenant_id` / `app.user_id` session settings for auditing.
- **Write automated tests proving cross-tenant isolation** (user of tenant A cannot read or write tenant B data via Supabase client or API).

### 3.3 General conventions

- UUID primary keys (`gen_random_uuid()`).
- Money: `numeric(18,2)`; quantities/percentages: `numeric(9,4)`. In Python use `Decimal` everywhere. In TypeScript, money values travel as **strings** and are formatted for display only; no arithmetic on money in the frontend except display previews.
- Every table: `created_at`, `created_by`, `updated_at`, `updated_by`.
- Master data uses soft delete (`archived_at`). **Financial records are never deleted or updated after posting.**
- All timestamps `timestamptz` stored in UTC; display in tenant timezone (Africa/Cairo, Asia/Qatar...).
- Dates in Gregorian calendar; Arabic UI may show Arabic-Indic or Western digits (tenant setting).
- Idempotency: all POST endpoints that move money accept an `Idempotency-Key` header; duplicates return the original result.

### 3.4 Business rules catalogue

Keep business rules in the service layer (never only in routers or Angular), list them in `docs/BUSINESS_RULES.md`, and give each one a test. Starting set:
- A vehicle can be sold only once, unless its sale was cancelled.
- No new payments against a cancelled sale.
- A payment cannot exceed the outstanding amount unless the excess is explicitly recorded as customer credit.
- Installment remaining = amount due − payments, always derived.
- Profit uses recorded costs only; manually entered profit is never accepted.
- Active partners' ownership percentages total 100% on every date.
- A cash box cannot go negative unless the tenant setting allows it (warn vs. block).
- No record may reference another tenant's data.
- Posted financial records are corrected only by reversal.

---

## 4. Functional Modules

### 4.1 Tenant setup and settings

- Showroom profile: name (AR/EN), logo, commercial registration, tax registration number, address, phones, country, currency, timezone, fiscal year start, default language, digit style.
- Branches/locations (a showroom may have more than one yard).
- Cash boxes (خزنة) and bank accounts, each linked to a ledger account.
- Expense categories (seeded, editable): maintenance, bodywork, paint, polishing, cleaning, license renewal, transport, inspection, tips (إكرامية), other.
- General expense categories: rent, salaries, utilities, advertising agency, government fees, other.
- Profit distribution policy (see 4.9).
- User management: invite by email/phone, assign role, link a user to a partner record.
- Onboarding wizard: profile → partners and opening capital → cash/bank opening balances → import vehicles from Excel → done.

### 4.2 Partners and capital

- Partner record: name, national ID (optional, stored encrypted or masked), phone, notes, **ownership percentage**, active from/to dates.
- Ownership percentages must total exactly 100% for active partners at any date; changes are effective-dated (history kept, never overwritten).
- Transactions per partner (each posts to the ledger, Section 7):
  - Capital contribution
  - Capital withdrawal (reduces capital)
  - **Drawing from share** (سحب من الحصة / من الأرباح)
  - **Loan / advance to partner** (سلفة) and its repayments
  - **Partner loan to the business** (the partner lends the showroom money) and its repayment
  - **Expense paid personally by a partner** (credited to his current account or recorded as a loan from him, chosen per transaction)
  - Profit allocation (system-generated)
- **Partner statement** (كشف حساب شريك): date range, opening balance, every movement, running balance, closing balance; split into capital, current account (profits − drawings) and loans outstanding. Exportable to PDF/Excel and shareable.
- **Partners balance summary**: one row per partner showing capital, allocated profit, drawings, loans outstanding, net balance, current % share.
- `OPEN QUESTION`: Is partnership only at showroom level, or can a single car have its own investors and percentages? **Design the data model to support car-level investor shares (optional)**, but ship the MVP UI with showroom-level partnership only, behind a feature flag for car-level.

### 4.3 Vehicles (inventory)

Vehicle fields:
- Internal stock number (auto-generated per tenant, e.g. `V-2026-0042`)
- Make, model, trim, year, color (exterior/interior), body type, transmission, fuel, engine capacity, mileage
- **Chassis number (VIN)**: unique per tenant among non-archived vehicles; validate format loosely (Egyptian/older cars may not have a 17-char VIN)
- Plate number, license expiry date, license governorate/city
- Ownership type: `OWNED`, `CONSIGNED_IN` (belongs to someone else, sold on their behalf)
- Acquisition source: `DIRECT_PURCHASE`, `TRADE_IN` (taken from a buyer as part payment, see 4.7), `CONSIGNMENT_IN`, `AUCTION`, `IMPORT`
- Current location with **location history**: own branch/yard, outdoor lot, **workshop**, external showroom (for `CONSIGNED_OUT`), customer (sold, awaiting delivery). Every move records date, from, to, user and reason.
- Asking price, minimum acceptable price (visible to owner/accountant only). Keep **price change history** and show days since the last price change.
- Photos and documents (Supabase Storage, private bucket, signed URLs): license, purchase contract, inspection report, etc. Photos can be captured directly from the phone camera in the PWA during lot inspection and are compressed client-side before upload.
- Notes

Status lifecycle (enforced by a state machine in the backend):

```
DRAFT → IN_PREPARATION → AVAILABLE ⇄ RESERVED → SOLD → DELIVERED
                │              │
                └──────────────┴──► AT_OTHER_SHOWROOM (consigned out) ──► back to AVAILABLE, or SOLD
Any non-sold state → RETURNED_TO_OWNER (consigned-in only) / ARCHIVED
```

Lifecycle statuses are fixed in code because they drive the state machine. Categories, location types, payment methods and thresholds are configurable reference data.

- **Purchase**: seller (customer/dealer record), purchase date, price, payment method(s) (cash box, bank, partly deferred = payable to seller).
- **Vehicle expenses**: date, category, amount, paid from (cash/bank), supplier/workshop (optional), attachment. For OWNED cars these are capitalized into the car's cost.
- **Vehicle card / file (ملف العربية)**: a single screen showing all data, photos, the full cost breakdown (purchase + each expense = total cost), days in stock, status history, and after sale: sale price, buyer, gross profit and profit %.
- **Inventory list**: filters (status, make, year, location, ownership type), columns including total cost, asking price, **days in stock**, with color warnings at configurable thresholds (default 30/60/90 days).
- **Global quick search** (top bar, always available): by chassis number (full or last digits), plate number, make/model, customer name or phone.
- **Cost completeness**: a per-tenant checklist of expected cost categories (e.g. transport, license renewal). If a ready or sold car is missing an expected category, its profit is labeled "estimate, missing: ..." instead of being shown as exact. Never hide missing data.

### 4.4 Consignment IN (other people's cars in our showroom)

- Consignor (owner) record, agreement date, agreed **net price to owner** OR **commission** (fixed amount or %), who pays preparation expenses (owner / showroom / shared), agreement end date, attachment (signed agreement scan).
- Printable **consignment receipt/agreement** in Arabic.
- Expenses paid by the showroom on a consigned car are tracked as **recoverable from the consignor** (not capitalized into our inventory).
- On sale: system computes amount due to consignor = sale price − showroom commission − recoverable expenses; creates a payable to the consignor.
- Consignor settlement payment(s).
- Return car to owner (no sale): settle any recoverable expenses.
- **Consignor statement** (كشف حساب صاحب العربية).

### 4.5 Consignment OUT (our cars in other showrooms)

- External showroom record (name, contact, address).
- Move vehicle to external showroom: date, agreed terms (their commission fixed or %), expected price.
- Track which of our cars are where and for how long.
- When they sell: record sale (price, buyer if known), their commission (expense), and the amount receivable from the external showroom; record collections.
- **External showroom statement**.

### 4.6 Customers and requests

- Customer record: name, phone(s), national ID (optional), address, notes, type (buyer/seller/consignor/all). Phone is the primary key for search (calls are the main channel).
- **Follow-ups (lightweight)**: call, visit, test drive, or note, with date, user, result, **next action and next follow-up date**, assigned salesperson and priority. Customers mainly contact the showroom by phone, so logging a call must take a few taps.
- **Car requests / wanted list (طلبات العملاء)**: customer, make, model, year range, budget range, color preference, notes, status (new / contacted / vehicle found / negotiating / deposit / won / lost / on hold), assigned salesperson, source, financing needed (yes/no), trade-in offered (yes/no).
- **Matching**: when a vehicle becomes AVAILABLE, find open requests that match and show an alert to staff ("3 customers asked for this car") with their phone numbers; record whether they were contacted.

### 4.7 Sales

- Sale draft (staff) → confirm and post (owner/accountant; configurable who can confirm).
- Fields: vehicle, buyer, sale date, sale price, discounts, payment structure:
  - Full cash / bank transfer
  - Down payment + **installments**
  - Mixed (part cash, part bank, part deferred)
  - **Trade-in**: the buyer gives his own car as part payment. Capture the trade-in vehicle (creates a new vehicle record with source `TRADE_IN` and its own cost file) and its agreed value; the agreed value reduces the amount the buyer owes.
- Reservation with deposit (عربون): deposit received before sale; on sale it is applied to the price; on cancellation, refund or forfeit (configurable per case).
- Printable **sale contract / invoice** in Arabic (and English), with tenant logo and details.
- On posting: vehicle → SOLD, ledger postings (Section 7), installment schedule created if applicable.
- **Sale cancellation** (after posting): owner/accountant only, mandatory reason. It reverses the sale entries, returns the vehicle to AVAILABLE, and records any refund or forfeited deposit as separate transactions.

### 4.8 Installments, promissory notes and post-dated cheques

- Schedule generator: number of installments, frequency (monthly default), first due date, amount per installment (equal split with rounding remainder on the last one), or fully manual schedule.
- `OPEN QUESTION`: installment price markup. Support two modes per sale: (a) the installment total is simply the sale price; (b) cash price + financing markup, where the markup is recorded as **deferred income** recognized as installments are collected. Default (a); make (b) available in settings.
- **Deferred papers register (سجل الأوراق الآجلة)** covering two instrument types: **promissory notes (إيصالات أمانة)** and **post-dated cheques (شيكات آجلة)**, which are very common in Qatar and the Gulf. Fields: type, number, customer, amount, issue date, due date, linked installment, physical storage location, scan attachment; for cheques also drawer bank, branch and account holder name. Statuses: held → deposited (cheques) → collected / **bounced** (cheques) / returned to customer / overdue / **defaulted** / in legal process. A bounced cheque reopens the installment balance and flags the customer.
- Record payments against installments (partial payments allowed), from cash or bank.
- When an installment is fully paid, the linked note status can be updated to "returned to customer".
- **Due and overdue dashboard**: due today, due in next N days, overdue with days late, total outstanding per customer. Provide both a list and a **calendar view** ("installment radar"), color-coded: collected, pending, overdue, bounced/defaulted. Default upcoming window: next 48 hours on the main dashboard, 7 days on the installments board.
- **Reminders**: daily scheduled job creates in-app reminders for installments due in X days (default 2) and overdue. Provide a **pluggable notification provider interface** (`SmsProvider`, `WhatsAppProvider`) with a no-op/log implementation in the MVP; real SMS/WhatsApp providers are a later phase.
- Customer installment statement (printable).

### 4.9 Profit calculation and distribution

- Vehicle gross profit = sale revenue − total vehicle cost (purchase + capitalized expenses). Consignment-in profit = commission earned.
- Net profit for a period = all revenues − cost of cars sold − general expenses.
- Distribution policy (tenant setting, `OPEN QUESTION` which one customers use most):
  1. **Periodic** (monthly/quarterly/yearly): owner runs "Close period & distribute profit"; net profit is allocated to partners by their effective ownership % during the period (pro-rate if % changed mid-period).
  2. **Per car on sale**: each car's gross profit is allocated to partners when the sale is posted; general expenses allocated periodically.
- Distribution creates ledger entries crediting each partner's current account. Actual cash payout is a separate "partner drawing" transaction.
- Preview screen before posting the distribution, showing each partner's amount.

### 4.10 Cash, bank and general expenses

- Cash boxes and bank accounts with live balances (computed from the ledger).
- Transfers between cash and bank (deposit cash to bank, withdraw cash from bank).
- **Suppliers / payees** (workshops, transport, parts, ad agency): car and general expenses can be paid immediately or recorded **on credit** as a supplier payable, with supplier statements and payments.
- General (non-car) expenses with category, attachment, paid from (or on credit to a supplier).
- Payment methods (configurable): cash, bank transfer, card, cheque, other; each maps to a cash or bank account.
- Other income (miscellaneous).
- **Cash book / bank book**: date range, opening balance, movements with running balance, closing balance.
- Simple bank reconciliation in a later phase (design table placeholders only).

### 4.11 Reversals, corrections and period locking

- No edit or delete after posting. Corrections are made via **Reverse** (creates an exact opposite journal entry linked to the original, with mandatory reason) and then re-entering the correct transaction.
- Reversal permission: owner/accountant only; audit-logged.
- **Period lock**: owner can lock a month; no posting or reversal dated inside a locked period.
- Drafts (not yet posted) can be edited and deleted freely.

### 4.12 Reports (all with date filters, PDF and Excel export, Arabic-first layout)

1. Dashboard: cash + bank balances, **capital tied up in inventory** (count and total cost of cars in stock), cars over 60 days, this month's sales and gross profit, collections due in the next 7 days, overdue total, and a **partner equity matrix** (per partner: ownership %, capital, allocated profit, drawings, net balance, shown with simple bars).
2. Partner statement and partners summary.
3. Cash book / bank book.
4. Vehicle profit report (per car: cost, sale, profit, days in stock).
5. Inventory report with aging buckets (0–30, 31–60, 61–90, 90+ days).
6. Installments: schedule, due, overdue, collections in period.
7. Promissory notes register.
8. Consignment-in and consignment-out statements.
9. General expenses by category.
10. Profit and loss (simple, owner-friendly wording).
11. Trial balance and general ledger (for an external accountant).
12. Audit log viewer.

### 4.13 Excel import (critical for onboarding)

Customers currently live in Excel. Build an import wizard:

1. Download our template **or** upload their own sheet.
2. **Column mapping** screen (map their columns to our fields; remember the mapping per tenant).
3. Validation preview: show row-by-row errors (missing VIN, invalid date, duplicate) before anything is saved.
4. Import vehicles (with purchase cost and opening expenses as an opening balance), customers, partners with opening balances, open installments with remaining balances.
5. Opening balances are posted as a single, clearly labeled **opening journal entry** dated at the go-live date.

### 4.14 Invoicing and tax (country packs)

- Implement a `CountryPack` abstraction: currency, VAT rate(s), invoice numbering rules, invoice template, e-invoicing adapter.
- **Egypt**: Design an `EgyptETAAdapter` interface for the Egyptian Tax Authority e-invoice / e-receipt system (document submission, signing, status). In the MVP, implement the interface and data fields (tax registration numbers, item codes, invoice UUID/status) with a stub adapter; real integration is a later phase.
- **Qatar**: no VAT currently; simple invoices.
- **Later**: Saudi ZATCA (Fatoorah) phase 2, UAE VAT including the used-car **margin scheme**.
- Tax configuration must be data-driven per tenant.

### 4.15 Audit log

- Every create/update/post/reverse/login/permission change: who, when, tenant, entity, before/after (JSON diff), IP/user agent.
- Append-only table; no role can update or delete it.

### 4.16 SaaS platform layer

- Tenant signup (self-serve with trial, or created by super admin).
- Plans with limits (e.g. number of users, branches, vehicles in stock) and feature flags (installments module, consignment, multi-branch, country pack features).
- Subscription status: trial / active / past due / suspended (read-only mode when suspended; never delete data).
- MVP billing is **manual** (super admin marks invoices paid). Design a `PaymentGateway` interface for later (e.g. Paymob/Fawry in Egypt, local gateways in Qatar).
- Super admin console: tenants list, plan, status, usage, impersonation only with explicit tenant-granted support access (audit-logged).

### 4.17 Needs Attention and notifications

The dashboard opens with a **"Needs Attention" (محتاج متابعة)** panel built from deterministic rules, not AI. Each alert links to the record, and all thresholds are configurable:
- Installments due soon or overdue; bounced cheques
- Cars past aging thresholds; license expiry for cars in stock
- Cars missing expected cost categories
- Cars whose estimated profit is negative or below a threshold
- Customer requests that match available cars
- Follow-ups due today; leads with no follow-up for N days
- Consignment settlements pending; supplier payments due
- Abnormal balances: a cash box below zero, or a partner's drawings exceeding his balance

An in-app notification center (read/unread) delivers the same alerts. Email/SMS/WhatsApp come later through the provider interfaces.

---

## 5. Data Model (core tables)

Create these (names may be refined; document any change). All tenant tables have `tenant_id` + RLS.

```
tenants, tenant_settings, branches, memberships, plans, subscriptions, feature_flags

partners, partner_share_history (partner_id, percentage, effective_from, effective_to)

customers (type flags: buyer, seller, consignor), external_showrooms
customer_requests, customer_request_matches, call_logs

vehicles, vehicle_status_history, vehicle_media, vehicle_documents
vehicle_investors (optional, car-level shares; feature-flagged)
vehicle_expenses
consignments_in (vehicle_id, consignor_id, terms...)
consignments_out (vehicle_id, external_showroom_id, terms...)

sales, sale_payments, reservations (deposits)
installment_plans, installments, installment_payments
promissory_notes

cash_accounts (cash boxes & bank accounts, each → ledger account)
general_expenses, other_incomes, transfers

-- Ledger (the heart of the system)
ledger_accounts (chart of accounts; system + tenant accounts; type: asset/liability/equity/income/expense;
                 optional subledger: partner_id / customer_id / vehicle_id / consignor_id / external_showroom_id)
journal_entries (id, tenant_id, entry_no (sequential per tenant), entry_date, description,
                 source_type, source_id, status: POSTED, reversal_of_id null, reversed_by_id null,
                 period_id, created_by, posted_at)
journal_lines (id, journal_entry_id, ledger_account_id, debit numeric(18,2) >= 0, credit numeric(18,2) >= 0,
               partner_id, customer_id, vehicle_id, consignor_id, external_showroom_id, cash_account_id, memo)
accounting_periods (month, status: OPEN/LOCKED)

profit_distributions, profit_distribution_lines
import_jobs, import_mappings
notifications, reminder_jobs
audit_log
documents (generic attachments)
```

### Ledger integrity (enforce in the database, not only in code)

- Each line: exactly one of debit/credit > 0 (check constraint).
- Each journal entry: sum(debit) = sum(credit) and at least two lines. Enforce with a **deferred constraint trigger** checked at commit.
- `journal_entries` and `journal_lines`: no UPDATE/DELETE allowed (trigger raises exception), except the controlled update of `reversed_by_id` through the reversal function.
- Posting date must be in an OPEN period.
- Sequential `entry_no` per tenant without gaps (use a per-tenant counter row locked with `SELECT ... FOR UPDATE`).
- A single SQL function or Python service `post_journal_entry(...)` is the **only** way to create entries.
- **Balances are always derived** from journal lines (use indexed queries or materialized/summary tables refreshed in the same transaction). Never store an editable balance field.

---

## 6. Chart of Accounts (seed template, Arabic + English names)

```
1000 Assets
  1100 Cash boxes (one sub-account per cash box)
  1200 Bank accounts (one per bank account)
  1300 Vehicle inventory (subledger by vehicle)
  1400 Installment receivables (subledger by customer)
  1410 Other receivables
  1420 Receivable from external showrooms (subledger)
  1430 Recoverable expenses from consignors (subledger)
  1500 Loans/advances to partners (subledger by partner)
2000 Liabilities
  2100 Payable to sellers (deferred purchase price)
  2200 Payable to consignors (subledger)
  2300 Customer deposits (عربون)
  2400 Deferred installment income (markup mode only)
  2500 Taxes payable
  2600 Loans from partners (subledger by partner)
  2700 Payable to suppliers (subledger by supplier)
3000 Equity
  3100 Partner capital (subledger by partner)
  3200 Partner current accounts (profit allocations − drawings; subledger by partner)
  3300 Retained earnings / undistributed profit
  3900 Opening balance equity
4000 Income
  4100 Vehicle sales
  4200 Consignment commission income
  4300 Installment financing income
  4900 Other income
5000 Cost of vehicles sold
6000 Expenses
  6100 Commission paid to external showrooms
  6200.. General expense categories (rent, salaries, utilities, advertising, government fees, tips, other)
```

---

## 7. Posting Rules (implement each as a tested function)

| # | Business event | Debit | Credit |
|---|---|---|---|
| 1 | Partner capital contribution | Cash/Bank | Partner Capital (partner) |
| 2 | Partner capital withdrawal | Partner Capital (partner) | Cash/Bank |
| 3 | Partner drawing from share | Partner Current Account (partner) | Cash/Bank |
| 4 | Loan/advance to partner | Loans to Partners (partner) | Cash/Bank |
| 5 | Partner loan repayment | Cash/Bank | Loans to Partners (partner) |
| 6 | Buy car (paid) | Vehicle Inventory (vehicle) | Cash/Bank |
| 7 | Buy car (partly deferred) | Vehicle Inventory (vehicle) | Cash/Bank + Payable to Seller |
| 8 | Pay seller later | Payable to Seller | Cash/Bank |
| 9 | Expense on OWNED car | Vehicle Inventory (vehicle) | Cash/Bank |
| 10 | Expense on CONSIGNED-IN car paid by showroom | Recoverable from Consignor (consignor) | Cash/Bank |
| 11 | Customer deposit received | Cash/Bank | Customer Deposits |
| 12 | Cash sale of owned car | Cash/Bank (+ Customer Deposits applied) | Vehicle Sales |
|    | and cost recognition | Cost of Vehicles Sold | Vehicle Inventory (vehicle total cost) |
| 13 | Installment sale (mode a) | Cash/Bank (down payment) + Installment Receivable (customer) | Vehicle Sales |
|    | and cost recognition | Cost of Vehicles Sold | Vehicle Inventory |
| 14 | Installment sale (mode b, markup) | Cash/Bank + Installment Receivable (full incl. markup) | Vehicle Sales (cash price) + Deferred Installment Income (markup) |
| 15 | Installment collected | Cash/Bank | Installment Receivable (customer) |
|    | (mode b) recognize markup portion | Deferred Installment Income | Installment Financing Income |
| 16 | Sale of consigned-in car | Cash/Bank / Receivable | Payable to Consignor (full sale price) |
|    | and take commission + recover expenses | Payable to Consignor | Consignment Commission Income + Recoverable from Consignor |
| 17 | Pay consignor | Payable to Consignor | Cash/Bank |
| 18 | Our car sold by external showroom | Receivable from External Showroom | Vehicle Sales |
|    | their commission | Commission to External Showrooms (expense) | Receivable from External Showroom |
|    | cost recognition | Cost of Vehicles Sold | Vehicle Inventory |
| 19 | Collect from external showroom | Cash/Bank | Receivable from External Showroom |
| 20 | General expense | Expense category | Cash/Bank |
| 21 | Cash ↔ bank transfer | Destination | Source |
| 22 | Profit distribution | Retained Earnings / Undistributed Profit | Partner Current Account (each partner by %) |
| 23 | Period close (income summary) | Income accounts | Expense/COGS accounts + Retained Earnings (net) |
| 24 | Reversal of any entry | Mirror of original | Mirror of original |
| 25 | Opening balances (import) | Assets per opening data | Liabilities / Partner Capital / Opening Balance Equity |
| 26 | Sale with trade-in | Cash/Bank/Receivable (remaining amount) + Vehicle Inventory (trade-in vehicle, at agreed value) | Vehicle Sales |
|    | and cost recognition of the sold car | Cost of Vehicles Sold | Vehicle Inventory (sold vehicle) |
| 27 | Post-dated cheque bounced (after being recorded as collected) | Installment Receivable (customer) | Cash/Bank |
| 28 | Partner lends money to the business | Cash/Bank | Loans from Partners (partner) |
| 29 | Business repays partner loan | Loans from Partners (partner) | Cash/Bank |
| 30 | Partner pays a car or general expense personally | Vehicle Inventory / Expense | Partner Current Account or Loans from Partners (partner) |
| 31 | Expense or service on credit | Vehicle Inventory / Expense | Payable to Suppliers (supplier) |
| 32 | Pay supplier | Payable to Suppliers (supplier) | Cash/Bank |
| 33 | Sale cancellation | Reversal of the original sale entries (rules 12/13/26) | Reversal of the original sale entries |
| 34 | Deposit refunded | Customer Deposits | Cash/Bank |
| 35 | Deposit forfeited | Customer Deposits | Other Income |

Required tests, at minimum:
- Every rule balances and hits the correct subledgers.
- Full scenario test: 3 partners contribute capital → buy 3 cars with expenses → sell one cash, one on 6 installments, one consigned out and sold by the other showroom → collect 2 installments → partner drawing and loan → profit distribution → verify cash balance, each partner's balance, inventory value, receivables, and P&L against hand-calculated expected values.
- Sale with trade-in: the sold car's profit is correct, and the trade-in car enters inventory at its agreed value with its own cost file.
- A bounced cheque restores the customer's receivable and the bank balance.
- Reversal returns all balances to the prior state.
- Posting into a locked period fails.
- Unbalanced entry fails at the database level even if the Python check is bypassed.
- Cross-tenant posting attempt fails.

---

## 8. FastAPI Design

- Structure: `app/api/routers`, `app/services` (business logic and posting rules), `app/domain` (Pydantic models, enums, state machines), `app/db` (session, queries), `app/integrations` (country packs, notifications, payment gateways), `app/jobs` (scheduled tasks), `app/reports` (PDF/Excel).
- Auth dependency: verify Supabase JWT (JWKS), load membership for `X-Tenant-Id`, check role per endpoint.
- Command-style endpoints for money movement, e.g.:

```
POST /partners/{id}/contributions
POST /partners/{id}/withdrawals
POST /partners/{id}/drawings
POST /partners/{id}/loans            POST /partners/{id}/loan-repayments
POST /vehicles/{id}/purchase
POST /vehicles/{id}/expenses
POST /vehicles/{id}/consign-out      POST /vehicles/{id}/return-from-external
POST /consignments-in                POST /consignments-in/{id}/settle
POST /reservations                   POST /reservations/{id}/cancel
POST /sales                          POST /sales/{id}/post
POST /installments/{id}/payments
POST /external-showrooms/{id}/collections
POST /general-expenses               POST /transfers
POST /profit-distributions/preview   POST /profit-distributions
POST /journal-entries/{id}/reverse
POST /periods/{month}/lock           POST /periods/{month}/unlock (owner only)
GET  /reports/{report}?format=json|pdf|xlsx&...
POST /imports (upload)  POST /imports/{id}/mapping  POST /imports/{id}/validate  POST /imports/{id}/commit
```

- Every money endpoint: Pydantic validation → permission check → period check → single DB transaction → posting service → audit log → return the created document with its journal entry number.
- Consistent error format, e.g. `{"error": {"code": "VEHICLE_ALREADY_SOLD", "message": "...", "details": {}}}`; the frontend maps codes to Arabic/English messages. Never expose stack traces in production.
- All list endpoints: versioned under `/api/v1`, with server-side pagination, filtering, sorting and search; avoid N+1 queries.
- OpenAPI docs enabled in dev; generate a typed Angular client from the OpenAPI schema.
- Scheduled jobs (APScheduler or a separate worker container): daily installment reminders, license-expiry reminders for vehicles in stock, aging alerts.
- Rate limiting and request size limits; structured JSON logging; health check endpoint.

---

## 9. Angular Frontend

### 9.1 Foundations

- Standalone components, signals for state, lazy-loaded feature routes, strict mode, Reactive Forms for all data entry. Folder structure: `core/` (auth, guards, interceptors, services), `shared/` (components, dialogs, pipes), `features/<domain>/` (dashboard, vehicles, customers, sales, installments, partners, finance, consignments, reports, settings). No global state library unless genuinely needed.
- PrimeNG with a custom theme (Tailwind CSS optional for layout utilities via PrimeNG's Tailwind integration; do not mix two component libraries); **full RTL support** (set `dir` on `<html>` from the active language; use CSS logical properties: `margin-inline-start`, etc.).
- Fonts: an Arabic-friendly font (Cairo, IBM Plex Sans Arabic, or Tajawal) with Latin fallback. Default theme color `#0f172a` (configurable per tenant later).
- Number/currency/date formatting through a single formatting service using tenant settings (currency, digit style).
- Supabase JS client for auth and allowed reads; generated API client for FastAPI calls.
- An HTTP interceptor attaches the Supabase JWT and the active `X-Tenant-Id` header to every API call, refreshes expired sessions, and maps API error codes to translated messages.
- Route guards by role; menu items hidden by role and feature flag.
- Responsive, **mobile-first** for owners checking from phones; desktop-optimized data tables for accountants.
- PWA: installable, app icons, offline shell, **offline read-only** cache of dashboard and last-viewed lists; writes require connectivity (show a clear offline banner; do not queue financial writes offline).

### 9.2 Screens

1. Login, forgot password, tenant switcher
2. Onboarding wizard
3. Dashboard (owner view and partner view)
4. Vehicles: list (filters, aging colors), vehicle file (tabs: details, costs, media/documents, history, sale; the costs tab is a **cost-stacking card**: purchase price + each expense = total cost, recalculated live (display only) while an expense is being typed, and hidden entirely for the sales role), add/purchase wizard, add expense quick dialog (must take less than 15 seconds on a phone)
5. Consignment in / out: lists, agreements, settlements, statements
6. Customers: list, profile (purchases, sales, installments, requests, call notes)
7. Customer requests and matches
8. Sales: new sale wizard (vehicle → buyer → price → payment structure → review → post), sale document print
9. Installments: due/overdue board, calendar view, schedule view, record payment dialog, deferred papers register (promissory notes and cheques)
10. Partners: list, partner statement, summary, record contribution/drawing/loan
11. Cash and bank: balances, cash book, transfers, general expenses, other income
12. Profit distribution: preview and post
13. Reports center
14. Excel import wizard
15. Settings: profile, branches, cash accounts, categories, users and roles, tax/country pack, profit policy, period locks
16. Audit log
17. Super admin console (separate route/module, separate role)

### 9.3 UX principles

- Arabic labels must be natural Egyptian-business Arabic (e.g. "ملف العربية", "رقم الشاسيه", "مصاريف التجهيز", "حصة الشريك", "مسحوبات", "كشف حساب الشريك", "الخزنة", "إيصالات الأمانة", "شيكات آجلة", "عربون") with English equivalents.
- Every financial form shows a **plain-language preview** before posting: "سيتم خصم 50,000 ج.م من الخزنة الرئيسية وتسجيلها كسحب من حصة الشريك أحمد".
- Confirmation dialogs for posting and reversal; reversal requires a reason.
- Never show the words "debit/credit" to non-accountant roles.
- Large touch targets, minimal typing, smart defaults (today's date, default cash box).
- **Design system**: consistent typography, spacing, buttons, inputs, tables, cards, dialogs and status badges, plus explicit empty, loading and error states. It should look like serious financial software, not a flashy car-dealer site.
- **Key mobile workflows, minimum taps**: view dashboard, search a car, add a car, add an expense, record a payment, log a call, view a car's profit, see what's due today.

---

## 10. Security and Compliance

- RLS on all tenant tables, tested.
- Supabase service-role key used **only** server-side; never shipped to the browser.
- Storage buckets private; signed URLs with short expiry; files under `tenant_id/` paths with storage RLS policies.
- Sensitive personal fields (national IDs) masked in UI and lists; access audit-logged.
- **Field-level cost masking**: the sales role must not receive purchase price, expenses, total cost, minimum price or profit through any channel. Enforce in three places: (1) FastAPI response schemas per role, (2) a Supabase view (e.g. `vehicles_catalog`) without cost columns as the only vehicle source granted to the sales role, with base vehicle and expense tables denied to it by RLS, (3) the UI. Add tests proving a sales user cannot obtain cost data via the API or the Supabase client.
- Strong password policy; optional 2FA (TOTP) for owners and accountants.
- Backups: rely on Supabase backups plus a nightly logical export per tenant; documented restore procedure.
- Data protection: document where data is hosted. Egypt (Personal Data Protection Law) and Saudi Arabia (PDPL) may impose localization or transfer requirements; keep the infrastructure portable (self-hosted Supabase possible) and record this in `docs/DECISIONS.md`.
- Tenant data export (full Excel/JSON) available to the owner at any time.

---

## 11. Non-Functional Requirements

- Dashboard and lists load in under 2 seconds for a tenant with 5,000 vehicles and 100,000 journal lines.
- Indexes on `tenant_id` + common filters; journal lines indexed by account, partner, vehicle, customer, date.
- All monetary calculations rounded to 2 decimals using banker's rounding only where explicitly specified; default ROUND_HALF_UP; document the choice.
- Accessibility: keyboard navigation, sufficient contrast.
- Observability: structured logs, error tracking (Sentry-compatible), basic metrics.

---

## 12. Repository Layout and Developer Experience

```
/apps/web            Angular PWA
/apps/api            FastAPI service
/supabase            config.toml, migrations/, seed.sql, tests (pgTAP for RLS and ledger constraints)
/docs                SPEC.md (this file), DECISIONS.md, ACCOUNTING.md (posting rules), API.md, RUNBOOK.md
/.github/workflows   CI
docker-compose.yml   local API + local Supabase
```

- `make dev` / scripts to start everything locally (Supabase CLI local stack + API + Angular).
- Seed script creating a demo tenant ("معرض النور للسيارات"), 3 partners, 15 vehicles in various states, sales, installments (some overdue), consignments, so every screen and report has realistic data.
- `.env.example` for all services; no secrets committed.
- Pre-commit: ruff, black/ruff-format, mypy, eslint, prettier.
- Git: `main`, `develop`, `feature/*` branches; conventional commits (`feat:`, `fix:`); never commit secrets.
- Environments: development, testing, production. Key variables: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (API only, never Angular), Supabase JWKS URL / JWT secret, `CORS_ORIGINS`.
- Per-feature workflow: explain the design → affected tables → migration → service and business rules → endpoint → tests → Angular service and UI → E2E test → docs.

---

## 13. Delivery Phases and Acceptance Criteria

**Phase 0: Design (no application code)**
Produce for review: product requirements summary, architecture diagram, ERD with tenant isolation and indexes, financial model (`ACCOUNTING.md` with all posting rules), API specification, Angular module plan, and an MVP backlog of small milestones, all labeled FACT / ASSUMPTION / DECISION / OPEN QUESTION.
*Accept when:* the product owner approves the design. Do not start Phase 1 before approval.

**Phase 1: Foundation**
Repo, CI, Supabase schema for tenants/memberships/settings, RLS helpers with tests, FastAPI auth, Angular shell with login, RTL/LTR switching, tenant switcher, role-based menu.
*Accept when:* a user logs in, sees only their tenant, switches language with correct RTL, and cross-tenant tests pass.

**Phase 2: Ledger core**
Chart of accounts seed, journal tables, integrity constraints/triggers, posting service, reversal, period lock, cash accounts, transfers, general expenses, cash book report.
*Accept when:* all posting tests for rules 20, 21, 24 pass and unbalanced/locked-period/cross-tenant postings fail at DB level.

**Phase 3: Partners**
Partners, share history, contributions, withdrawals, drawings, loans, partner statement and summary (screen + PDF + Excel).
*Accept when:* the owner can answer "what is each partner's balance?" in one screen, matching hand-calculated tests.

**Phase 4: Vehicles and sales**
Vehicles, media, purchase, expenses, vehicle file with profit, inventory aging, customers, reservations/deposits, cash sales, sale documents.
*Accept when:* the full purchase → expenses → sale cycle posts correctly and the vehicle file shows exact cost and profit.

**Phase 5: Installments**
Schedules, payments, promissory notes register, due/overdue dashboard, reminder job (in-app).
*Accept when:* the scenario test with installments passes and overdue lists are correct.

**Phase 6: Consignment and customer requests**
Consignment in/out flows and statements, customer requests and matching alerts.

**Phase 7: Profit distribution and reports**
Distribution policies, preview/post, P&L, trial balance, all reports in Section 4.12, dashboard.
*Accept when:* the full end-to-end scenario test (Section 7) matches expected values exactly.

**Phase 8: Excel import and onboarding**
Import wizard with mapping and validation, opening balances, onboarding wizard.
*Accept when:* a realistic messy Excel sheet imports with clear error reporting and correct opening balances.

**Phase 9: SaaS layer and hardening**
Plans, limits, feature flags, subscription states, super admin console, audit log viewer, PWA offline read, performance testing, security review, backups/restore runbook.

**Phase 10 (later, separate briefs):** Egypt ETA e-invoicing integration, SMS/WhatsApp reminders, payment gateway billing, car-level investors UI, Saudi ZATCA and UAE margin-scheme packs, bank reconciliation, marketplace posting.

**Phase 11 (later): AI management assistant**, only after the data model is stable. It answers questions such as "which cars need attention?" or "summarize this week" through **read-only backend tools** scoped to the current tenant and the user's permissions. It never gets direct database access, never runs SQL, and never creates, modifies, approves or deletes anything. Its output is labeled as recommendations.

### MVP acceptance demo (automate as a Playwright E2E test)

Owner creates showroom → adds 3 partners and records capital → adds a car and records its purchase → adds transport, repair and license expenses → sees the true cost → staff adds a customer and a car request → system shows the match → customer pays a deposit → sale is posted with a down payment and installments → first installment is collected → car profit is shown → dashboard, cash balance and partner balances update → owner sees due payments, aging stock and the Needs Attention panel.

---

## 14. Open Questions (record answers in docs/DECISIONS.md)

1. Is partnership showroom-level only, or also per car with different investors?
2. Is profit distributed per car on sale, or periodically? Monthly, quarterly or yearly?
3. Do installment sales include a markup over the cash price, and should it be recognized over time?
4. When a partner borrows against his share, is it a loan to be repaid, or an advance deducted from future profit? (Support both: rule 4/5 vs. rule 3.)
5. Who in the showroom records transactions, and who must approve them?
6. Which Egypt e-invoice/e-receipt obligations apply to used-car showrooms specifically?
7. Which digit style do users prefer in Arabic: Arabic-Indic (١٢٣) or Western (123)?
8. How common are trade-ins and post-dated cheques in Egypt vs. Qatar? (Both are supported; confirm priority.)

Until answered, implement the defaults stated in this document and keep the behavior configurable.

---

## 15. Definition of Done (every feature)

- Works in Arabic (RTL) and English (LTR), on mobile and desktop.
- Role permissions enforced in the UI, the API **and** the database (RLS).
- Money-moving actions are atomic, idempotent, audit-logged, reversible only via reversal, and covered by tests.
- Reports reconcile: sum of partner balances + liabilities = assets (balance sheet check runs in CI against the seed data).
- Documentation updated (`ACCOUNTING.md` for any new posting rule, `DECISIONS.md` for any assumption).
