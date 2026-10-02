# FRONTEND: Angular Module Plan

> Phase 0 design. Labels: **FACT** / **ASSUMPTION** / **DECISION** / **OPEN QUESTION** ([DECISIONS.md](DECISIONS.md)).

---

## 1. Foundations

| Topic | Choice | Label |
|---|---|---|
| Framework | Angular latest stable; standalone components, signals, strict TypeScript, Reactive Forms, lazy-loaded feature routes | FACT |
| UI kit | PrimeNG with a custom theme preset (primary `#0f172a`). Tailwind is optional, for layout utilities only, through the PrimeNG integration. No second component library | FACT |
| State | Signals plus feature-scoped services (`signal`, `computed`, `resource`/`rxResource` for API reads). **No NgRx** | FACT / DECISION |
| i18n | Transloco, runtime switching; `ar` (default, RTL) and `en` (LTR); scopes lazy-loaded per feature; locale variants `ar-EG`/`ar-QA` for terminology (Q-25) | DECISION D-02 |
| Direction | The `dir` and `lang` attributes on `<html>` are set from the active language. Only CSS logical properties are used (`margin-inline-start`, `inset-inline-end`). A lint rule (stylelint) blocks `left`/`right`/`margin-left` | FACT / DECISION |
| Fonts | IBM Plex Sans Arabic (UI) with Latin fallback; Cairo for headings. Self-hosted so the PWA works offline | DECISION (FACT allows Cairo / Plex / Tajawal) |
| Formatting | One `FormatService` (currency, numbers, dates, digit style `ARABIC_INDIC`/`WESTERN` from tenant settings) with pipes `money`, `num`, `date`, `pct` | FACT |
| Money | Money values are strings end to end. Display-only previews use a small decimal helper (`decimal.js-light` or `big.js`); no `number` arithmetic on money | FACT / DECISION |
| API | Typed client generated from OpenAPI (`openapi-typescript` + a thin fetch wrapper, or `ng-openapi-gen`) in `core/api/generated`. A CI check fails if it drifts from the API | FACT / DECISION |
| Supabase | `@supabase/supabase-js` for auth and permitted reads/CRUD; a single `SupabaseService`. The service-role key never exists in the web app | FACT |
| PWA | `@angular/pwa`; app shell, icons, offline **read-only** cache of the dashboard and last-viewed lists (data groups, `freshness` strategy, max age 24 h). An offline banner disables every write button | FACT |

---

## 2. Folder structure

```text
apps/web/src/app/
  core/
    auth/            auth.service.ts (Supabase session, refresh), auth.guard.ts
    tenant/          tenant-context.service.ts (active tenant signal, memberships, permissions, flags)
    permissions/     permission.guard.ts, has-permission.directive.ts (*appCan="'vehicle.view_cost'")
    http/            api.interceptor.ts (JWT + X-Tenant-Id + Idempotency-Key), error.interceptor.ts (code → i18n toast)
    api/             generated/ (OpenAPI client), api.config.ts
    supabase/        supabase.service.ts, typed table helpers
    i18n/            transloco loader, language.service.ts (dir switching)
    format/          format.service.ts, pipes
    offline/         network-status.service.ts, offline-banner
    layout/          shell (top bar, side menu, bottom nav on mobile), menu.config.ts
  shared/
    components/      (see §5)
    dialogs/         confirm-post, reverse-entry, reason
    pipes/ directives/ validators/ (money, vin, phone, percent-sum)
    models/          view models not covered by the generated client
  features/
    auth/            login, forgot-password, reset-password, tenant-switcher
    onboarding/
    dashboard/
    vehicles/
    consignments/
    customers/
    requests/
    sales/
    installments/
    partners/
    finance/         cash & bank, transfers, general expenses, other income, suppliers, periods, journal
    distribution/
    reports/
    imports/
    settings/
    audit/
  admin/             super admin console (separate lazy route tree, separate guard)
```

**DECISION.** Each feature has `<feature>.routes.ts`, `data/` (API and Supabase services), `pages/` (routed), and `components/` (feature-local). Features do not import each other; anything shared moves to `shared/`.

---

## 3. Routes

All tenant routes live under `/t/:tenantId/…`, so links include the tenant and a deep link opens the right tenant (DECISION D-32). Guards: `authGuard`, `tenantGuard` (the membership is active, and it sets the context), `can('perm')`, `flag('feature')`, `writableGuard` (blocks write pages when the tenant is suspended or the device is offline).

