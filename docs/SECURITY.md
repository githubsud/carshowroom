# SayyaraDMS — Security review

**Audience:** the product owner and whoever deploys or audits the platform.
**Status:** Phase 9 review (BACKLOG 9.8), 2026-10-03. **No high finding is open in what ships to users**; the open items in §6 are deployment tasks or decisions.

---

## 1. What we protect

| Asset | Why it matters |
|---|---|
| Each showroom's ledger, partner shares, costs and profits | Partners settle money on these numbers; another tenant or a partner must not see what they are not entitled to |
| Customers' personal data (names, phones, national IDs) | Data-protection law (Q-21); national IDs are encrypted at rest (`NATIONAL_ID_KEY`) |
| Accounts and sessions | Whoever holds the owner's session can move money in the books |
| The service-role key, the database password, `NATIONAL_ID_KEY`, the PrimeUI licence | Server-side configuration only; never in Git or in the Angular bundle |

## 2. Threat model (STRIDE, condensed)

| Threat | Example | Controls |
|---|---|---|
| **Spoofing** | Stolen password | Password policy (≥10 chars, upper/lower/digits); optional TOTP two-step sign-in, **enforced by the API once enrolled** (`MFA_REQUIRED`, D-119); refresh-token rotation; Auth rate limits (30 sign-ins / 5 min / IP) |
| **Tampering** | Editing a posted entry; writing into another tenant | Posted entries immutable (triggers), corrections are reversals; RLS on every tenant table with composite `(tenant_id, id)` foreign keys; the API runs as `app_api` (no table owner rights); suspended tenants refused in the database itself (SR040) |
| **Repudiation** | "I never cancelled that sale" | Append-only `audit_log` with actor, actor kind (USER/PLATFORM/SYSTEM), before/after; owners read it in the audit viewer |
| **Information disclosure** | Cross-tenant read; a salesperson sees costs; support staff browse a showroom | RLS + `X-Tenant-Id` checked against memberships; cost fields masked by permission; platform admins see **counts only**, and only inside an owner-granted, time-boxed window (D-117); API errors never echo SQL; offline cache keyed by tenant and cleared on sign-out |
| **Denial of service** | Flooding signup or imports; huge uploads | Request body limit 10 MB (413); per-IP rate limits (429) — signup 5/h, invites 30/h, imports 30/h, any API 600/min; plan limits |
| **Elevation of privilege** | A partner calls an owner endpoint; a showroom user calls `/admin` | Permission checks per endpoint (role matrix, ARCHITECTURE §7) and again in RLS/security-definer functions; platform functions check `platform_admins` in the database (`private.user_is_platform_admin`) |

## 3. Controls added in Phase 9

### 3.1 HTTP hardening (`apps/api/app/core/http_guard.py`)

- **Body size:** `Content-Length` above 10 MB → `413 REQUEST_TOO_LARGE` (an import file, base64, is the largest legitimate body).
- **Rate limits** (per client IP, per API instance; the tightest matching rule wins):

  | Method | Path prefix | Limit |
  |---|---|---|
  | POST | `/api/v1/signup` | 5 per hour |
  | POST | `/api/v1/users/invite` | 30 per hour |
  | POST | `/api/v1/imports` | 30 per hour |
  | any | `/api/v1/` | 600 per minute |

  Over the limit → `429 RATE_LIMITED` with `Retry-After`. Off in tests unless `RATE_LIMITS_ENABLED=true`. With several API instances, the proxy or a shared store must enforce them as well (§6).
- **Headers on every API response:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (not on the API docs pages), and in production `Strict-Transport-Security: max-age=31536000; includeSubDomains`.

### 3.2 Accounts

- **Password policy** (Supabase Auth, `supabase/config.toml`): minimum 10 characters with lower and upper case letters and digits. Mirror these settings in the hosted project.
- **Two-step sign-in (TOTP)** — Account & security page: enroll with a QR code, confirm with a code, turn off. Optional for every role (Q-37 default), **recommended for owners and accountants** on the page. Once a user has a verified factor, the API refuses a password-only session (`aal1`) with `401 MFA_REQUIRED`, and the login page asks for the code.
- Losing the authenticator: removal by a platform operator after out-of-band verification (RUNBOOK §4).

### 3.3 Tenancy and the platform

- **Read-only tenants** (D-113): a trigger on every tenant business table refuses writes when the showroom is suspended or archived (`SR040 → 423 TENANT_READ_ONLY`), independent of the API. Logins, notifications and the audit log keep working.
- **Support access** (D-117): granted by the owner for 1–72 h with a reason, revocable; without a grant the console returns `SUPPORT_NOT_GRANTED`; every look is audit-logged in the showroom's own log.
- **Signup** (D-118): a signed-in user may own at most three showrooms (`SIGNUP_LIMIT`).

### 3.4 Offline (PWA, D-120)

- The service worker caches API **reads** per tenant; it never caches `/me`, files or exports, and never queues writes. Offline writes are refused in the app (`OFFLINE`). Sign-out clears the API cache.
- Production builds only, so development never serves stale code.

## 4. Dependency audit (2026-10-03)

| Scope | Tool | Result |
|---|---|---|
| Web — runtime dependencies | `npm audit --omit=dev` | **0 vulnerabilities** |
| Web — development tooling | `npm audit` | 11 high, all one advisory: `braces` (GHSA-vfj7-8cjw-p6xm, ReDoS on crafted glob patterns) reached only through `stylelint` and its plugins. Lint-time only, our own patterns, nothing in the bundle; no upstream fix yet. **Accepted; re-check monthly** |
| API | `pip-audit` | **No known vulnerabilities** |

CI should run both audits (§6).

## 5. Secrets

- Only `.env.example` files are committed; GitHub push protection is on.
- The service-role/secret key lives only in the API's environment; the Angular app uses the publishable key and the user's own JWT.
- `NATIONAL_ID_KEY` and `PRIMEUI_LICENSE` come from the environment and are never committed.
- Exports (`apps/api/exports/`) are ignored by Git.

## 6. Open items (owner: deployment)

| # | Item | Severity | Notes |
|---|---|---|---|
| S-01 | Web hosting must send a CSP and HSTS for the Angular app | Medium | Suggested: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://*.supabase.co; connect-src 'self' https://<api-host> https://<project>.supabase.co wss://<project>.supabase.co; frame-ancestors 'none'` plus `X-Content-Type-Options`, `Referrer-Policy`. Test before enforcing (`Content-Security-Policy-Report-Only`) |
| S-02 | Rate limits across several API instances | Medium | In-memory limits are per instance; add proxy limits (or Redis) when scaling out |
| S-03 | Hosted Supabase Auth settings | Medium | Copy password policy, MFA TOTP, refresh-token rotation and Auth rate limits from `config.toml`; turn on leaked-password protection |
| S-04 | Make two-step sign-in mandatory for owners and accountants? | Decision | Q-37 (default: optional, enforced once enrolled) |
| S-05 | Dependency audits in CI | Low | `npm audit --omit=dev --audit-level=high` and `pip-audit` as CI jobs (GitHub Actions must be enabled first) |
| S-06 | Data-protection hosting decision | Decision | Q-21: before the first real tenant data |
| S-07 | Statement timeout for the `app_api` role | Low | e.g. `alter role app_api set statement_timeout = '15s'` in the hosted project, after checking the slowest report on real volume (PERFORMANCE.md) |
