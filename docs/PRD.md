# PRD: SayyaraDMS (سيارة), Product Requirements Summary

> Phase 0 design document. Source of truth: [SPEC.md](SPEC.md). Statements are labelled **FACT** (stated in the spec), **ASSUMPTION** (our reading, to be confirmed), **DECISION** (a design choice we propose; it needs product-owner approval) or **OPEN QUESTION** (needs an answer; tracked in [DECISIONS.md](DECISIONS.md)).
> "SayyaraDMS" is a placeholder name and lives in a single config constant (FACT, SPEC §1).

---

## 1. Problem and goal

**FACT (SPEC §1.1).** Discovery interviews with an Egyptian used-car showroom found that the #1 pain is **financial**:

- Several partners fund the showroom, each owning a percentage of capital.
- Partners withdraw money and borrow against their share.
- There are many cash movements every day, and they all live in one Excel sheet.
- Nobody can quickly and confidently say what came in, what went out, what the cash balance is, or what each partner's balance is.

**FACT (Golden rule).** Give the showroom owner **one reliable picture of the vehicles, the money, the customers and the real profit**.

The owner must be able to answer these at a glance (FACT, SPEC §1.1):

| # | Owner question | Where it is answered |
|---|---|---|
| 1 | How much cash do I have, and where is it? | Dashboard, cash/bank balances, cash book |
| 2 | What is my stock worth at cost? | Dashboard "capital tied up in inventory", inventory report |
| 3 | Who owes me, and what do I owe? | Receivables and payables (installments, external showrooms, consignors, sellers, suppliers) |
| 4 | What is each partner's position? | Partners summary, partner statement, partner equity matrix |
| 5 | Which cars made or lost money? | Vehicle file, vehicle profit report |
| 6 | Which cars have sat too long? | Inventory aging colours, aging report, Needs Attention |
| 7 | What needs my attention today? | Needs Attention panel and notification centre |

**Feature filter (FACT, SPEC §0.8).** Every feature must help the owner make money, protect cash, reduce mistakes, save time or control the business. Otherwise it is deferred.

**Discovery caveat (FACT, SPEC §1.4).** The financial pain comes from early interviews and must be re-validated with more showrooms, so modules stay loosely coupled. **ASSUMPTION:** the evidence so far comes from a single Egyptian showroom, and nothing yet validates the Qatar needs. See DECISIONS R-01.

---

## 2. Users and roles

