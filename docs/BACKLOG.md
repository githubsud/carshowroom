# BACKLOG: Phases 1–9 as Small Milestones

> Phase 0 design. Each milestone is roughly 1–4 days of work and ends with passing tests. Every milestone follows the per-feature workflow (FACT, SPEC §12): design → tables → migration → service and rules → endpoint → tests → Angular → E2E → docs.
> Every milestone also inherits the Definition of Done (SPEC §15): AR/EN, mobile and desktop, permissions enforced in the UI, the API **and** RLS; money actions atomic, idempotent, audited and tested; docs updated.
> Features the spec does not assign to a phase are placed by **DECISION D-30** and marked ⚑.
> 🔒 marks a milestone that is blocked until an OPEN QUESTION is answered.

---

## Phase 1: Foundation

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 1.1 | Monorepo skeleton | `apps/web`, `apps/api`, `supabase/`, `docs/`; `make dev` starts local Supabase, the API and Angular; `.env.example` for each service; pre-commit (ruff, ruff-format, mypy, eslint, prettier) passes on an empty project |
| 1.2 | CI pipeline | GitHub Actions run lint, type-check, pytest, Angular tests, pgTAP and the migration check (`supabase db reset` on a fresh DB) on every PR; the pipeline is green |
| 1.3 | Tenancy schema | Migrations for `tenants`, `tenant_settings`, `branches`, `locations`, `roles`, `permissions`, `role_permissions`, `memberships`, `invitations`, `tenant_counters`, `audit_log` (append-only), `platform_admins`, `plans`, `subscriptions`, `feature_flags`; composite tenant FKs; seeded permissions and system roles (ARCHITECTURE §7) |
| 1.4 | RLS helpers and isolation tests | `private.is_member`, `has_permission`, `my_partner_id`, `tenant_writable`, `current_tenant_id`; pgTAP shows that tenant A cannot read or write B for every table; a "RLS enabled on every tenant table" check fails CI when it is violated |
| 1.5 | FastAPI auth and tenant context | JWKS verification, `X-Tenant-Id` resolution, `require(perm)` dependency, `set_config` per transaction, error envelope, request id, JSON logs, `/healthz`, `/readyz`; pytest: invalid token → 401, other tenant → 403, missing permission → 403 |
| 1.6 | Audit plumbing | Generic audit trigger; API audit events (login, membership change); UPDATE/DELETE on `audit_log` fail for every role (pgTAP) |
| 1.7 | Angular shell | Standalone app, PrimeNG theme, Transloco AR/EN, `dir` switching, logical-CSS lint, FormatService (digits), layout (top bar + side menu + mobile bottom nav), empty/loading/error components |
| 1.8 | Login and tenant switcher | Login, forgot/reset password, tenant switcher, `/t/:tid` routing, interceptor (JWT + tenant), guards, permission directive, menu by permission and flag |
| 1.9 | ⚑ User invites | Owner invites by **email** (phone: Q-29), assigns a role, links a partner; the invitee accepts and lands in the tenant; role change is audit-logged |
| 1.10 | Generated API client | OpenAPI → TS client; a CI drift check |

**Phase 1 accepted when (FACT):** a user logs in, sees only their tenant, switches language with correct RTL, and the cross-tenant tests pass (pgTAP + API).

### Phase 1 status: accepted by the product owner on 2026-10-02

| ID | Status | Notes |
|---|---|---|
| 1.1 | ✅ | `make` (Linux/macOS/CI) and `scripts/dev.ps1` (Windows); pre-commit config |
| 1.2 | ✅ written, ⏳ not yet run on GitHub | `.github/workflows/ci.yml`: lint, types, unit, migrations from scratch, pgTAP, API integration, E2E. Needs a GitHub repository to run |
| 1.3 | ✅ | `locations` deferred to Phase 4 (D-46); `country_packs`, role overrides and restrictions added (D-43, D-44) |
| 1.4 | ✅ | 61 pgTAP assertions: RLS on every table, policy on every tenant table, no anon/service-role grants, browser write allowlist, private-function allowlist, cross-tenant isolation (browser and API roles), permissions, audit |
| 1.5 | ✅ | JWKS (ES256) verification against real Supabase logins; 21 unit + 18 integration tests |
| 1.6 | ✅ | Row-change trigger + API events; append-only proven against the owner role |
| 1.7 | ✅ | AR/EN runtime switch, `dir` on `<html>`, logical CSS enforced by stylelint, digit-style money formatting (24 unit tests) |
| 1.8 | ✅ | Login, forgot/reset password, tenant switcher, `/t/:tenantId` routing, interceptor, guards, permission/flag menu |
| 1.9 | ✅ | Email invites via Supabase Auth admin; existing accounts get a membership; last-owner rule; UI page. Phone invites wait for Q-29 |
| 1.10 | ⏳ deferred to Phase 2 | Contracts are hand-typed in `api.models.ts` for the 8 Phase 1 endpoints; the generated client arrives with the first money endpoints |
| E2E | ✅ | 14 Playwright tests (desktop + mobile): login, tenant isolation by URL, RTL↔LTR with sidebar mirroring, partner tenant switching, sales menu restrictions, sign-out |