| Path | Page | Guard (permission / flag) | Phase |
|---|---|---|---|
| `/login`, `/forgot-password`, `/reset-password` | Auth | public | 1 |
| `/tenants` | Tenant switcher (auto-skipped with one membership) | auth | 1 |
| `/t/:tid/onboarding` | Onboarding wizard | `tenant.settings.manage` | 8 |
| `/t/:tid/dashboard` | Owner, partner or staff dashboard (chosen by permission) | `dashboard.view` or `partner.view_own` | 1 (shell), 7 |
| `/t/:tid/vehicles` | Inventory list | `vehicle.view` | 4 |
| `/t/:tid/vehicles/new` | Add/purchase wizard | `vehicle.manage` (+`vehicle.purchase` for the purchase step) | 4 |
| `/t/:tid/vehicles/:id` | Vehicle file (tabs: details, costs*, media & documents, history, sale) | `vehicle.view`; *costs: `vehicle.view_cost` | 4 |
| `/t/:tid/consignments/in`, `/in/new`, `/in/:id` | Consignment IN list, agreement, statement | `consignment.manage`, flag `consignment` | 6 |
| `/t/:tid/consignments/out`, `/out/:id` | Consignment OUT / external showroom statement | same | 6 |
| `/t/:tid/customers`, `/customers/:id` | List, profile (purchases, sales, installments, requests, calls) | `customer.view` | 4 |
| `/t/:tid/requests`, `/requests/:id` | Wanted list, matches | `request.manage` | 6 |
| `/t/:tid/sales`, `/sales/new`, `/sales/:id` | List, new sale wizard, sale document | `sale.view` / `sale.draft` | 4 |
| `/t/:tid/installments` | Due/overdue board | `installment.view`, flag `installments` | 5 |
| `/t/:tid/installments/calendar` | Installment radar | same | 5 |
| `/t/:tid/installments/papers` | Deferred papers register | `deferred_paper.manage` | 5 |
| `/t/:tid/partners`, `/partners/:id`, `/partners/summary` | List, statement, summary | `partner.view_all` (own statement: `partner.view_own`) | 3 |
| `/t/:tid/finance/cash` | Balances, cash/bank book | `cash.view` | 2 |
| `/t/:tid/finance/expenses`, `/finance/other-income`, `/finance/transfers` | General expenses, other income, transfers | `cash.transact` | 2 |
| `/t/:tid/finance/suppliers`, `/:id` | Suppliers and statements | `supplier.manage` | 4 |
| `/t/:tid/finance/journal`, `/finance/periods` | Journal (accountant view), period locks | `journal.view` / `period.lock` | 2 |
| `/t/:tid/distribution` | Preview and post | `profit.distribute` | 7 |
| `/t/:tid/reports`, `/reports/:report` | Reports centre | per report | 7 |
| `/t/:tid/imports`, `/imports/:id` | Excel import wizard | `import.run` | 8 |
| `/t/:tid/settings/...` | profile, branches, cash-accounts, categories, users, tax, profit-policy, periods | `tenant.settings.manage` / `users.manage` | 1–9 |
| `/t/:tid/audit` | Audit log | `audit.view` | 9 |
| `/t/:tid/notifications` | Notification centre | member | 7 |
| `/admin/...` | Super admin (tenants, plans, billing, support sessions) | platform admin | 9 |

**FACT.** Menu items are hidden by permission and feature flag. On mobile, a bottom nav holds Dashboard, Cars, + (quick actions), Due, More.

---

## 4. Screens (key behaviour)