**FACT (SPEC §1.2).** Authorization is **permission-based**. Roles are bundles of permissions, and code checks permissions, never role names. The full permission catalogue and default role bundles are in [ARCHITECTURE.md §7](ARCHITECTURE.md#7-permissions-and-roles).

| Role | Who | Summary of access |
|---|---|---|
| **Owner / Managing Partner** | Founder or lead partner | Everything. Approves sensitive operations (posting, reversal, period unlock, partner equity changes). |
| **Manager** | Showroom manager | Day-to-day operations and finance **as granted**. Cannot change settings or partner equity, and cannot unlock periods. |
| **Partner** | Silent or active investor | Read-only: own statement, own balance and, if configured, an overall showroom summary. |
| **Accountant** | In-house or external bookkeeper | Records all financial transactions, runs reports and can reverse entries. Cannot change settings. |
| **Sales / Showroom staff** | Floor staff | Vehicles, customers, requests, follow-ups and sale **drafts**. No access to partner accounts. **Never sees purchase price, vehicle expenses, total cost, minimum price or profit** through any channel. |
| **Viewer** | Auditor, family member | Read-only. Whether a Viewer sees cost data is an OPEN QUESTION (Q-05). The default is no cost visibility. |
| **Platform Super Admin** | Our company | Tenants, plans and support. **Never** sees tenant financial data unless the tenant grants support access, and that access is audit-logged. |

**FACT.** A user can belong to several tenants (for example, a partner in two showrooms) and switches tenant in the UI.

**ASSUMPTION.** Each membership has exactly one role in the MVP. Custom per-tenant roles are a later feature, but the permission model is built for them from Phase 1.

---

## 3. Markets

| Market | Currency | Status | Notes |
|---|---|---|---|
| Egypt | EGP | **FACT** Phase 1 | Egypt ETA e-invoice/e-receipt: interface and stub adapter only in the MVP. Which tax obligations apply is an **OPEN QUESTION** (Q-11). |
| Qatar | QAR | **FACT** Phase 1 | No VAT currently; simple invoices (FACT, SPEC §4.14). Post-dated cheques are common (FACT, SPEC §4.8). |
| UAE, Saudi Arabia, Sudan | AED, SAR, SDG | **FACT** later | Must be added through configuration (`CountryPack`), not code rewrites. |

**ASSUMPTION.** A tenant operates in **a single currency**. There is no multi-currency ledger in the MVP (DECISIONS A-03).

---

## 4. MVP scope

**ASSUMPTION (A-01).** "MVP" means Phases 1–9 of SPEC §13. Phases 10–11 are post-MVP. The MVP acceptance demo (SPEC §13) is the end-to-end proof.

### 4.1 In scope, by module

| Module | Key capabilities | Phase |
|---|---|---|
| **Foundation** | Login, password reset, tenant switcher, AR (RTL, default) / EN (LTR) runtime switching, role- and flag-based menu, user invites | 1 |
| **Ledger core** | Chart of accounts seed, journal entries and lines with DB-level integrity, posting service, reversal, period lock, cash boxes and bank accounts, transfers, general expenses, other income, cash/bank book | 2 |
| **Partners** | Partners, effective-dated share history, contributions, withdrawals, drawings, loans to and from partners, expenses paid personally, partner statement and summary (screen, PDF, Excel) | 3 |
| **Vehicles** | Vehicle master data, stock numbers, VIN rules, location and price history, media and documents, purchase (paid or deferred), vehicle expenses (cash, credit, or paid personally by a partner), cost completeness, vehicle file, inventory list with aging, global quick search | 4 |
| **Suppliers** | Supplier records, expenses on credit, supplier payments and statements | 4 (DECISION D-30: the spec assigns no phase) |
| **Customers** | Customer records (buyer, seller, consignor), quick call logging and follow-ups | 4 (records), 6 (follow-ups) |
| **Sales** | Reservations and deposits (refund or forfeit), sale draft → post, cash/bank/mixed sales, trade-ins, sale contract/invoice print, sale cancellation | 4 |
| **Installments** | Schedule generator, mode (a) (mode (b) markup behind a setting), payments, deferred-papers register (promissory notes and post-dated cheques), bounced cheques, due/overdue board, calendar, in-app reminder job | 5 |
| **Consignment** | Consignment IN (agreements, recoverable expenses, settlement, return to owner, consignor statement) and consignment OUT (move, sale, commission, collections, external showroom statement) | 6 |
| **Customer requests** | Wanted list, matching alerts when a car becomes AVAILABLE | 6 |
| **Profit and reports** | Distribution policy (periodic or per car), preview and post, P&L, trial balance, general ledger, all 12 reports in SPEC §4.12, dashboard with Needs Attention, notification centre | 7 |
| **Import and onboarding** | Excel import wizard (template or own sheet, column mapping, validation preview, commit), opening journal entry, onboarding wizard | 8 |
| **SaaS layer** | Plans, limits, feature flags, subscription states (read-only when suspended), manual billing, super admin console, support-access grants, audit log viewer, PWA offline read, performance and security hardening, backup/restore runbook | 9 |
| **Country packs** | `CountryPack` abstraction (EG, QA), invoice numbering, `EgyptETAAdapter` interface with a stub | 4 (invoice), 9 (pack config). DECISION D-30 |

### 4.2 Starting business rules

**FACT (SPEC §3.4).** These rules live in the service layer, each has a test, and they will be catalogued in `docs/BUSINESS_RULES.md` (to be created in Phase 2):

1. A vehicle can be sold only once, unless its sale was cancelled.
2. No new payments against a cancelled sale.
3. A payment cannot exceed the outstanding amount unless the excess is explicitly recorded as customer credit.
4. Installment remaining = amount due − payments, always derived.
5. Profit uses recorded costs only; manually entered profit is never accepted.
6. Active partners' ownership percentages total 100% on every date.
7. A cash box cannot go negative unless the tenant setting allows it (warn or block).
8. No record may reference another tenant's data.
9. Posted financial records are corrected only by reversal.

### 4.3 Non-functional requirements (summary)

| Area | Requirement | Label |
|---|---|---|
| Money | `numeric(18,2)`, `Decimal` in Python, strings in TypeScript, no floats; default rounding ROUND_HALF_UP | FACT |
| Integrity | Ledger invariants enforced **in the database** (balanced entries, immutability, open period, gapless numbering) | FACT |
| Performance | Dashboard and lists in under 2 s for a tenant with 5,000 vehicles and 100,000 journal lines | FACT |
| Security | RLS on every tenant table; cross-tenant and cost-masking tests; private storage with short-lived signed URLs | FACT |
| UX | Arabic-first RTL, mobile-first, spreadsheet-simple, never shows "debit/credit" to non-accountants, plain-language preview before every posting | FACT |
| Offline | PWA offline **read-only** cache; financial writes are never queued offline | FACT |
| Accessibility | Keyboard navigation, sufficient contrast | FACT |
| Observability | Structured JSON logs, Sentry-compatible error tracking, basic metrics, health check | FACT |

### 4.4 Key mobile workflows (minimum taps)

**FACT (SPEC §9.3).** View the dashboard, search a car, add a car, add an expense (**under 15 seconds**), record a payment, log a call, view a car's profit, see what's due today.

---

## 5. Out of scope for the MVP

**FACT (SPEC §1.4, §13).** The architecture leaves room for these, but none of them are built in the MVP:

- WhatsApp chat CRM, marketplace multi-posting, a sales commissions module, a public marketplace website, AI pricing
- Payroll/HR, workshop or spare-parts management, insurance, a general-purpose ERP, a website builder
- Native iOS/Android apps (the PWA covers mobile)
- Microservices, Kubernetes, GraphQL, event-driven infrastructure
- **Phase 10:** real Egypt ETA integration, SMS/WhatsApp delivery, payment-gateway billing, car-level investors **UI** (the data model ships, behind a flag), Saudi ZATCA, UAE margin scheme, bank reconciliation (placeholder tables only), marketplace posting
- **Phase 11:** AI management assistant (read-only tools only)

**ASSUMPTION.** Items the spec does not mention are also out of scope: multi-currency, late-payment penalties, repossession accounting and bad-debt write-off. See DECISIONS G-12 and G-13.

---

## 6. MVP acceptance demo

**FACT (SPEC §13).** This runs as an automated Playwright E2E test:

> Owner creates the showroom → adds 3 partners and records capital → adds a car and records its purchase → adds transport, repair and license expenses → sees the true cost → staff adds a customer and a car request → the system shows the match → the customer pays a deposit → the sale is posted with a down payment and installments → the first installment is collected → the car's profit is shown → the dashboard, cash balance and partner balances update → the owner sees due payments, aging stock and the Needs Attention panel.

**ASSUMPTION.** The demo spans Phases 1–7, so it can only pass in full at the end of Phase 7. Each earlier phase automates the slice it has built (see [BACKLOG.md](BACKLOG.md)).