---

## Phase 2: Ledger core

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 2.1 | COA seed and ledger tables | `ledger_accounts` seeded per tenant from the country template (ACCOUNTING §2); `journal_entries`, `journal_lines`, `accounting_periods`; header accounts not postable |
| 2.2 | DB integrity | One-side check; deferred balance trigger (≥ 2 lines); immutability triggers; open-period trigger; gapless counter; subledger-required trigger; **pgTAP: an unbalanced raw insert fails, an update/delete fails, a locked-period insert fails, a foreign-tenant account fails** |
| 2.3 | `post_journal_entry` / `reverse_journal_entry` | `SECURITY DEFINER` functions are the only insert path; `app_api` has no INSERT grant; concurrency test: 20 parallel posts give gapless numbers |
| 2.4 | Python posting framework | `money.py` (Decimal, HALF_UP), `JournalLine` types, rule registry, idempotency middleware and table, preview mechanism; **unit tests for rules 20, 21, 24 written first** |
| 2.5 | Cash accounts | Settings CRUD creates ledger sub-accounts; balances endpoint; cash-negative policy (WARN/BLOCK) with row locking; test that concurrent withdrawals cannot overdraw under BLOCK |
| 2.6 | Transfers and general expenses | Rules 20, 21 (+ funding by cash only in this phase); expense categories → 62xx; attachments; preview text AR/EN |
| 2.7 | Reversal and period lock | Reverse endpoint with reason (rule 24); lock and unlock (owner) by month; tests: reversal restores trial balance, posting and reversal into a locked month fail |
| 2.8 | Cash book report | Opening, movements, running balance, closing; JSON/PDF (WeasyPrint with Arabic font)/XLSX; numbers reconcile with the balances endpoint |
| 2.9 | Finance UI | Cash & bank page, transfer dialog, expense dialog, journal (accountant), periods page |
| 2.10 | 🔒 Other income (Q-26/P-01) | Posts once the rule is approved |

**Phase 2 accepted when (FACT):** all posting tests for rules 20, 21 and 24 pass, and unbalanced, locked-period and cross-tenant postings fail **at DB level**.

### Phase 2 status: accepted by the product owner on 2026-10-02

| ID | Status | Notes |
|---|---|---|
| 2.1 | ✅ | `coa_template` (41 accounts incl. 2310/3310 from D-40/D-41) seeded into every tenant by trigger; `ledger_accounts`, `cash_accounts`, `expense_categories` (7 general + 10 vehicle seeded), `payment_methods` |
| 2.2 | ✅ | One-side check, deferred balance trigger, immutability (incl. owner and TRUNCATE), open-period trigger, gapless counter, subledger and postable checks, account identity protection — 34 pgTAP assertions in `05_ledger_integrity` |
| 2.3 | ✅ | `post_journal_entry` / `reverse_journal_entry` are the only insert path (no write grants); gapless numbering proven with 20 concurrent + 5 rolled-back postings |
| 2.4 | ✅ | `money.py` (strict Decimal, HALF_UP), drafts, rules 20/21/24 with unit tests written first (30 tests), idempotency, plain-language previews |
| 2.5 | ✅ | Cash/bank accounts with auto sub-accounts, derived balances, WARN/BLOCK negative-cash policy with row locks |
| 2.6 | ✅ | General expenses (rule 20) and transfers (rule 21), with previews in Arabic and English. Funding by supplier credit or partner arrives with Phases 3–4 |
| 2.7 | ✅ | Reversal with reason and preview; month lock (owner) / unlock (owner, reason, audited) |
| 2.8 | ✅ | Cash book JSON / Excel (everywhere) / PDF (Docker, CI, Linux — D-56), Arabic RTL layout verified |
| 2.9 | ✅ | Web: Cash & bank (balances, cash book, expenses, transfers, exports), expense and transfer dialogs with preview, Journal with reversal, Month lock, Settings for cash accounts and categories |
| 2.10 | 🔒 | Other income still waits for approval of P-01 (Q-26) |
| 1.10 | ✅ | Typed API client generated from OpenAPI; CI drift checks (D-57) |
| Seed | ✅ | Opening balances, an expense and a transfer for معرض النور; Doha opening balance; `06_seed_balance` checks every tenant balances (SPEC §15) |
| Tests | ✅ | pgTAP 99 · API 100 (+1 PDF test run in Docker/CI) · web unit 29 · E2E 22 |

