# SayyaraDMS (سيارة)

Multi-tenant SaaS for car showrooms (Egypt and Qatar first): vehicles, money, customers, partners and real profit in one place.

- Specification: [docs/SPEC.md](docs/SPEC.md)
- Design: [PRD](docs/PRD.md) · [Architecture](docs/ARCHITECTURE.md) · [ERD](docs/ERD.md) · [Accounting](docs/ACCOUNTING.md) · [API](docs/API.md) · [Frontend](docs/FRONTEND.md)
- **Sharia compliance (binding):** [docs/SHARIA.md](docs/SHARIA.md)
- Plan and decisions: [Backlog](docs/BACKLOG.md) · [Decisions](docs/DECISIONS.md)
- Operations: [Runbook](docs/RUNBOOK.md) · [Security](docs/SECURITY.md) · [Performance](docs/PERFORMANCE.md)

## Layout

```text
apps/web     Angular 22 PWA (PrimeNG, Transloco, Supabase JS)
apps/api     FastAPI (Python 3.12, SQLAlchemy Core + psycopg 3)
supabase     SQL migrations (single source of truth), seed, pgTAP tests
docs         Specification and design documents
```

## Prerequisites

Node ≥ 22.22 (Angular 22 requirement), Python 3.12, Docker (for the local Supabase stack). The Supabase CLI runs through `npx supabase`.

## First run

```bash
# Windows: ./scripts/dev.ps1 <command>     Linux/macOS: make <command>
setup       # venv + API deps, npm deps, Playwright browser
db-start    # local Supabase: applies migrations + seed, then writes apps/api/.env (secret key from `supabase status`)
api         # http://localhost:8000  (OpenAPI docs: /api/v1/docs)
web         # http://localhost:4200
```

Demo users (local seed only; password `Demo-Pass-2026`):

| Email | Showroom | Role |
|---|---|---|
| owner@nour.example | معرض النور للسيارات (EG) | Owner |
| accountant@nour.example | معرض النور | Accountant |
| sales@nour.example | معرض النور | Sales |
| partner@nour.example | معرض النور + Doha Motors | Partner (two showrooms) |
| owner@doha.example | Doha Motors (QA) | Owner |

Invitation emails sent locally can be read in Mailpit at http://127.0.0.1:54324.

## Background worker

Daily installment reminders run in a worker that uses the API image (D-86):

```bash
cd apps/api && .venv/bin/python -m app.jobs --once   # one run (cron style)
docker compose up worker                              # hourly loop, one advisory lock across copies
```

Each showroom is processed once a day; reminders appear in the notification bell. SMS and WhatsApp
providers only log until real providers are configured.

## PrimeUI licence

PrimeNG needs a PrimeUI licence key (DECISIONS Q-38). Set it as an environment variable before starting or building the web app; it is never committed:

```powershell
$env:PRIMEUI_LICENSE = "<your key>"; ./scripts/dev.ps1 web
# build: npx ng build --define PRIMEUI_LICENSE="'<your key>'"
```

Without a key the app works but shows an "Invalid PrimeUI License" notice.

## Tests

```bash
db-test     # pgTAP: RLS on every table, cross-tenant isolation, permissions, append-only audit log
test        # pgTAP + API (unit + integration against real Supabase logins) + web unit + Playwright E2E
lint        # ruff, mypy --strict, eslint, stylelint (logical CSS properties enforced for RTL)
```

Integration and E2E tests need the local stack running with the seed (`db-start`, or `db-reset` to start clean).

## Rules that matter

- The browser never writes financial tables; money moves only through the API (SPEC §3.1).
- Every tenant table goes through `private.secure_table()` and has RLS; pgTAP fails otherwise.
- Code checks permissions, never role names. Sales never receives cost data.
- No secrets in git: only `.env.example` files. The service-role/secret key is API-only.