| # | Screen | Essentials |
|---|---|---|
| 1 | Login / tenant switcher | Email or phone + password, language toggle on the login page, remember the last tenant |
| 2 | Onboarding wizard | Profile → partners & opening capital (shares must total 100%) → cash/bank opening balances → import vehicles → done. A preview of the opening entry is shown in plain language |
| 3 | Dashboard | **Needs Attention** panel first; KPI tiles (cash + bank, capital in inventory, cars > 60 days, month sales and gross profit, due in the next 7 days, overdue total); partner equity matrix with simple bars. The partner view shows own position plus the summary if enabled. The sales view shows no money tiles |
| 4 | Vehicles list | PrimeNG table (desktop) / card list (mobile), filter chips, aging colours (green < 30, amber 30–60, orange 60–90, red > 90, from settings), cost columns only with permission |
| 4 | Vehicle file | Header with stock no, status badge, days in stock, quick actions. **Cost-stacking card**: purchase + each expense = total, with the "estimate, missing: …" label when incomplete. The profit block appears after sale. The whole tab is absent for the sales role |
| 4 | Add/purchase wizard | Car details → photos (camera) → purchase (seller, price, payment legs, deferred) → preview → post |
| 4 | Quick expense dialog | **< 15 s on a phone**: car (pre-selected or search by last VIN digits), category chips, amount keypad, paid-from defaulting to the main cash box, optional photo of the receipt, a live preview of the new total cost, one confirm |
| 5 | Consignments | IN: agreement form, printable agreement, recoverable expenses, settlement, statement. OUT: send to showroom, record their sale, collections, statement |
| 6 | Customers | Phone-first search; profile tabs; **"Log call"** button: 3 taps (result chip → optional note → next follow-up date chip "tomorrow / 3 days / week") |
| 7 | Requests & matches | List by status (kanban on desktop optional, list on mobile); match alert "3 customers asked for this car" with tap-to-call and a "contacted" toggle |
| 8 | New sale wizard | Vehicle → buyer (search or quick-create) → price & discount → payment structure (cash/bank legs, deposit applied, trade-in, installments with live schedule preview, papers) → review (plain-language summary) → save draft / post (if permitted) |
| 9 | Installments | Board with tabs Today / Next 7 days / Overdue / All; the calendar "radar" is colour-coded; record payment dialog (amount defaults to the next due amount, allocation preview); papers register with status actions |
| 10 | Partners | List with %; statement (date range, opening, running balance, closing, buckets); summary; action buttons Contribution / Drawing / Loan / Repayment, each with a preview such as "سيتم خصم 50,000 ج.م من الخزنة الرئيسية وتسجيلها كسحب من حصة الشريك أحمد" |
| 11 | Cash & bank | Balance cards per account, cash book with running balance, transfer dialog, general expense dialog, other income |
| 12 | Distribution | Period picker → preview table per partner → confirm post |
| 13 | Reports centre | Cards per report; filters; JSON view + PDF/Excel download |
| 14 | Import wizard | Upload/template → mapping (drag or select; remembered) → validation preview (row errors highlighted, download error file) → commit |
| 15 | Settings | Profile, branches, cash accounts, categories, users & roles, tax/country pack, profit policy, period locks |
| 16 | Audit log | Filter by user, entity, action, date; JSON diff viewer |
| 17 | Super admin | Tenants table, usage, plan, subscription status, mark invoice paid, support session (only with a grant) |

**FACT (SPEC §9.3).** Every financial form shows a plain-language preview before posting (from the API `preview` endpoint), plus a confirmation dialog. A reversal requires a reason. "Debit/credit" appears only in `journal.view` screens.

---

## 5. Shared components

| Component | Purpose |
|---|---|
| `app-money-input` | Locale-aware numeric keypad input, string value, 2 dp, digit-style aware, no float |
| `app-money` (pipe + component) | Formatted amount with currency, optional sign colour |
| `app-date-input` | Defaults to today (tenant timezone), quick chips |
| `app-cash-account-select` | Defaults to the tenant default cash box; shows the balance if permitted |
| `app-vehicle-picker` | Search by last VIN digits, plate, make/model; masked view model |
| `app-customer-picker` | Phone-first search + quick-create |
| `app-partner-picker` | |
| `app-posting-preview` | Renders the API preview: sentences + effects list (+ Dr/Cr table for accountants) |
| `app-confirm-post-dialog` | Preview + confirm; generates and holds the Idempotency-Key for retries |
| `app-reason-dialog` | Mandatory reason (reversal, cancellation, unlock) |
| `app-status-badge` | Vehicle, sale, installment and paper statuses; consistent colours and icons |
| `app-aging-chip` | Days in stock with threshold colour |
| `app-cost-stack-card` | Purchase + expenses = total; live preview row; "estimate, missing" label |
| `app-data-table` | PrimeNG table wrapper: server pagination, sort, filter, empty/loading/error states, mobile card mode |
| `app-filter-bar` | Chips + search, synced to query params |
| `app-kpi-tile`, `app-bar-meter` | Dashboard tiles, partner matrix bars |
| `app-attention-list` | Needs Attention items with deep links |
| `app-file-upload` / `app-camera-capture` | Signed URL upload, client-side compression (WebP), progress |
| `app-empty-state`, `app-error-state`, `app-skeleton` | Explicit states (FACT §9.3) |
| `app-offline-banner` | Shown when offline; disables writes |
| `app-statement-table` | Opening / movements / running balance / closing (partner, cash, consignor, supplier, external showroom) |
| `*appCan` directive | Renders only if the permission is held |

---

## 6. Design system

**DECISION D-33.** Tokens: an 8 px spacing scale; type scale 12/14/16/20/24/32; radius 8; neutral slate palette with primary `#0f172a`; semantic colours success/warn/danger/info, each with an accessible (≥ 4.5:1) text pair. Touch targets are ≥ 44 px. Tables are dense on desktop and switch to cards under 768 px. The tone is serious financial software: no gradients and no stock car imagery.

---

## 7. Testing

- **Unit:** format service, money helpers, guards, the interceptor (headers, error mapping), permission directive, sale wizard form logic.
- **Component:** quick expense dialog, cost stack card masking.
- **Playwright E2E:** the MVP acceptance demo (SPEC §13), an RTL/LTR visual smoke test, a sales-role masking test (no cost text anywhere in the DOM or in network responses), offline banner behaviour.