---

## Phase 3: Partners

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 3.1 | Partners and share history | Partner CRUD; batch share change with a deferred 100% check (Q-09 precision); no overlapping periods; history never overwritten |
| 3.2 | Partner transactions | Rules 1, 2, 3, 4, 5, 28, 29 (unit tests first), endpoints, previews; national ID encrypted and masked |
| 3.3 | Partner statement | Buckets capital / current / loans to / loans from; opening, running, closing; hand-calculated test; PDF and Excel |
| 3.4 | Partners summary | One row per partner with %, capital, allocated profit, drawings, loans, net (formula per Q-17); matches the sum of statements |
| 3.5 | Partner role access | A partner user sees only their own statement (RLS + API test) and the summary only if `partner_sees_summary` |
| 3.6 | Partners UI | List, statement, summary, action dialogs with plain-language previews |

**Phase 3 accepted when (FACT):** the owner can answer "what is each partner's balance?" in one screen, matching hand-calculated tests.

### Phase 3 status: accepted by the product owner on 2026-10-02

| ID | Status | Notes |
|---|---|---|
| 3.1 | ✅ | Partner records (Arabic/English name, phone, national ID, notes, archive per D-62); share batches checked at commit to total 100.0000 (SR010), no overlapping periods, history append-only (D-64), pgTAP `07_partners` |
| 3.2 | ✅ | Rules 1, 2, 3, 4, 5, 28, 29 and 30 (unit tests first), one transactions endpoint with preview; repayment cap and warnings (D-63); national ID encrypted, masked and audited (D-65) |
| 3.3 | ✅ | Statement by bucket with opening, running net and closing; JSON / Excel / PDF (D-56) |
| 3.4 | ✅ | Summary: %, capital, allocated profit, drawings, current account, loans both ways, net (Q-17); totals row; the hand-calculated Doha scenario matches |
| 3.5 | ✅ | A partner user sees only their own record, history and statement (RLS + API), the summary only with `partner_sees_summary`, and their position on the dashboard; user ↔ partner link in Settings → Users (D-66) |
| 3.6 | ✅ | Partners screen (summary, add partner, change ownership with "split equally", new movement), statement screen, dialogs with plain-language previews |
| 2.10 | ✅ | Other income (P-01, approved under Q-26) on the Cash & bank screen |
| 2.6 | ✅ | General expense paid personally by a partner (rule 30, D-67) |
| Seed | ✅ | Three partners (50/30/20) with capital for معرض النور, two for Doha; a user linked to each |
| Tests | ✅ | pgTAP 111 · API 131 (+1 PDF test in Docker/CI) · web unit 35 · E2E 28 |

---

