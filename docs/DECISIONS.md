# DECISIONS: Contradictions, Gaps, Risks, Facts, Assumptions, Decisions and Open Questions

> Phase 0 register. The product owner approves or changes each **DECISION** and answers each **OPEN QUESTION**. Answers are recorded here with a date. Until a question is answered, the default stated in the spec (or the default below) applies, and the behaviour stays configurable (SPEC §14).
> ID prefixes: **C** contradiction · **G** gap · **R** risk · **F** fact · **A** assumption · **D** decision · **Q** open question · **P** candidate posting rule ([ACCOUNTING.md §5](ACCOUNTING.md#5-open-accounting-questions-not-implemented-until-answered)).

---

## Part 1: Contradictions in the spec (not silently fixed)

| ID | Where | Contradiction | Proposed resolution (needs approval) |
|---|---|---|---|
| **C-01** | §3.1 vs §4.3 vs §10 | §3.1 lists "vehicles master data" as direct browser CRUD through Supabase. But the status lifecycle is "enforced by a state machine in the backend" (§4.3), and §10 denies the base `vehicles` table to the sales role, the role that "manages vehicles". Direct CRUD would let the browser bypass the state machine and price history, and sales users could not write a table they cannot read | D-06: **all vehicle writes go through FastAPI**; reads use Supabase (`vehicles` or the `vehicles_catalog` view) |
| **C-02** | §1.2 vs §3.2 | §1.2: "code checks permissions, never role names". §3.2 specifies `memberships.role` and an RLS helper `has_role(tenant_id, roles[])`, which checks role names in SQL | D-10: `role_id` → `roles` → `role_permissions`; the RLS helper is `has_permission(tenant_id, perm)` |
| **C-03** | §4.2 / §3.4 vs §3.3 | Ownership must total "exactly 100%", but percentages are `numeric(9,4)`. Three equal partners give 33.3333 × 3 = 99.9999, which can never equal 100 | Q-09. Default: keep `numeric(9,4)`, require Σ = 100.0000, and have "split equally" give the 0.0001 remainder to one partner (e.g. 33.3334 / 33.3333 / 33.3333) |
| **C-04** | §4.9 policy 2 vs rules 22/23 | Rule 22 debits Retained Earnings (3300), but 3300 only receives profit at period close (rule 23). Distributing per car at sale time would debit 3300 before any profit has been closed into it, so it shows a temporary negative balance. General expenses "allocated periodically" also has no rule | Q-10; candidate P-10 |
| **C-05** | §6 vs §5 | COA 2700 "Payable to suppliers (subledger by supplier)", and §4.10 has supplier statements. But §5 has no `suppliers` table, and `journal_lines` has no `supplier_id` | D-23: add `suppliers` and `journal_lines.supplier_id` |
| **C-06** | Rule 33 vs §4.7 | Rule 33 = "reversal of the original sale entries". A mirror of a cash sale **credits Cash/Bank** on the cancellation date, as if the refund had already happened. §4.7 says refunds are "separate transactions". Installment receipts collected after the sale are not reversed by the mirror, so the receivable would show a credit balance | Q-12; candidate P-03 (reverse against a "refund payable to customer" liability, then refund separately) |
| **C-07** | §15 | "Sum of partner balances + liabilities = assets" only holds when all profit has been closed and distributed **and** Opening Balance Equity (3900) is zero. Any undistributed profit, current-period P&L or opening balance equity breaks it | Implement the standard check **assets = liabilities + equity (incl. 3300, 3900 and the current-period result)**, and report the partner-only version separately. Needs approval |
| **C-08** | §11 | "Banker's rounding only where explicitly specified": the spec specifies it nowhere | ROUND_HALF_UP everywhere (A-07) |
| **C-09** | §4.8 vs §4.12 | The main dashboard's upcoming window is "next 48 hours" in §4.8, but the dashboard shows "collections due in the next 7 days" in §4.12 | Q-32. Default: the dashboard shows both "due in 48 h" (Needs Attention) and a "next 7 days" KPI tile |
| **C-10** | §4.8 | "Overdue" is listed as a deferred-paper status beside physical states (held, deposited…). It is time-derived, and storing it would go stale | Derive overdue; store only physical states (ERD §6) |
| **C-11** | Rules 30, 31 vs rule 10 / §4.4 | Rules 30 and 31 always debit Vehicle Inventory. For a CONSIGNED-IN car, rule 10 and §4.4 say expenses are recoverable from the consignor and **not** capitalized | Default: when the car is CONSIGNED_IN, rules 30/31 debit 1430 (recoverable) instead of 1300. Needs approval (Q-15) |
| **C-12** | §4.3 | `CONSIGNED_OUT` is mentioned like an ownership type, but the ownership types are only `OWNED` and `CONSIGNED_IN`; consigned-out is a status (`AT_OTHER_SHOWROOM`) | Treat it as a status/location, not an ownership type |
| **C-13** | §4.12 #7 vs §4.8 | The report is called "Promissory notes register", but the register covers notes **and** post-dated cheques | Rename to "Deferred papers register" |
| **C-14** | §13 vs §15 | §15 requires a CI balance check against the seed data for every feature, but the demo seed is only described in §12 and has no phase | The seed grows from Phase 2 and is completed in Phase 9 (BACKLOG 9.11) |

---

## Part 2: Gaps in the spec

| ID | Gap | Impact | Handling |
|---|---|---|---|
| **G-01** | No posting rule for **other income** (§4.10 module, COA 4900) | Phase 2 | Q-26 / P-01 |
| **G-02** | Business rule 3 allows "customer credit", but there is no account or rule for it, and no rule for refunding a customer other than deposits | Phases 4–5 | Q-13 / P-02 |
| **G-03** | Expenses arriving after the car is sold (late invoices): crediting a sold car's inventory would leave a balance on 1300 | Phase 4 | Q-14 / P-04. Default: blocked with an error |
| **G-04** | Share changes made one partner at a time pass through invalid totals | Phase 3 | D-21 (batch + deferred check) |
| **G-05** | No consignor reimbursement rule when a car is returned unsold ("settle any recoverable expenses", §4.4) | Phase 6 | P-06 |
| **G-06** | Idempotency is required, but §5 has no table for it | Phase 2 | D-17 |
| **G-07** | No rule for allocating a **loss** to partners | Phase 7 | Q-10 / P-09 |
| **G-08** | Account 2500 "Taxes payable" exists, but no posting rule includes tax; sale invoices have no tax lines | Phases 4, 10 | Q-11 / Q-06; P-11 has no candidate |
| **G-09** | Other channels that could leak cost data: purchase contracts in Storage, audit diffs, notification texts, exports, search | Phase 4 | ARCHITECTURE §5; `documents.sensitivity` |
| **G-10** | Consignment-in edge cases: showroom-borne or shared expenses (which account? what split?), a sale below the agreed net price, an installment or deferred sale of a consigned car (when the consignor gets paid) | Phase 6 | Q-15 / P-05 / P-14 |
| **G-11** | When a cheque counts as "collected" for the ledger; bank charges on bounced cheques | Phase 5 | A-10, Q-20 / P-07 |
| **G-12** | Late-payment penalties and early-settlement discounts on installments | Later | Out of scope until requested (P-13) |
| **G-13** | Repossession of a car after default; bad-debt write-off ("defaulted / in legal process" statuses exist with no accounting) | Later | Out of scope until requested (P-13) |
| **G-14** | Features with no phase: suppliers, invoices/CountryPack/ETA stub, Needs Attention engine, notification centre, follow-ups, trade-in, sale cancellation, global search, user invites, other income, branches | Planning | D-30 (BACKLOG ⚑) |
| **G-15** | Phases 6 and 9 have no acceptance criteria | Planning | Proposed in BACKLOG; needs approval |
| **G-16** | No table for tenant-granted support access (§4.16) | Phase 9 | `support_access_grants` added |
| **G-17** | National IDs must be "encrypted or masked", but customers are written directly through Supabase, so the browser cannot encrypt server-side | Phase 3/4 | D-05 |
| **G-18** | "Days in stock" has no defined start date (purchase date? arrival at the yard? agreement date for consigned cars?) | Phase 4 | Q-24 |
| **G-19** | How sale discounts appear in the ledger | Phase 4 | Q-22 / P-12 |
| **G-20** | Mode (b) markup recognition method; early payoff | Phase 5 | Q-03 |
| **G-21** | "Partner net balance" and "drawings exceeding his balance" are not defined | Phase 3 | Q-17 |
| **G-22** | Whether a capital withdrawal (rule 2) or a contribution changes ownership % | Phase 3 | Q-19 |
| **G-23** | Sale cancellation when the trade-in car has already been sold or has expenses, or when the car has been DELIVERED | Phase 4 | Q-30 |
| **G-24** | Arabic terminology is Egyptian ("ملف العربية"), but Qatar is also a Phase 1 market, and Gulf users say "السيارة" | Phase 1 | Q-25 |
| **G-25** | How often rule 23 period-close entries are posted (monthly? only at distribution? year end?) | Phase 7 | Q-27 |
| **G-26** | "Invite by phone" needs an SMS provider (cost, sender ID per country); the MVP has no-op providers only | Phase 1 | Q-29; email invites only by default |
| **G-27** | Role details are missing: does Manager see minimum price? Does Viewer see cost? Who may take deposits? Who may lock periods? | Phase 1 | Q-05 |
| **G-28** | Vehicle profit for an externally sold car: before or after the external commission (6100)? | Phase 6 | Q-34 |
| **G-29** | Gapless numbering for **invoices** (Egypt ETA may require it) vs voided drafts | Phase 4 | Numbers are assigned only at posting; Q-06 |
| **G-30** | Hosting for FastAPI and the worker is not specified | Phase 1 | Q-28 |

---

## Part 3: Risks

| ID | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| **R-01** | The discovery evidence comes from **one** Egyptian showroom. The Qatar needs (PDCs, VAT absence, terminology) and the distribution policy are unvalidated | High / High | Interview 3–5 more showrooms (including at least 1 in Qatar) before Phase 5; keep modules loosely coupled (FACT §1.4) |
| **R-02** | The MVP (Phases 1–9) is large, so time-to-first-pilot is long | High / High | Suggest a **pilot cut** after Phase 4 (ledger + partners + vehicles + cash sales) with the interviewed showroom (Q-36) |
| **R-03** | Data residency. Supabase has no Middle East region. Egypt's PDPL executive regulations (in force 2025-11-02, compliance deadline 2026-11-01) require a PDPC cross-border licence **and** data-subject consent for transfers abroad. Saudi PDPL has its own transfer rules | High / High | Q-21 / D-38: develop on Frankfurt without real personal data; get Egyptian counsel's opinion; be ready to move Egyptian tenants to hosting in Egypt (self-hosted Supabase); keep national IDs optional |
| **R-04** | Per-tenant gapless counter serializes postings | Low / Medium | Lock the counter last and briefly; fine at showroom volumes; load test in 9.7 |
| **R-05** | Supabase pooler (transaction mode) vs session settings and prepared statements | Medium / High | psycopg 3 without server-side prepared statements, or a direct/session connection; `set_config(..., true)` per transaction (D-01, D-09) |
| **R-06** | The offline PWA cache stores financial data on phones that may be shared or lost | Medium / Medium | Cache only the dashboard and last lists, clear on logout, never cache cost data for masked roles, short max-age |
| **R-07** | Promissory notes (إيصالات أمانة) and cheques carry legal weight; scans are sensitive | Medium / High | Private storage, `sensitivity`, audit of access. **We give no legal advice and add no legal workflow** |
| **R-08** | "Financing markup" may be sensitive under Islamic finance norms in Qatar or Egypt (wording, contract templates) | Medium / Medium | Mode (a) default; wording per CountryPack; Q-03 |
| **R-09** | Egypt ETA integration probably needs document signing (e.g. a hardware token or HSM) and a certified integration process. *ASSUMPTION: to be verified* | Medium / High (Phase 10) | Keep the stub interface; research before Phase 10 |
| **R-10** | `numeric(18,2)` fixes 2 decimals; 3-decimal currencies (KWD, BHD, OMR) would need a migration | Low / Low | Not on the roadmap; noted |
| **R-11** | Messy Excel history yields wrong opening balances, and every later report inherits the error | High / High | Validation preview, a signed-off opening trial balance, a pilot sheet fixture (Q-35) |
| **R-12** | "Latest stable" Angular and PrimeNG versions may be briefly incompatible | Low / Medium | Pin compatible majors in Phase 1 and record them here |
| **R-13** | Supabase-specific features (Auth, Storage, RLS on `auth.uid()`) create vendor lock-in | Low / Medium | Plain Postgres + SQL migrations; self-hosted Supabase as the exit path |
| **R-14** | Owner and accountant accounts hold full financial power; 2FA is optional | Medium / High | Recommend enforcing TOTP for those roles (Q-37) |
| **R-15** | With no tax rules (D-39), a tenant that is in fact obliged to issue e-receipts or charge VAT gets no help from the product | Medium / Medium | Tax and e-invoicing remain extension points (CountryPack, ETA adapter); revisit with the first paying Egyptian tenants |
| **R-16** | **PrimeNG licence changed.** Every PrimeNG version that supports Angular 22 is under the commercial *PrimeUI License*. The free Community License covers organisations with < $1M revenue, < 5 developers, < 10 employees and < $3M outside funding, needs a licence key and annual renewal. Larger organisations pay per developer. Without a key the app shows an *Invalid PrimeUI License* badge to every user | High / High | Q-38: decide before any pilot; options listed there |
| **R-17** | The deferred balance check would only fire at commit; the API forces it to run immediately after each posting (`SET CONSTRAINTS ALL IMMEDIATE`) so errors surface inside the service. A code path that posts without the engine would still be caught at commit, just with a less friendly error | Low / Low | All postings go through `engine.post` / `engine.reverse` |

---

## Part 4: Facts (from SPEC.md, summarised)

| ID | Fact |
|---|---|
| F-01 | Multi-tenant SaaS for car showrooms; Egypt (EGP) and Qatar (QAR) first; UAE, KSA and Sudan later via configuration |
| F-02 | Fixed stack: Angular + PrimeNG + PWA; FastAPI (Python 3.12+, Pydantic v2); Supabase (Postgres, Auth, Storage, RLS); Supabase SQL migrations only (no Alembic); WeasyPrint; openpyxl; pytest; Playwright; GitHub Actions; Docker |
| F-03 | The browser never writes financial tables; FastAPI performs all money movement in one transaction with explicit tenant checks |
| F-04 | Shared schema with `tenant_id` + RLS everywhere; users may belong to several tenants; cross-tenant isolation tests are mandatory |
| F-05 | Money `numeric(18,2)`, Decimal in Python, strings in TS; no float |
| F-06 | Posted entries are immutable; corrections only by reversal; DB-enforced balanced entries, open period, gapless `entry_no`, single posting function |
| F-07 | 35 posting rules (SPEC §7), each a tested function, with tests written before the endpoints |
| F-08 | Sales role never sees cost, expenses, minimum price or profit (API, DB, UI) |
| F-09 | Partnership is showroom-level in the MVP UI; the car-level investor data model ships behind a flag |
| F-10 | Distribution policy: periodic (default candidate) or per car; preview before posting; payout is a separate drawing |
| F-11 | Installment mode (a) is the default; mode (b) markup is available in settings |
| F-12 | Qatar: no VAT currently. Egypt: ETA adapter interface + stub in the MVP |
| F-13 | Notification providers (SMS/WhatsApp) are no-op in the MVP; in-app only |
| F-14 | The AI assistant (Phase 11) is read-only and comes after the data model is stable |
| F-15 | Phase 0 needs product-owner approval before Phase 1 starts |

---

## Part 5: Assumptions

| ID | Assumption |
|---|---|
| A-01 | "MVP" = Phases 1–9; Phases 10–11 are post-MVP |
| A-02 | One role per membership in the MVP |
| A-03 | A tenant uses a single currency; no multi-currency ledger |
| A-04 | Gregorian dates only; fiscal periods are calendar months; the fiscal year start month is a setting |
| A-05 | The tenant's timezone defines the accounting date and period of a transaction |
| A-06 | Customers, sellers and consignors are one `customers` table with flags; suppliers and external showrooms are separate |
| A-07 | ROUND_HALF_UP at 2 dp everywhere (no banker's rounding anywhere) |
| A-08 | Schedule rounding remainder goes on the last installment (FACT); distribution rounding remainder uses largest remainder (pending Q-18) |
| A-09 | A sale can happen without a prior reservation (AVAILABLE → SOLD) |
| A-10 | A cheque reaches the ledger (rule 15) when its status becomes COLLECTED; a bounce before that is status-only |
| A-11 | Photo compression targets (WebP, 1600 px, ~80%) are reasonable defaults |
| A-12 | Showroom volumes (≤ a few hundred postings/day/tenant) make per-tenant serialized posting acceptable |
| A-13 | Email is the primary invite channel; phone invites wait for an SMS provider |
| A-14 | Partners and staff use modern mobile browsers that support PWA (Chrome on Android; Safari on iOS with its PWA limits) |
| A-15 | The Supabase CLI's local default keys (publishable/secret) are the same on every machine, so `.env.example` values work in CI unchanged |

---

## Part 6: Decisions (proposed; need approval)

| ID | Decision | Reason |
|---|---|---|
| D-01 | SQLAlchemy 2.x Core + psycopg 3 (no ORM for financial writes) | Explicit SQL, pooler compatibility (R-05) |
| D-02 | Transloco for i18n | Runtime switching, lazy scopes |
| D-03 | Separate worker container (same image) with APScheduler + advisory locks | No duplicate jobs when the API scales |
| D-04 | Settings writes go through the API | They create ledger accounts; audit |
| D-05 | National IDs are written and read (unmasked) only via the API, encrypted at the application level (AES-GCM, key in an env/secret manager); the table holds ciphertext + last 4 digits for display | §10 masking + audit |
| D-06 | All vehicle writes go via the API (resolves C-01) | State machine, price history, masking |
| D-07 | Posting rules are pure Python; `post_journal_entry()` SQL `SECURITY DEFINER` is the only insert path | Testability + DB enforcement |
| D-08 | FastAPI uses a dedicated `app_api` DB role without BYPASSRLS, with tenant-scoped RLS | Defence in depth |
| D-09 | Transaction-local `set_config` for tenant/user context | Pooler-safe |
| D-10 | `roles` + `role_permissions`; `has_permission()` in RLS (resolves C-02) | Permission-based auth |
| D-11 | Composite `(tenant_id, id)` foreign keys everywhere | DB-level business rule 8 |
| D-12 | Balances via indexed aggregates; a summary table only if Phase 9 performance needs it (maintained in the posting transaction) | Simplicity first |
| D-13 | Row locks: cash account → vehicle → counter | Correct cash-negative checks, no deadlocks |
| D-14 | Permission catalogue + default role bundles (ARCHITECTURE §7) | Starting point; see Q-05 |
| D-15 | Storage bucket layout and signed URL lifetimes (5 min view / 15 min upload) | Security |
| D-16 | `CountryPack` shape (ARCHITECTURE §9) | Configuration over code |
| D-17 | `idempotency_keys` table; key required on money POSTs; 7-day retention | FACT §3.3 |
| D-18 | Accounting dates are `date` in the tenant timezone | Correct periods |
| D-19 | Document status pattern DRAFT → POSTED → CANCELLED/REVERSED with `journal_entry_id` | Uniform UX |
| D-20 | One `tenant_counters` table for all sequences | Gapless, simple |
| D-21 | Share changes as a batch + deferred 100% check + no-overlap exclusion | G-04 |
| D-22 | `call_logs` → `follow_ups` | Covers visits and test drives too |
| D-23 | Add `suppliers` + `journal_lines.supplier_id` (resolves C-05) | |
| D-24 | `promissory_notes` → `deferred_papers` (+ events) | Notes and cheques |
| D-25 | A missing accounting period row is auto-created as OPEN on first posting | No manual setup |
| D-26 | Vehicle cost = derived balance of 1300 per vehicle; cost breakdown = its lines | Single source of truth |
| D-27 | COA header accounts are non-postable; sub-accounts auto-created per cash account and general category | Clean TB |
| D-28 | Sale and cost recognition are two linked entries in one transaction | Readability, clean reversal |
| D-29 | Closing entries are flagged and excluded from P&L | The P&L still shows activity after close |
| D-30 | Phase placement of unassigned features (BACKLOG ⚑) | G-14 |
| D-31 | Every money command has a `preview` twin returning the plain-language summary | §9.3 previews come from the same posting code |
| D-32 | Tenant id in the URL (`/t/:tenantId/...`) | Deep links, multi-tenant users |
| D-33 | Design tokens (FRONTEND §6) | Consistent serious look |
| D-34 | Profit is never stored on `sales`; always derived | Business rule 5; masking |
| D-35 | A posted sale by an external showroom is a `sales` row (`channel = EXTERNAL_SHOWROOM`) | One "sold once" rule |
| D-36 | A cancelled sale keeps its row (status CANCELLED) and links to the reversal entries | Audit trail |
| D-37 | Audit log partitioned monthly; no UPDATE/DELETE for any role | Volume + append-only |
| D-38 | **Approved 2026-10-02.** Development, testing and the pilot run on Supabase Cloud **Frankfurt (eu-central-1)**. Only synthetic or anonymised data goes in until the hosting question is settled. The deployment stays region-agnostic (one deployment per country is possible, with each tenant pinned to one), so Egyptian tenants can move to hosting in Egypt without code changes | Q-21, R-03 |
| D-39 | **Approved 2026-10-02 (Q-06, Q-11).** The product implements **no tax rules**: no VAT or other tax lines in any posting rule, no tax on invoices, and no e-invoice submissions. Account 2500 is seeded but unused. The `CountryPack` tax profile and the `EgyptETAAdapter` interface stay as empty or stub extension points so tax can be added later as configuration. The tenant remains responsible for its own tax compliance | Product owner decision; see R-15 |
| D-40 | **Approved 2026-10-02 (Q-02, Q-10, Q-18, Q-27).** Profit distribution is fully **tenant-configurable** in Settings → Profit policy. Each option has a default that applies if the tenant leaves it unset:<br>• **Policy:** `PERIODIC` (default) or `PER_CAR`.<br>• **Frequency** (periodic): `AD_HOC` (default; the owner picks the date range), `MONTHLY`, `QUARTERLY` or `YEARLY`. The frequency only drives the reminder and the suggested range; the owner still previews and posts.<br>• **Loss handling:** `ALLOCATE_TO_PARTNERS` (default; a loss is charged to partner current accounts by %, P-09) or `CARRY_FORWARD` (the loss stays in 3300 and offsets future profit before the next distribution).<br>• **Pro-rata when % changes mid-period:** `DAY_WEIGHTED` (default) or `SUB_PERIOD_PROFIT` (actual profit computed per sub-period between share changes).<br>• **Rounding remainder:** `LARGEST_REMAINDER` (default) or `LARGEST_SHARE` (to the partner with the largest %).<br>• **Per-car mechanics (C-04, P-10):** with `PER_CAR`, each posted sale allocates its gross profit through a clearing account **3310 Profit allocated in advance** (Dr 3310 / Cr 3200 per partner). At period close, rule 23 closes net profit into 3300, and the 3310 balance is netted against 3300. General expenses and other income for the period are then allocated by the periodic rules (loss handling applies). Changing the policy is allowed only at the start of an unclosed period | Owner choice; defaults keep the spec's behaviour |
| D-41 | **Approved 2026-10-02 (Q-12, Q-13).** Sale cancellation and customer credit are **tenant-configurable** in Settings → Sales:<br>• **Cancellation method:** `REFUND_LIABILITY` (default; P-03) or `MIRROR` (literal rule 33). `REFUND_LIABILITY` reverses revenue and cost and moves every amount the customer has paid (deposit applied, cash legs, installments collected) to **2310 Customer credits / refunds owed**. The actual refund, forfeit or reuse is posted separately. `MIRROR` posts the exact opposite of the original sale entries on the cancellation date; installments collected after the sale must be refunded or credited first, otherwise the cancellation is blocked with `SALE_HAS_COLLECTIONS`.<br>• **Overpayments:** `BLOCK` (default; business rule 3) or `ALLOW_AS_CREDIT`. With `ALLOW_AS_CREDIT`, the user must tick "keep the excess as customer credit" on that payment; the excess posts Dr Cash / Cr 2310 (customer). The credit can be applied to a later sale or installment, or refunded (Dr 2310 / Cr Cash).<br>• **Default rationale:** `REFUND_LIABILITY` is the default because `MIRROR` lowers the bank balance before any refund has actually been paid (C-06). The owner can switch to `MIRROR` | Owner choice |
| D-42 | **Phase 1.** Public signup is off until the Phase 9 signup flow; users join by invitation. Invitations use Supabase Auth's admin invite (the user sets a password from the email link), so no `invitations` table is needed (ERD §2 listed one). An email that already has an account (e.g. a partner in another showroom) just gets a membership | Simpler; Supabase handles tokens and expiry |
| D-43 | **Phase 1.** Added `tenant_role_permission_overrides` (per-tenant grant/revoke on a role bundle, e.g. "Manager may post sales") and `role_permission_restrictions` (permissions a role may never hold, e.g. sales → cost). The restriction is enforced by trigger, so no configuration can give sales staff cost visibility | SPEC §1.2, §10 |
| D-44 | **Phase 1.** Added a `country_packs` reference table (EG, QA); `tenants.country_code` references it. A new country is a new row | SPEC §1.3 |
| D-45 | **Phase 1.** Audit log monthly partitioning (D-37) is deferred to Phase 9, when real volumes are known; the table is append-only now (triggers block UPDATE/DELETE/TRUNCATE for every role) | Avoid premature complexity |
| D-46 | **Phase 1.** `locations` (yard, workshop, external showroom…) move to Phase 4 with vehicles; Phase 1 has `branches` only | They reference external showrooms (Phase 6) |
| D-47 | **Phase 1.** Signing out ends the session on the current device only (Supabase default would sign the user out everywhere) | The owner's phone stays signed in when they sign out on the office PC |
| D-48 | **Phase 1.** Password policy: at least 10 characters with upper case, lower case and a digit (Supabase Auth config + UI validation) | SPEC §10 strong password policy |
| D-49 | **Phase 1.** Local development runs a reduced Supabase stack (Postgres, Auth, REST, Storage, Mailpit; no Studio/analytics) | The full stack was unstable on a developer laptop |
| D-50 | **Phase 1.** The API role needs no access to the `auth` schema: the acting user is read from the request settings, and two narrow SECURITY DEFINER functions expose member emails to user management | Least privilege |
| D-51 | **Phase 1.** Initial JS bundle budget raised to 1 MB warning / 2 MB error (actual: 842 kB raw, 193 kB compressed), mainly PrimeNG + supabase-js | Revisit in Phase 9 performance work |
| D-52 | **Phase 2.** No posting may be dated after today in the showroom's timezone (back-dating into open months is allowed) | Prevents typos like 2062; post-dated cheques are recorded on collection (A-10). Configurable later if needed |
| D-53 | **Phase 2.** A cash box or bank account can be archived only with a zero balance | Money must never disappear from the balance sheet |
| D-54 | **Phase 2.** Journal tables have no row-change audit triggers: the ledger is append-only and stores `created_by`, so it is its own audit trail. Accounting-period changes and documents are audited | Avoids duplicating every line in audit_log |
| D-55 | **Phase 2.** The ledger functions are owned by the migration owner (`postgres`) rather than a separate `ledger_owner` role (ARCHITECTURE §3). Effect is the same: client roles have no write grants on journal tables and reach them only through `post_journal_entry` / `reverse_journal_entry` | One fewer role to manage on Supabase |
| D-56 | **Phase 2.** PDF reports render where WeasyPrint's native Pango libraries exist (Docker image, CI, Linux). On a Windows dev machine without them, the PDF endpoint returns `PDF_UNAVAILABLE` (503); Excel works everywhere | WeasyPrint is fixed by SPEC §2; GTK on Windows is fragile |
| D-57 | **Phase 2.** Angular API types are generated from the FastAPI OpenAPI schema (`npm run api:types`). `openapi-typescript` runs in an isolated `npx` environment with TypeScript 5 because it does not yet support the TypeScript 6 used by Angular 22. CI fails if the committed schema or types drift from the API | Single source of truth for contracts (BACKLOG 1.10) |
| D-58 | **Phase 2.** The cash book (and other reports) are exported with the showroom's report file name; the API exposes `Content-Disposition` through CORS so browsers keep it | Found by E2E: downloads were all named cash-book.xlsx |
| D-59 | **Phase 2.** Rule 21 transfer descriptions default to "تحويل من X إلى Y"; expense descriptions default to the category name. Users can override both | Readable cash book without typing |
| D-60 | **Phase 2.** Arabic sentences isolate dates and codes with Unicode directional isolates so they are not reordered by right-to-left text | Found by screenshot review |
| D-61 | **Phase 3.** The PrimeUI licence key is injected at build time from the `PRIMEUI_LICENSE` environment variable (`--define`) and passed to `providePrimeNG`. It is never committed; an empty key builds and runs locally | Q-38 answer: keep PrimeNG |
| D-62 | **Phase 3.** A partner counts as *active* while they hold an open share. A partner can be archived only with no open share and a zero balance in all four buckets (`PARTNER_NOT_SETTLED`) | Money and ownership must never disappear |
| D-63 | **Phase 3.** A loan repayment (rules 5 and 29) cannot exceed what is currently owed (`REPAYMENT_EXCEEDS_LOAN`). A drawing above the partner's net position, or a capital withdrawal that makes capital negative, posts with a warning (`DRAWING_EXCEEDS_BALANCE`, `CAPITAL_NEGATIVE`), the same WARN approach as BR-C1 | Overpaying a loan has no accounting meaning; over-drawing is a business choice the owner must see, not a block (Q-17 net formula) |
| D-64 | **Phase 3.** A share change is a full batch for **all** partners, effective from a date after the latest change. Earlier history cannot be rewritten; a mistake is corrected by a newer batch | Append-only history (FACT); avoids retroactive changes to past distributions |
| D-65 | **Phase 3.** National IDs are encrypted in the API with AES-256-GCM (`NATIONAL_ID_KEY`, never committed); the row id is bound as associated data so a ciphertext cannot be moved to another row. Lists show only the last 4 digits; revealing the full number needs `partner.equity.change` and is audit-logged (`NATIONAL_ID_VIEWED`) | SPEC §10 "encrypted or masked" (G-17, D-05). Key rotation is a Phase 9 task |
| D-66 | **Phase 3.** One user can be linked to at most one partner per showroom, and a partner to at most one user (`PARTNER_ALREADY_LINKED`). The link is set in Settings → Users | Partner self-service (3.5) needs an unambiguous "own" record |
| D-67 | **Phase 3.** An expense paid personally by a partner (rule 30) is a `general_expenses` row with no cash account; the user chooses current account or loan to the business. The cash box is not touched | ERD §3 design, now implemented for general expenses (vehicle expenses in Phase 4) |
| D-68 | **Phase 4.** Customers are written through the API, not directly through Supabase (BACKLOG 4.4 said "via Supabase"): phone numbers are normalised to E.164 by country pack, national IDs are encrypted as for partners (D-65), and a phone that already belongs to a customer is refused with `CUSTOMER_PHONE_EXISTS`, offering the existing record | One place for normalisation and encryption; phone-first search needs no duplicates |
| D-69 | **Phase 4.** The VIN is unique among cars still with the showroom: archived, delivered and returned-to-owner cars do not block their VIN | A car sold earlier can come back as a trade-in. The spec says "among non-archived vehicles" |
| D-70 | **Phase 4.** Users change a car's status directly only for: DRAFT→IN_PREPARATION, IN_PREPARATION→AVAILABLE, SOLD→DELIVERED, and archiving (DRAFT/IN_PREPARATION/AVAILABLE). RESERVED, SOLD and the return to AVAILABLE after a cancelled sale happen only through the deposit and sale commands, and the database refuses SOLD without a posted sale. A car with recorded cost cannot be archived (`VEHICLE_HAS_COST`). Delivery moves the car to the "with customer" location | Money and status never disagree (like D-53) |
| D-71 | **Phase 4.** A car's cost = its balance on 1300 plus anything charged to 5000 for it (P-04 late expenses); its profit = 4100 − 5000 for it; profit % is of the sale price. The cost breakdown lists its 1300 lines (except the cost-of-sale transfer) and its P-04 lines. Profit is shown as an estimate while an expected cost category is missing | D-26, D-34; the spec's "estimate, missing: …" |
| D-72 | **Phase 4.** A deposit is refunded or forfeited in full (rules 34/35); a partial refund with partial forfeit is not offered until requested (Q-39). Expiry is shown, not acted on: an expired reservation stays until the user settles it. A deposit restored by a MIRROR cancellation is RELEASED (held, car free) until settled | The spec says "refund or forfeit (configurable per case)" without a split |
| D-73 | **Phase 4.** A Phase 4 sale is fully covered by payments, the deposit and the trade-in (`SALE_AMOUNTS_MISMATCH` otherwise); deferred and installment sales arrive with Phase 5. A car can be sold only after its purchase is recorded (`VEHICLE_COST_MISSING`, business rule 5). The sale price posted to 4100 is the net price after discount (P-12) | No receivable without its schedule (rule 13) |
| D-74 | **Phase 4.** Storage buckets are private with **no** browser storage policies: the API issues 15-minute upload URLs and 5-minute view URLs with the service-role key after its own permission checks, and accepts an uploaded file only under the record's own path. Photos are compressed in the browser (WebP, 1600 px, 80%, A-11) | Simpler and stricter than path-based storage RLS (ARCHITECTURE §8) |
| D-75 | **Phase 4.** Journal reversal refuses entries owned by a document action: sale, cost of sale and cancellation entries (use cancel sale) and deposit entries (use settle deposit). A purchase or capitalised expense of a sold car cannot be reversed, and a purchase with later payments to the seller needs those reversed first | Reversal must not leave documents and the ledger disagreeing |
| D-76 | **Phase 4.** Cancelling a sale with a trade-in hands the trade-in car back: allowed only while that car is untouched (not sold or reserved, no expenses), it is archived and its value leaves inventory (to the customer's credit with REFUND_LIABILITY, mirrored with MIRROR). A delivered car's sale cannot be cancelled (Q-30 default) | G-23; needs approval |
| D-77 | **Phase 4.** Numbers: stock `V-YYYY-NNNN` when the car is created, sale `S-YYYY-NNNN` when the draft is created, invoice `{prefix}-YYYY-NNNNN` from the country pack only when posting (G-29). The Egypt ETA adapter is a stub that records `NOT_SUBMITTED`; no tax lines (D-39) | D-16, D-20 |
| D-78 | **Phase 4.** Sales staff prepare sale drafts without payment lines (they cannot see cash accounts); the accountant or owner adds the payments and posts. Sales staff see posted sales and their own drafts | ARCHITECTURE §7: sales has no cash access |
| D-79 | **Phase 4.** Payments to a seller (rule 8), a supplier (rule 32) and refunds of customer credit (P-02) are capped at what is owed (`PAYMENT_EXCEEDS_BALANCE`, `REFUND_EXCEEDS_CREDIT`) | Same as D-63 |
| D-80 | **Phase 4.** The printed sale contract records the parties, the car, the price and how it was paid, with signature lines, and contains no legal clauses; the invoice has no tax lines | R-07: no legal advice. The showroom's own contract terms are Q-40 |
| D-82 | **Phase 5.** Installment sales use mode (a) only (rule 13): the installment total is the sale price. Mode (b) markup (rules 14 and 15b) stays locked until Q-03 settles how the markup is recognised | SPEC §4.8 default; nothing invented |
| D-83 | **Phase 5.** A receipt belongs to one plan and is allocated to the oldest open installment first (a cheque pays its own installment first). Paid and remaining are derived from allocations of receipts that still count (`installment_status` view); a receipt locks its plan row | Business rule 4; no double collection under concurrency |
| D-84 | **Phase 5.** Overpayments follow the tenant option (D-41): `BLOCK` refuses (`PAYMENT_EXCEEDS_OUTSTANDING`); `ALLOW_AS_CREDIT` keeps the excess as customer credit only when the user ticks it (P-02). Customer credit can pay an installment (Dr 2310 / Cr 1400) or be refunded | Business rule 3 |
| D-85 | **Phase 5.** Deferred papers: notes HELD → RETURNED / DEFAULTED → LEGAL; cheques also DEPOSITED, COLLECTED, BOUNCED (and re-presented). Collection posts the receipt (A-10); a bounce after collection posts rule 27, marks the receipt BOUNCED (the installment reopens), notifies everyone with `installment.view`, and can post bank charges (P-07) to the new account **6270 Bank charges** or recharge them to the customer (1410). A bounce before collection is status-only. OVERDUE is derived (C-10). A cancelled sale's held papers are returned automatically | SPEC §4.8, approved P-07 |
| D-86 | **Phase 5.** Reminders: a worker (`python -m app.jobs`, same image) wakes hourly, takes an advisory lock, and per tenant once a day creates in-app notifications for installments due within `attention_thresholds.installment_due_days` (default 2) — once per installment — and for overdue installments — once when they become overdue — to every member with `installment.view`. SMS/WhatsApp providers only log (F-13) | D-03; avoids daily repeats of the same alert |
| D-87 | **Phase 5.** The dashboard shows installment tiles for the next 48 hours and the next 7 days, overdue and bounced cheques; the installments board defaults to overdue | C-09 default |
| D-88 | **Phase 5.** Cancelling an installment sale: REFUND_LIABILITY owes the customer the down payment, deposit and collected installments, clears the outstanding receivable, cancels the plan and returns held papers; MIRROR is refused while installments are collected (`SALE_HAS_COLLECTIONS`, D-41). Installments of a cancelled sale take no payments (business rule 2) | P-03 |
| D-89 | **Phase 5.** The unpaid part of a sale is always an installment plan ("pay later" = one installment), never an open receivable without due dates | Due lists, reminders and statements need due dates |
| D-90 | **Phase 5.** Monthly and quarterly due dates keep the first date's day, clamped to the month's end (31 Jan → 28 Feb); the equal split rounds half-up with the remainder on the last installment and refuses splits that would leave an installment at zero | SPEC §4.8, A-07 |
| D-81 | **Phase 4.** Days in stock start at the purchase date (Q-24 default) and, for a trade-in car, at the sale date that brought it in; aging colours follow the tenant's thresholds (default 30/60/90) | Q-24 |
| D-91 | **Phase 6.** A consigned-in car is a vehicle with ownership CONSIGNED_IN, created together with its agreement (one agreement per car); the owner is a customer flagged as consignor (A-06). Days with us start at the agreement date (Q-24). A fixed or percentage commission must be above zero; with net-price terms the sale must be **above** the net (Q-15 default blocks below-net sales; at the net the showroom earns nothing, which entry B cannot record). A consigned car is never archived; it leaves by a sale or a return to its owner | SPEC §4.4, Q-15, Q-33 |
| D-92 | **Phase 6.** External showrooms are their own records (not customers), each with a yard location of type EXTERNAL_SHOWROOM. Sending a car out moves it to that yard (status AT_OTHER_SHOWROOM, location history shows where and since when); only owned cars in preparation or available can be sent (Q-33: no re-consignment; a reserved car stays) | SPEC §4.5 |
| D-93 | **Phase 6.** An expense on a consigned car takes its treatment from the agreement, whatever paid it (cash, supplier credit, partner): OWNER → 1430 recoverable (rule 10; C-11 default for rules 30/31), SHOWROOM → the new account **6280 Consigned-car expenses** (P-05), SHARED → split by the owner's percentage written in the agreement (half-up on the owner's part, A-07). Expenses are refused once the consignment is sold or returned (the owner's account is then settled) | P-05 approved; the split % is a contract term, not an accounting rule |
| D-94 | **Phase 6.** A consigned car is sold through the normal sale draft. Posting writes rule 16 entry A (the full price owed to the owner) in place of revenue, and entry B (commission + recovered expenses) in place of cost of sale; expenses are recovered up to the price less the commission, any rest stays recoverable (P-06). Installments are refused (P-14 has no candidate). Cancelling such a sale is always the literal mirror (rule 33) whatever the tenant option, and only before the owner has been paid (`CONSIGNOR_ALREADY_PAID`); see Q-41 | ACCOUNTING rule 16, P-14 |
| D-95 | **Phase 6.** A sale by an external showroom is a `sales` row with channel EXTERNAL_SHOWROOM (D-35): the buyer is optional (name in the notes), no invoice is issued by us, rule 18 posts three entries (the commission entry is skipped when the commission is zero) and the car goes SOLD → DELIVERED at once, so the sale is final (Q-30 default). Collections (rule 19) are against the showroom's balance, never more than it owes | SPEC §4.5, rule 18 |
| D-96 | **Phase 6.** Settlements with an owner: a payout only after the sale and never more than is owed for that car; a recovery never more than the owner owes for expenses. All balances (2200, 1430, 1420) are read from the ledger, and the consignor and showroom statements list every ledger line of that subledger with a running balance, so they reconcile with the ledger by construction. Profit of a consigned car = commission (4200) − showroom-borne expenses (6280); an externally sold car's profit is after the external commission (Q-34 default) | D-26, Q-34 |
| D-97 | **Phase 6.** Matching (BACKLOG 6.6) runs in the database whenever a car becomes AVAILABLE, and when a request is created or edited: open requests (new, contacted, car found, negotiating) whose make equals the car's (ignoring case and spaces), whose model is contained in the car's model, whose year range contains the car's year and whose budget ceiling is at least the asking price (an unknown asking price matches). Colour and the minimum budget are preferences, not filters. Members with `request.manage` get one notification per new set of matches | SPEC §4.6 |
| D-98 | **Phase 6.** Follow-ups are an append-only log. The quick call log is two taps: open, then the result (saved at once); “no answer”, “call back” and “interested” default the next follow-up to tomorrow. The due list shows customers whose **latest** follow-up asks for contact today or earlier. An unassigned follow-up belongs to whoever logged it. Logging a call on a new request marks it contacted; marking a match contacted moves the request to “car found” | BACKLOG 6.4 (≤ 3 taps) |
| D-99 | **Phase 6.** The printed consignment agreement records the showroom, the owner, the car and the agreed terms with signature lines, and no legal clauses (like D-80; the showroom's own terms are Q-40) | R-07 |
| D-100 | **Phase 7.** Closing a period (rule 23) moves every income and expense balance of the range, per account and subledger, into 3300 in one closing entry dated the last day; then (PER_CAR) the profit already allocated per car is netted (Dr 3300 / Cr 3310), and rule 22 credits the partners with the rest. A period may end today at the latest. The preview runs the same plan as posting, so it shows exactly what is posted. With SUB_PERIOD_PROFIT, a loss carried in belongs to the first stretch of the range | D-40, D-29 |
| D-101 | **Phase 7.** Distributed ranges never overlap and leave no gap: a new one starts the day after the last (or at the first income/expense entry). Once distributed, nothing but closing entries may be dated inside the range (database rule, `PERIOD_DISTRIBUTED`); reversing the distribution opens it again | A period cannot be distributed twice (BACKLOG 7.1) |
| D-102 | **Phase 7.** Only the latest distribution can be reversed; its entries are mirrored on their own date, so the range is exactly as before the close | Rule 24 |
| D-103 | **Phase 7.** PER_CAR (P-10): when a sale posts, its gross profit is allocated at once by the shares on the sale date — owned car: price − cost (− external commission); consigned car: the commission. A cancelled sale reverses its allocation. Expenses after the sale (P-04) and showroom-borne consignment expenses are settled at the period close | D-40 |
| D-104 | **Phase 7.** Every report is one generic table (JSON, PDF, Excel from the same numbers) with its own permission: P&L, balance check and expenses need `report.financial`; trial balance and ledger `journal.view`; vehicle profit and aging `vehicle.view_cost`. The P&L's cost of sales is the 5xxx accounts; other expenses are listed below gross profit. The balance check adds profit not yet closed and flags a 3900 balance (Q-16) | SPEC §4.12 |
| D-105 | **Phase 7.** Needs Attention rules (SPEC §4.17): overdue installments per plan, due within `dashboard_due_hours`, bounced cheques; cars older than the 2nd aging threshold (danger past the 3rd); licences expiring within `license_expiry_days` (default 30); missing expected costs; asking price − cost below `min_profit`; uncontacted matches; follow-ups due; open requests idle for `lead_idle_days`; owners owed for sold consigned cars; suppliers owed; cash below zero; partner current account below zero (Q-17). Each rule runs only with its permission, at most 20 alerts per rule; the daily worker also sends them to the notification centre once per alert and level | Deterministic, permission-filtered |
| D-106 | **Phase 7.** The MVP acceptance demo E2E starts from the seeded showroom and its three partners; creating a showroom from the UI is the onboarding wizard of Phase 8, which will extend the test | SPEC §13 |
| D-107 | **Phase 8.** Open installments imported at go-live become plans without a sale: they carry the sheet's contract reference (or `افتتاحي-NNN`) and vehicle text, with a MANUAL schedule of what is still due; everything else (receipts, papers, reminders, reports) works as for a sold car | SPEC §4.13 |
| D-108 | **Phase 8.** An imported car enters stock AVAILABLE with an OPENING purchase record (no seller unless something is still owed to one), so its purchase cannot be recorded twice. Its cost is the purchase price plus every mapped expense column, each its own line with the column header as memo (the cost breakdown) | BACKLOG 8.4 |
| D-109 | **Phase 8.** The file is read on the server (xlsx or csv, uploaded as base64 JSON, ≤ 5,000 rows per sheet). The header row is the one with most recognised headers (titles above the table are skipped); kind and mapping are suggested from Arabic/English synonyms; a confirmed or committed mapping is remembered per tenant and header layout | BACKLOG 8.1, 8.2 |
| D-110 | **Phase 8.** All sheets of an import — and the onboarding wizard's partners and cash/bank openings — commit together in one transaction with ONE opening entry (rule 25) dated at go-live, balanced by 3900. Nothing is saved while any row has an error; a committed import never changes. Partners can be imported only while none have shares | SPEC §4.13 #5 |
| D-111 | **Phase 8.** Number and date parsing: Arabic-Indic digits and separators, currency words and symbols, thousands/decimal comma or dot (the later separator is the decimal one), parentheses or a trailing minus for negatives; dates as ISO, d/m/y (/ - .), y/m/d, two-digit years (20xx) and Excel serials. More than two decimals is an error, never rounded | A-07 |
| D-112 | **Phase 8.** Opening balance equity is cleared by the partners' agreement (P-08): the owner allocates it to each partner's capital or current account (suggested by ownership %, editable); never more than the balance | Q-16, P-08 |
| D-113 | **Phase 9.** A suspended subscription or a non-active tenant is read-only in the database too: one trigger on every tenant business table refuses writes (SR040 → `423 TENANT_READ_ONLY`). Exempt, so suspension, billing, logins and the log keep working: tenants, subscriptions, feature_flags, memberships, audit_log, notifications, reminder_jobs, idempotency_keys, tenant_counters. Nothing is ever deleted | SPEC §4.16, 9.2 |
| D-114 | **Phase 9.** Plan limits count active members, unarchived branches and cars in stock (DRAFT, IN_PREPARATION, AVAILABLE, RESERVED, AT_OTHER_SHOWROOM). Reaching one refuses only the new thing (`403 PLAN_LIMIT_REACHED`); what exists is never touched. A trade-in taken in a sale is not refused (the sale must not fail on it); reactivating a member counts | 9.1 |
| D-115 | **Phase 9.** No summary tables (D-12 stands): with indexes on the hot paths, every measured endpoint is under 2 s p95 on 5,000 cars / 100,000 lines (worst: the dashboard, PERFORMANCE.md) | D-12, 9.7 |
| D-116 | **Phase 9.** Manual billing: the platform admin issues an invoice per period and marks it paid when the money arrives outside the app; paying makes the subscription ACTIVE until the period's end. Status changes (PAST_DUE, SUSPENDED) are manual with a reason; nothing is suspended automatically yet. A `PaymentGateway` interface (`services/billing.py`, manual implementation) is where a card/wallet provider plugs in later. Prices are not set in the app (OPEN: commercial decision) | SPEC §4.16, 9.3 |
| D-117 | **Phase 9.** Support access is granted by the showroom (owner/admin) for 1–72 hours with a reason and can be revoked. Inside the window the platform sees a read-only **summary** (counts, cars by status), not records; without one it sees nothing (`SUPPORT_NOT_GRANTED`). Every look is written to the showroom's own audit log as a PLATFORM action | SPEC §4.16, 9.4 |
| D-118 | **Phase 9.** Self-serve signup: an account first (email + password, no confirmation locally; confirmation on in the hosted project), then a showroom (Egypt or Qatar) on a 30-day trial with the user as owner. One person may own at most three showrooms (`SIGNUP_LIMIT`); more by request | SPEC §4.16, 9.3 |
| D-119 | **Phase 9.** Two-step sign-in (TOTP) is optional for every role (Q-37 default) but enforced once enrolled: the API refuses a password-only session (`401 MFA_REQUIRED`). Password policy ≥10 characters with upper/lower case and digits. Per-IP rate limits and a 10 MB body limit in the API; security headers on every response (SECURITY.md) | 9.8, Q-37 |
| D-120 | **Phase 9.** PWA: installable; offline the app opens and shows the last loaded pages read-only (API reads cached per user session and tenant, never `/me` or files); writes are refused offline, never queued, so nothing is posted twice or out of order. Sign-out clears the cache. The service worker runs in production builds only | SPEC §8, 9.6 |
| D-121 | **Phase 9.** Country wording is data: `country_packs.terminology` maps translation keys to the country's Arabic (e.g. Qatar: السيارة where Egypt says العربية), applied over `ar` when a showroom of that country opens (Q-25) | Q-25, 9.10 |
| D-122 | **Phase 9.** Backups: the platform's managed backups (PITR) plus a nightly logical dump kept 30 days, and a per-showroom JSON export every night (kept `EXPORT_KEEP_DAYS`, default 14) and on demand by the owner. The export is JSON in a zip (one file per table); an Excel export of the same is not built (the reports already export to Excel). Restore drill rehearsed (RUNBOOK §3) | 9.9 |
| D-123 | **Pilot review.** A drawing or capital withdrawal larger than the partner's **net balance** (capital + current − loans to the partner + loans from the partner) is refused (`WITHDRAWAL_EXCEEDS_BALANCE`). Within the net balance, drawing ahead of profits still posts with the `DRAWING_EXCEEDS_BALANCE` warning, so partners can draw before a distribution. Replaces the warn-only part of D-63 | Accountant review item 2 |
| D-124 | **Pilot review.** P-12 revised: a discount on an owned car is its own line, Dr **4150 Sales discounts** (contra-income, vehicle subledger) with Cr 4100 at the list price. Car profit and the P&L use 4100 + 4150, so profit is unchanged. Consigned cars post no discount line. Cancellations mirror the discount line actually posted, so older sales (net only) cancel as before | Accountant review item 7 |
| D-125 | **Pilot review.** Cancelling the sale of a consigned car needs the new permission `sale.cancel_consigned`, held by the owner and the manager; an accountant (who has `sale.cancel`) cannot. Ordinary sales are unchanged | Accountant review item 17, Q-41 |
| D-126 | **Pilot review.** Request matching compares makes through a catalogue of Arabic and English names (`private.make_aliases`, about 45 makes common in Egypt and Qatar) after folding case, spaces, hyphens and Arabic letter variants (أ/إ/آ/ا, ى/ي, ة/ه). A make outside the catalogue matches its own spelling. Open requests were re-matched when this shipped | Accountant review item 19, Q-42 |
| D-127 | **Pilot review.** One direct expense can be split over several cars (`POST /vehicle-expenses/split`): each car's part is an ordinary vehicle expense with its own entry and treatment (cost, P-04 cost of sales, or consignment terms), the parts share a `split_group_id`, the cash check runs once on the total. The dialog offers an equal split, editable per car. Indirect expenses stay general expenses and are never charged to cars | Accountant follow-up item 5 |
| D-128 | **Pilot review.** D-76 revised: a sale whose trade-in car has had expenses can be cancelled. The car goes back to the customer and a second entry charges what was spent on it (its inventory beyond the agreed value): Dr customer credits up to what the customer is owed (REFUND_LIABILITY), the rest Dr other receivables (always so under MIRROR, which refunds the money as it came) / Cr vehicle inventory. A trade-in car already sold or reserved still blocks the cancellation (open) | Accountant follow-up item 11 |
| D-129 | **Pilot review.** D-90 revised: monthly and quarterly schedules use a 30-day month, as for payroll: the first date stays as chosen, later dates keep its day capped at 30 and at the month's last day (31 Jan → 28 Feb → 30 Mar) | Accountant follow-up item 14 |
| D-130 | **Pilot answer, Q-03.** Installment markup (mode b) is set on each sale (`installments.markup`, an amount; the sale screen also turns a percentage of what is financed into the amount) and recognised **at once**: Dr 1400 receivable (rest + markup) / Cr 4100 cash price / Cr 4300 installment financing income (buyer). No deferral to 2400, so collections stay as rule 15 mode a. Allowed only when the tenant setting `installment_markup_mode` is `B_ENABLED` (Settings → Policies; `MARKUP_DISABLED` otherwise). A cancellation to customer credit takes the markup income back out (Dr 4300). Car profit stays price − cost; the markup is showroom income, settled at the period close under PER_CAR | Pilot owner |
| D-131 | **Pilot answer.** Power of attorney (توكيل) is a document type; the car file offers it with the purchase and sale contracts and the ID copy. All remain normal-sensitivity documents except the purchase contract and seller receipt (cost data, G-09) | Pilot owner |

---

## Part 7: Open questions

**Spec §14 questions** (Q-01 to Q-08) are first, followed by the questions raised in Phase 0. "Default" = the behaviour until answered.

| ID | Question | Default until answered | Blocks |
|---|---|---|---|
| Q-01 | Is partnership showroom-level only, or also per car with different investors? | Showroom-level UI; `vehicle_investors` table behind a flag | Phase 10 |
| Q-02 | Is profit distributed per car on sale or periodically? Monthly, quarterly or yearly? | **Answered 2026-10-02: tenant option** (D-40). Default if left unset: PERIODIC, owner-triggered, any date range | 7.1, 7.2 |
| Q-03 | Do installment sales include a markup, and how is it recognized over time (proportional per installment? straight-line? other)? | Mode (a); mode (b) disabled until the method is confirmed | 5.3 |
| Q-04 | When a partner "borrows against his share", is it a loan to be repaid (rules 4/5) or a drawing (rule 3)? Does "سحب من الحصة" mean from capital or from profits? | Both offered; the user picks per transaction | 3.2 |
| Q-05 | Who records and who approves? | **Answered 2026-10-02: ARCHITECTURE §7 matrix approved as written.** Cells marked Q-05 take the restrictive default: Manager does **not** see minimum price; Viewer does **not** see cost or financial dashboards/reports; sales staff **cannot** take deposits and see the due list read-only; Accountant **cannot** lock periods (Owner only); Manager posts sales only if the Owner enables it | 1.3 |
| Q-06 | Which Egypt ETA e-invoice / e-receipt obligations apply to used-car showrooms? | **Answered 2026-10-02: no tax rules in the product** (D-39). The ETA adapter interface stays as a stub with no submissions | Phase 10 |
| Q-07 | Arabic-Indic (١٢٣) or Western (123) digits? | Tenant setting; default **Western** | — |
| Q-08 | How common are trade-ins and post-dated cheques in Egypt vs Qatar? | Both built (4.11, 5.5) | Priority only |
| Q-09 | Ownership precision: is 33.3334 / 33.3333 / 33.3333 acceptable for thirds? (C-03) | Yes | 3.1 |
| Q-10 | Per-car distribution mechanics (C-04) and loss allocation (G-07) | **Answered 2026-10-02: tenant options** (D-40) | 7.2 |
| Q-11 | Does VAT or any tax apply to used-car sales, the margin, or consignment commission in Egypt? | **Answered 2026-10-02: no tax rules.** No tax lines on sales, commissions or invoices; account 2500 is seeded but unused; the CountryPack tax profile stays empty (D-39) | — |
| Q-12 | Sale cancellation accounting (C-06): literal mirror (rule 33) or reversal against a refund liability (P-03)? | **Answered 2026-10-02: tenant option** (D-41) | 4.13 |
| Q-13 | Customer credit for overpayments: allowed? Which account? How is it refunded? | **Answered 2026-10-02: tenant option** (D-41) | 5.4 |
| Q-14 | Expenses on a car already sold: COGS (P-04) or not allowed? | Not allowed (error) | 4.7 |
| Q-15 | Consignment-in: account for showroom-borne expenses; shared split %; sale below the net price; installment sale of a consigned car; rules 30/31 for consigned cars (C-11) | **Partly answered by P-05/P-06 (Q-26):** showroom-borne → 6280, shared split = the owner's % in the agreement (D-93); still default: sales at or below the net are blocked, cash/bank sales only (P-14), rules 30/31 debit 1430 (C-11) | 6.2 |
| Q-16 | How is Opening Balance Equity (3900) cleared after import? | Left on 3900 and shown on the balance check | 8.4 |
| Q-17 | Definition of partner "net balance" and the "drawings exceed balance" alert | capital + current − loans to partner + loans from partner; alert when the current account goes negative | 3.4, 7.5 |
| Q-18 | Pro-rata method when % changes mid-period, and who receives the rounding remainder | **Answered 2026-10-02: tenant options** (D-40) | 7.1 |
| Q-19 | Does a capital contribution or withdrawal change ownership %? | No; % changes are explicit | 3.1 |
| Q-20 | Cheques: confirm "collected" timing (A-10); bank charges on a bounce, recharged to the customer? | No charge recording | 5.5 |
| Q-21 | Where may data be hosted (Supabase region; Egypt PDPL constraints)? | **Partly answered 2026-10-02:** Supabase Cloud Frankfurt for development and the pilot, with **no real personal data**. Final production hosting is pending Egyptian counsel (see the answer log) | First real tenant data |
| Q-22 | Discount: shown as a separate line or the net price only? | Net price in the ledger, discount on the document | 4.10 |
| Q-23 | Late fees, repossession, bad debt: needed in the MVP? | No | — |
| Q-24 | Days-in-stock start: purchase date, yard arrival, or agreement date (consigned)? | Purchase date / agreement date | 4.8 |
| Q-25 | Separate Arabic terminology for Qatar (السيارة vs العربية, etc.)? | `ar-EG` default + `ar-QA` overrides | 1.7 |
| Q-26 | Approve the candidate rules P-01 to P-15 (ACCOUNTING §5), ideally reviewed by the showroom's accountant | Not implemented | various |
| Q-27 | Close periods monthly or only when distributing? | Follows the distribution frequency option (D-40): closing entries are posted by each distribution run and at year end | 7.1 |
| Q-28 | Hosting provider for the FastAPI and worker containers | Not decided | 1.x deploy |
| Q-29 | Invite users by phone (SMS cost and provider)? | Email only | 1.9 |
| Q-30 | Can a DELIVERED sale be cancelled? What happens to a trade-in car already sold? | No / cancellation blocked | 4.13 |
| Q-31 | Do partners see the overall showroom summary by default? | No (setting off) | 3.5 |
| Q-32 | Dashboard due window: 48 h or 7 days (C-09)? | Both, as described in C-09 | 7.6 |
| Q-33 | Can a consigned-in car be re-consigned to another showroom? | No | 6.3 |
| Q-34 | Is the profit of an externally sold car shown before or after the external commission? | After commission | 6.3 |
| Q-35 | Can we get a real (anonymised) Excel sheet from the pilot showroom? | We build a synthetic messy fixture | 8.x |
| Q-36 | Would you accept a pilot release after Phase 4 (R-02)? | Phase order as specified | Planning |
| Q-37 | Make 2FA mandatory for Owner and Accountant? | Optional (FACT) | 9.8 |
| Q-39 | **Phase 4.** May a deposit be partly refunded and partly forfeited? | No: whole refund or whole forfeit (D-72) | — |
| Q-40 | **Phase 4.** Which contract terms (if any) should the printed sale contract carry? They must come from the showroom or its lawyer | None; parties, car, price, payments, signatures (D-80) | — |
| Q-41 | **Phase 6.** Cancelling the sale of a consigned car without refunding the buyer at once (a REFUND_LIABILITY variant with 2200 instead of 4100) | Only the literal mirror, and only before the owner is paid (D-94) | — |
| Q-42 | **Phase 6.** Should matching treat Arabic and English make names as the same (هيونداي = Hyundai), e.g. through a make catalogue? | Makes match only when spelled the same, ignoring case (D-97) | — |
| Q-38 | **PrimeNG licence (R-16).** Options: (a) register for the free PrimeUI Community License if the company qualifies, and buy commercial seats when it outgrows it; (b) buy commercial licences now; (c) replace PrimeNG with an MIT library such as Angular Material/CDK, a stack change only you can approve (SPEC §2 fixes PrimeNG, §0.9 forbids swapping without reason). Cost to switch is lowest now, while the UI is only the Phase 1 shell | Keep PrimeNG for development; the badge shows until a key is configured | Before any pilot |

---

## Part 8: Answer log

| Date | ID | Answer | By |
|---|---|---|---|
| 2026-10-02 | Q-21 | Frankfurt (Supabase Cloud) for development and the pilot, with **no real personal data**. Final production hosting depends on a written opinion from Egyptian data-protection counsel on: (1) whether we, as the SaaS processor, need our own PDPC licence; (2) whether EU hosting with a PDPC transfer licence and customer consent is workable, or Egyptian tenants must be hosted in Egypt. Qatar transfer rules are to be confirmed by counsel as well. Production decision required **before the first real tenant data is loaded** (D-38) | Product owner |
| 2026-10-02 | Q-05 | Role matrix (ARCHITECTURE §7) approved as written; open cells take the restrictive default | Product owner |
| 2026-10-02 | Q-06, Q-11 | No tax rules (D-39) | Product owner |
| 2026-10-02 | Q-02, Q-10, Q-18 | All distribution choices are tenant options with defaults (D-40) | Product owner |
| 2026-10-02 | Q-12, Q-13 | Cancellation method and overpayment handling are tenant options with defaults (D-41) | Product owner |
| 2026-10-02 | Phase 0 | Design approved; **Phase 1 started** | Product owner |
| 2026-10-02 | Phase 1 | Foundation delivered (see BACKLOG Phase 1 status); awaiting product-owner acceptance | Claude |
| 2026-10-02 | Phase 1 | **Accepted.** Q-38 (PrimeNG licence) remains open and must be decided before any pilot | Product owner |
| 2026-10-02 | Phase 2 | Ledger core delivered (see BACKLOG Phase 2 status); awaiting product-owner acceptance. P-01 other income still awaits approval (Q-26) | Claude |
| 2026-10-02 | Phase 2 | **Accepted** | Product owner |
| 2026-10-02 | Q-38 | **Keep PrimeNG** under the PrimeUI licence. The product owner obtains the licence key; the app reads it from configuration and never commits it (D-61) | Product owner |
| 2026-10-02 | Q-26 | **Candidate posting rules approved** (ACCOUNTING §5) where a candidate exists: P-01 other income, P-02/P-03 (as D-41 options), P-04 expense on a sold car → COGS, P-05 showroom-borne consignment expense, P-06 consignor reimbursement, P-07 bounced-cheque bank charges, P-08 opening-balance-equity clearing by agreement, P-09/P-10 (as D-40 options), P-12 discount at net price. Unchanged: P-11 (no tax, D-39), P-13 (out of MVP), P-14 and P-15 (no candidate; still open). Each is implemented with its phase | Product owner |
| 2026-10-02 | Phase 3 | Started | Product owner |
| 2026-10-02 | Phase 3 | Partners delivered (see BACKLOG Phase 3 status); awaiting product-owner acceptance. New decisions D-61 to D-67 need approval | Claude |
| 2026-10-02 | Phase 3 | **Accepted.** Standing instruction: commit and push each phase, then continue with the next until Phase 9 is finished | Product owner |
| 2026-10-03 | Phase 4 | Vehicles and sales delivered (see BACKLOG Phase 4 status); committed and pushed per the standing instruction; continuing with Phase 5. New decisions D-68 to D-81 and questions Q-39, Q-40 need review | Claude |
| 2026-10-03 | Phase 5 | Installments delivered (see BACKLOG Phase 5 status); committed and pushed per the standing instruction; continuing with Phase 6. New decisions D-82 to D-90 need review; mode (b) still waits for Q-03 | Claude |
| 2026-10-03 | Phase 6 | Consignment and customer requests delivered (see BACKLOG Phase 6 status); committed and pushed per the standing instruction; continuing with Phase 7. New decisions D-91 to D-99 and questions Q-41, Q-42 need review | Claude |
| 2026-10-03 | Phase 7 | Profit distribution, reports and dashboard delivered (see BACKLOG Phase 7 status); the full scenario of ACCOUNTING §4 matches exactly; committed and pushed per the standing instruction; continuing with Phase 8. New decisions D-100 to D-106 need review | Claude |
| 2026-10-03 | Phase 8 | Excel import and onboarding delivered (see BACKLOG Phase 8 status); committed and pushed per the standing instruction; continuing with Phase 9. New decisions D-107 to D-112 need review; Q-35 (a real anonymised sheet) is still wanted to replace the synthetic fixture | Claude |
| 2026-10-03 | Phase 9 | SaaS layer and hardening delivered (see BACKLOG Phase 9 status); committed and pushed per the standing instruction. All nine phases are delivered. New decisions D-113 to D-122 need review; open: Q-37 (mandatory 2FA), Q-21 (hosting), prices (D-116) | Claude |
| 2026-10-03 | Q-37 | Two-step sign-in stays **optional** for every role (enforced once a user enrols, D-119) | Product owner |
| 2026-10-03 | Q-21 | Frankfurt (Supabase Cloud) confirmed for testing before production, still with no real personal data; the production decision stays with Egyptian counsel | Product owner |
| 2026-10-03 | D-116 | Plan prices deferred; billing stays manual | Product owner |
| 2026-10-03 | CI | GitHub Actions enabled on githubsud/carshowroom | Product owner |
| 2026-10-03 | Review | **Accountant review (Mohamed El-Hout, for the pilot showroom).** Approved as built: D-62, D-64, D-67, D-71 (see below), D-73, P-04, D-79, D-83, D-89, D-93, D-96, D-95, D-101/D-102, D-103, D-110/D-112. Comments on D-64: a mistaken share can be handled by a temporary extra partner record until the new year (follow-up asked). On D-112: opening balances come from the last balance sheet, so 3900 should normally be zero | Accountant (pilot) |
| 2026-10-03 | D-63 | **Changed:** a drawing above the partner's balance is **refused** with a warning, not posted with a warning | Accountant (pilot) |
| 2026-10-03 | D-71 | Approved, plus a **new requirement**: operating expenses are allocated to the cars they relate to, and administrative expenses spread over all cars by a ratio (method to confirm) | Accountant (pilot) |
| 2026-10-03 | P-12 / D-73 | **Changed:** a discount must appear as its own line in the accounts (reviewable at any time), not only on the invoice | Accountant (pilot) |
| 2026-10-03 | D-78 | **Changed:** the accountant records; the owner or the manager approves (posts) transactions | Accountant (pilot) |
| 2026-10-03 | D-76 | Not clear to the reviewer; clarification sent | Accountant (pilot) |
| 2026-10-03 | D-90 | **Changed:** months count as 30 days, like payroll: a schedule starting on the 31st falls on the 30th after (February to confirm) | Accountant (pilot) |
| 2026-10-03 | Q-41 / D-94 | **Changed:** cancelling the sale of a consigned car is a manager-only permission | Accountant (pilot) |
| 2026-10-03 | Q-42 / D-97 | **Approved:** Arabic and English make names match (هيونداي = Hyundai) | Accountant (pilot) |
| 2026-10-03 | D-100 | No answer yet | Accountant (pilot) |
| 2026-10-03 | Review | Items 2, 7, 17 and 19 implemented (D-123 to D-126). Waiting on follow-ups for items 3, 5, 9, 11, 14 and 20 | Claude |
| 2026-10-03 | D-76 | **Changed (follow-up):** a sale with a trade-in may be cancelled even when the trade-in car has had expenses: the car goes back to the customer and those expenses are deducted from what the customer is refunded. The case of a trade-in car already sold or reserved is still open | Accountant (pilot) |
| 2026-10-03 | D-64 | Follow-up: a mistaken share is corrected through a temporary partner record holding the difference, merged into the partner's own account at the start of the next year; a share increase during the year earns per car, not by percentage, until it is merged at the start of the year. To discuss: the app already weights mid-year share changes by days (D-64, Q-18) | Accountant (pilot) |
| 2026-10-03 | D-71 | Follow-up, replaces the earlier comment: expenses are direct (tied to a car: charged to that car, or split over several cars) or indirect (the showroom in general, e.g. cleaning the office: never charged to cars). No allocation of administrative expenses to cars | Accountant (pilot) |
| 2026-10-03 | D-78 | Follow-up: the approval step applies to **all** transactions (no amount threshold) | Accountant (pilot) |
| 2026-10-03 | D-90 | Follow-up: confirmed; February falls on its last day (28, or 29 in a leap year) | Accountant (pilot) |
| 2026-10-03 | D-100 | **Approved**; profit is distributed on net profit (after expenses), not gross profit | Accountant (pilot) |
| 2026-10-03 | Review | Follow-up items 5, 11 and 14 implemented (D-127 to D-129). Open: item 9 (approval workflow), item 3 (to discuss), and the sold-trade-in case of item 11 | Claude |
| 2026-10-03 | Q-35 | **Pilot owner (Sharqia, Egypt):** will fill in our Excel template; the Arabic template was sent | Pilot owner |
| 2026-10-03 | Q-03 | **Answered:** installment sales carry a markup the owner sets per sale (it depends on the term: 3, 6 or 12 months); the whole profit, markup included, is recognised on the sale date. Mode (b) can be unlocked with immediate recognition (no deferral) | Pilot owner |
| 2026-10-03 | Q-23 | **Answered:** no late fees. A repossessed car would be put back to its original state, but in practice it does not happen | Pilot owner |
| 2026-10-03 | Q-08 | **Answered:** post-dated cheques and trade-ins both happen often | Pilot owner |
| 2026-10-03 | Q-20 | **Answered:** bank charges on a bounced cheque are borne by the showroom (the existing default: an expense, not recharged) | Pilot owner |
| 2026-10-03 | Q-39 | **Answered:** when a buyer backs out, the deposit is refunded in full (refund stays the usual action; forfeit remains available) | Pilot owner |
| 2026-10-03 | Q-01 | **Answered:** a trader may put money into one specific car and take its profit only. Car-level investors are needed (not built yet); terms to confirm | Pilot owner |
| 2026-10-03 | Q-04 | Answer unclear ("no partners ... there is financing"); to confirm whether the showroom has partners at all | Pilot owner |
| 2026-10-03 | Q-15 | **Answered:** consigned cars are taken at a net price agreed with the owner; the rest is the showroom's profit, and the car's expenses come off that profit (net-price terms, expenses borne by the showroom: both already supported) | Pilot owner |
| 2026-10-03 | Documents | Every purchase and sale keeps a copy of the power of attorney or contract, the ID card and the other party's details (power of attorney is not a document type yet) | Pilot owner |
| 2026-10-03 | Q-29 | **Answered:** two users, the owner and a salesperson; the salesperson works from a mobile phone | Pilot owner |
| 2026-10-03 | Q-40, prices | No answer yet | Pilot owner |
| 2026-10-03 | Q-35 | Mohamed El-Hout will send the showroom's real working sheet with personal data removed | Product owner |
| 2026-10-03 | Review | Installment markup and the power-of-attorney document type implemented (D-130, D-131). Waiting on the owner for car-level investor terms, partners, markup input, contract copy | Claude |