## Phase 4: Vehicles and sales

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 4.1 | Vehicle master data | Vehicles table, stock numbers, VIN normalisation and uniqueness among non-archived vehicles, state machine (service + DB trigger), status/location/price history; all writes via the API (D-06) |
| 4.2 | Cost masking | `vehicles_catalog` view; RLS denies base cost tables to sales; per-permission response models; **tests: a sales user gets no cost field via the API, the Supabase client, search, notifications or document listing** |
| 4.3 | Media and documents | Signed URL upload, client compression, camera capture, `documents.sensitivity`, storage RLS by `tenant_id/` path |
| 4.4 | Customers | CRUD via Supabase (RLS), phone normalisation, flags, global quick search (vehicles by VIN last digits/plate/make; customers by name/phone) |
| 4.5 | Purchase | Rules 6, 7, 8 (tests first); seller payable statement; purchase step of the add-car wizard |
| 4.6 | ⚑ Suppliers | Supplier CRUD, rules 31, 32, supplier statement |
| 4.7 | Vehicle expenses | Rule 9, rule 30 (partner-funded), rule 31 (credit); quick expense dialog **< 15 s** (timed E2E on a mobile viewport); cost completeness labels; 🔒 expenses on sold cars (Q-14) |
| 4.8 | Vehicle file and inventory list | Cost stack, days in stock (Q-24 default), aging colours from settings, filters, sort, server pagination |
| 4.9 | Reservations and deposits | Rules 11, 34, 35; RESERVED status; expiry |
| 4.10 | Cash sales | Draft → post (configurable poster), rule 12 + cost entry; mixed payment legs; deposit applied; business rule 1 (DB partial unique index + service check) |
| 4.11 | ⚑ Trade-in | Rule 26; the trade-in creates a vehicle with its own cost file; profit test (SPEC §7) |
| 4.12 | ⚑ Sale documents / CountryPack v1 | Invoice numbering per pack; Arabic and English contract/invoice PDF with logo; `EgyptETAAdapter` stub storing UUID/status fields; Qatar simple invoice; 🔒 tax lines (Q-11) |
| 4.13 | ⚑ Sale cancellation | 🔒 Rule 33 as specified **or** P-03 (Q-12); vehicle → AVAILABLE; a cancelled sale accepts no payments |
| 4.14 | Sales UI | New sale wizard (cash/bank/mixed/trade-in), sale list, sale detail |

**Phase 4 accepted when (FACT):** the full purchase → expenses → sale cycle posts correctly and the vehicle file shows exact cost and profit.

### Phase 4 status: delivered (2026-10-03); continuing per the standing instruction

| ID | Status | Notes |
|---|---|---|
| 4.1 | ✅ | Vehicles with stock numbers, VIN normalisation and uniqueness (D-69), state machine in the service **and** a DB trigger (SR020), status/location/price history (append-only), all writes via the API |
| 4.2 | ✅ | `vehicles_catalog` view without minimum price; base table only with cost + minimum-price permission; cost keys absent from every sales-role response (API JSON walk over vehicle, list, search, sale, customer, documents); cost documents hidden (pgTAP + API + E2E) |
| 4.3 | ✅ | Photos via signed URLs (D-74) with camera capture and client-side WebP compression; documents with `sensitivity` (purchase contracts and seller receipts are always COST) |
| 4.4 | ✅ | Customers via the API (D-68): E.164 phones, duplicate-phone check, flags, encrypted national ID; global quick search (stock no., plate, VIN last digits, make/model, name, phone) |
| 4.5 | ✅ | Rules 6, 7, 8 (tests first); seller payables on the customer page; add-car wizard = details → purchase with preview |
| 4.6 | ✅ | Suppliers, rule 31 (vehicle and general expenses on credit), rule 32, supplier statement |
| 4.7 | ✅ | Rules 9, 30, 31 and P-04 on sold cars; quick expense dialog timed at **3.8 s** on a phone viewport (E2E < 15 s); cost completeness from the tenant checklist (Settings) |
| 4.8 | ✅ | Vehicle file (cost breakdown, profit, history, photos, documents); inventory with filters, sorting, server pagination, days in stock and aging colours (D-81) |
| 4.9 | ✅ | Rules 11, 34, 35; RESERVED status; expiry shown (D-72) |
| 4.10 | ✅ | Draft → post by `sale.post`; rule 12 + cost entry (D-28); cash + bank legs; deposit applied; business rule 1 in the service and a partial unique index |
| 4.11 | ✅ | Rule 26: the trade-in becomes a car with its own cost file at the agreed value; profit test |
| 4.12 | ✅ | Invoice numbering per country pack at posting (D-77); Arabic/English invoice and contract PDF (D-56, D-80); ETA stub fields; no tax lines (D-39) |
| 4.13 | ✅ | Both cancellation methods (D-41): REFUND_LIABILITY (P-03) and MIRROR (rule 33); trade-in handled per D-76; delivered sales refused (Q-30); refund of customer credit (P-02) |
| 4.14 | ✅ | New sale screen (vehicle, buyer, discount, deposit, trade-in, split payments, live "remaining"), sales list, sale record with print and cancel |
| Seed | ✅ | Five cars in معرض النور (available, owed-to-seller, reserved, sold, in preparation), customers, a workshop; the balance check still holds |
| Tests | ✅ | pgTAP 132 · API 184 (+1 PDF test in Docker/CI) · web unit 42 · E2E 33 |

---

## Phase 5: Installments

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 5.1 | Schedule generator | Equal split with remainder on the last installment, manual schedule, frequency; property tests (Σ = financed amount) |
| 5.2 | Installment sale mode (a) | Rule 13; plan + installments created on post |
| 5.3 | 🔒 Mode (b) markup | Rules 14 and 15b behind the setting; recognition method per Q-03 |
| 5.4 | Receipts and allocation | Rule 15; partial payments; oldest-first allocation; remaining always derived; overpayment blocked (customer credit 🔒 Q-13) |
| 5.5 | Deferred papers register | Notes and PDCs, status machine, events, scans; **a bounced cheque reopens the balance** (rule 27 test) and flags the customer; "returned to customer" when fully paid |
| 5.6 | Due/overdue board and calendar | Today / N days / overdue with days late / per-customer totals; calendar radar colours |
| 5.7 | Worker and reminders | Worker container, advisory lock, `reminder_jobs` log; daily in-app notifications (default 2 days ahead + overdue), deduplicated; `SmsProvider`/`WhatsAppProvider` no-op logging |
| 5.8 | Customer installment statement | PDF |

**Phase 5 accepted when (FACT):** the scenario test with installments passes and the overdue lists are correct.

### Phase 5 status: delivered (2026-10-03); continuing per the standing instruction

| ID | Status | Notes |
|---|---|---|
| 5.1 | ✅ | Equal split (half-up, remainder on the last) or manual schedule; weekly/biweekly/monthly/quarterly with month-end clamping (D-90); property test over 2,000 random splits |
| 5.2 | ✅ | Rule 13 (mode a); plan and installments created when the sale posts; schedule preview in the sale screen (D-82, D-89) |
| 5.3 | 🔒 | Mode (b) markup waits for Q-03 (D-82) |
| 5.4 | ✅ | Rule 15; partial payments; oldest-first allocation; remaining derived (`installment_status`); overpayment per D-84; customer credit can pay installments |
| 5.5 | ✅ | Deferred papers register with status machine (DB-enforced), events, scans (documents), collect → receipt (A-10), bounce → rule 27 reopens the balance and flags the customer, P-07 bank charges, papers returned on cancellation (D-85) |
| 5.6 | ✅ | Board: overdue with days late, due today, next 7 days, all open, totals per customer; calendar "radar" coloured by state; dashboard tiles (D-87) |
| 5.7 | ✅ | Worker (`python -m app.jobs`, docker-compose `worker`), advisory lock, `reminder_jobs`, deduplicated in-app notifications, log-only SMS/WhatsApp providers (D-86); notification bell |
| 5.8 | ✅ | Customer installment statement (JSON and PDF) on the customer page |
| Cancel | ✅ | Installment sales cancel per D-88 (collected installments owed back; MIRROR refused with collections) |
| Seed | ✅ | Optra sold on 6 monthly installments (first overdue) with a post-dated cheque and a promissory note |
| Tests | ✅ | pgTAP 145 · API 205 (+1 PDF test in Docker/CI) · web unit 44 · E2E 36 |

---

## Phase 6: Consignment and customer requests

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 6.1 | Consignment IN agreements | Terms (net price / fixed / %), who bears expenses, end date, printable Arabic agreement |
| 6.2 | Consignment IN money | Rule 10 (recoverable), rule 16 (both entries), rule 17 settlements, consignor statement; 🔒 showroom-borne/shared expenses, below-net sale, return-with-recovery (Q-15, P-05/P-06) |
| 6.3 | Consignment OUT | Consign-out / return moves; rule 18 (three entries), rule 19; external showroom statement; "where are my cars and for how long" list |
| 6.4 | ⚑ Follow-ups / call logging | 3-tap call log, next follow-up date, assigned salesperson, priority; "due today" list |
| 6.5 | Customer requests | Wanted list with statuses, budget/year ranges |
| 6.6 | Matching | Becoming AVAILABLE triggers matching; alert "N customers asked for this car" with phones; contacted flag |

### Phase 6 status: delivered (2026-10-03); continuing per the standing instruction

| ID | Status | Notes |
|---|---|---|
| 6.1 | ✅ | Receive a consigned car (owner + car + terms in one form): net price, fixed or % commission, who bears expenses (owner / showroom / shared %), end date with "expired" flag; printable Arabic/English agreement PDF (D-91, D-99) |
| 6.2 | ✅ | Rule 10 and C-11 (tests first); rule 16 both entries through the sale screen; rule 17 payouts and P-06 recoveries with previews; consignor statement (JSON/PDF) reconciles with 2200/1430. Showroom-borne and shared expenses now built (P-05, account 6280, D-93). Below/at-net sales stay blocked and installment sales refused (Q-15, P-14) |
| 6.3 | ✅ | Send out / came back moves (D-92); rule 18 three entries, rule 19 collections; external showroom statement (JSON/PDF); "where are my cars and for how long" list with days out (D-95) |
| 6.4 | ✅ | Call log in **2 taps** (E2E on a phone viewport), next follow-up date, assigned salesperson, priority; due list on the requests page (D-98) |
| 6.5 | ✅ | Customer requests with make/model, year and budget ranges, statuses, financing/trade-in flags; on the customer page with the follow-up history |
| 6.6 | ✅ | Database trigger on AVAILABLE (D-97); notification "N customers asked for a car like this"; matches card with phones on the vehicle file; contacted flag (E2E) |
| Seed | ✅ | A consigned Lancer (owner سمير عادل, 5%), an external showroom, Sara's request matching the Corolla and a call-back due |
| Tests | ✅ | pgTAP 157 · API 242 (+1 PDF test in Docker/CI) · web unit 44 · E2E 39 |

**Phase 6 accepted when (DECISION; the spec gives no criteria, G-15):**

- Rules 10, 16, 17, 18 and 19 pass their unit tests, and the consignor and external showroom statements reconcile with the ledger.
- A car that becomes AVAILABLE produces correct matches in an E2E test.
- A call can be logged in ≤ 3 taps on mobile.

---

## Phase 7: Profit distribution, reports, dashboard

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 7.1 | 🔒 Period close + periodic distribution | Rules 23 + 22; pro-rata per Q-18; rounding remainder rule; preview = post; a period cannot be distributed twice |
| 7.2 | 🔒 Per-car distribution policy | Per C-04/Q-10 resolution; behind the setting |
| 7.3 | Financial reports | P&L (excludes closing entries), trial balance, general ledger, balance check (C-07) |
| 7.4 | Operational reports | Vehicle profit, inventory aging buckets, installments, papers register, consignment in/out, general expenses by category; all with PDF/XLSX |
| 7.5 | ⚑ Needs Attention engine | All SPEC §4.17 rules, deterministic, thresholds from settings, filtered by permission (no profit alerts for sales) |
| 7.6 | Dashboard | Owner / partner / staff variants; KPI tiles; partner equity matrix; the due window per C-09 |
| 7.7 | ⚑ Notification centre | Read/unread, bell counter, deep links |
| 7.8 | Full scenario test | ACCOUNTING §4 expected values match **exactly** |
| 7.9 | MVP acceptance demo E2E | The Playwright test from SPEC §13 passes |

### Phase 7 status: delivered (2026-10-03); continuing per the standing instruction

| ID | Status | Notes |
|---|---|---|
| 7.1 | ✅ | Rules 23 + 22 with preview = post; DAY_WEIGHTED / SUB_PERIOD_PROFIT, LARGEST_REMAINDER / LARGEST_SHARE, loss to partners or carried forward (D-40, P-09); no overlap, no gap, nothing posted into a distributed range, latest reversible (D-100–D-102) |
| 7.2 | ✅ | PER_CAR: allocation through 3310 at each sale (incl. consigned and external sales), reversed on cancellation, netted at close (P-10, D-103) |
| 7.3 | ✅ | P&L (closing entries excluded), trial balance, general ledger, balance check with 3900 flag (D-104) |
| 7.4 | ✅ | Vehicle profit, inventory aging (0–30/31–60/61–90/90+), installment collections, papers register, consignments in/out, general expenses by category — each on screen, PDF and Excel |
| 7.5 | ✅ | Needs Attention engine, every SPEC §4.17 rule, thresholds from settings, permission-filtered (D-105) |
| 7.6 | ✅ | Dashboard: Needs Attention first, cash/bank, stock and capital tied up, aged cars, month's sales and gross profit, installments due, partner equity matrix with bars; partner view keeps its own position |
| 7.7 | ✅ | Notification centre page (read/unread, deep links); worker sends attention alerts once per alert and level |
| 7.8 | ✅ | `test_full_scenario.py`: every expected value of ACCOUNTING §4 matches exactly, in a fresh showroom inside a rolled-back transaction |
| 7.9 | ✅ | `e2e/phase7.spec.ts` MVP acceptance demo (from the seeded showroom, D-106) |
| Settings | ✅ | Settings → Policies: profit policy, frequency, losses, pro-rata, rounding, cancellation, overpayments, negative cash, aging thresholds |
| Tests | ✅ | pgTAP 164 · API 268 (+1 PDF test in Docker/CI) · web unit 46 · E2E 42 |

**Phase 7 accepted when (FACT):** the full end-to-end scenario test (SPEC §7) matches the expected values exactly.

---

## Phase 8: Excel import and onboarding

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 8.1 | Upload and templates | Template downloads per kind; upload of their own sheet; header detection; Arabic headers |
| 8.2 | Column mapping | Suggested mapping; save per tenant; reuse |
| 8.3 | Validation preview | Row errors (missing VIN, invalid date, duplicate, bad number formats incl. Arabic-Indic digits, currency symbols); downloadable error file; nothing saved |
| 8.4 | Commit and opening entry | Vehicles (with cost breakdown memo), customers, partners with opening balances, open installments; a single labelled opening entry (rule 25) at the go-live date; all or nothing; 🔒 OBE clearing (Q-16) |
| 8.5 | Onboarding wizard | Profile → partners/capital → cash/bank openings → import → done |

**Phase 8 accepted when (FACT):** a realistic messy Excel sheet imports with clear error reporting and correct opening balances. **DECISION:** we need a real anonymised sheet from the pilot showroom as a fixture (Q-35).

---

## Phase 9: SaaS layer and hardening

| ID | Milestone | Acceptance criteria |
|---|---|---|
| 9.1 | Plans, limits, flags | Limits enforced (users, branches, vehicles in stock) → `PLAN_LIMIT_REACHED`; flags hide the menu and block the API |
| 9.2 | Subscriptions | Trial/active/past due/suspended; suspended = read-only in both the API and RLS; data is never deleted |
| 9.3 | Signup and super admin console | Self-serve signup with trial; tenants list, usage, plan, manual invoice mark-paid; `PaymentGateway` interface |
| 9.4 | Support access | Tenant-granted, time-boxed, read-only, audit-logged support sessions; test: no grant → no data |
| 9.5 | Audit log viewer | Filters, JSON diff |
| 9.6 | PWA | Installable, icons, offline shell, offline read-only cache, offline banner; writes blocked offline (E2E with network emulation) |
| 9.7 | Performance | A seed generator for 5,000 vehicles / 100,000 lines; dashboard and lists < 2 s (p95); add a summary table only if needed (D-12) |
| 9.8 | Security review | Threat model, dependency audit, rate limits, request size limits, headers/CSP, 2FA (TOTP) for owner/accountant, password policy |
| 9.9 | Backups and runbook | Nightly per-tenant export; tenant full data export (Excel/JSON) on demand; `RUNBOOK.md` with a **rehearsed** restore |
| 9.10 | ⚑ Country pack configuration | EG/QA packs data-driven; terminology variants (Q-25) |
| 9.11 | Demo seed (completed) | "معرض النور للسيارات", 3 partners, 15 vehicles in various states, sales, overdue installments, consignments; balance check passes in CI. **DECISION:** the seed grows from Phase 2 onward so the CI balance check (SPEC §15) runs from Phase 2, and is completed here |

**Phase 9 accepted when (DECISION; the spec gives no criteria, G-15):**

- The performance targets are met on the seeded volume.
- The security review is closed, with no high findings open.
- A restore drill has been documented.
- Suspended-tenant and support-access tests pass.
- The demo seed passes the balance check in CI.
