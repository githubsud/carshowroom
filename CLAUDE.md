# SayyaraDMS — rules for working in this repository

## 1. Sharia compliance comes first (binding)

Nothing in SayyaraDMS may contradict Islamic Sharia. Read [docs/SHARIA.md](docs/SHARIA.md) before designing or changing anything that touches money, sales, installments, partners, investors, loans, deposits, fees or their wording.

- Never add interest (riba) in any form, late-payment fees that become income, price increases after a contract, sale of debts or receivables, or guaranteed returns on investment.
- The gain on an installment sale is **sale profit** (فرق سعر التقسيط / أرباح البيع بالتقسيط), never "فائدة" or "interest", in code, UI, documents and messages.
- If a request or an existing behaviour may conflict with Sharia, do not build it: record it in docs/SHARIA.md §5 as SHARIA REVIEW and ask the product owner.

## 2. Other standing rules

- Do not invent accounting, tax or legal rules: mark them as OPEN QUESTION in docs/DECISIONS.md and implement only approved or option-based behaviour. Record contradictions and decisions in docs/DECISIONS.md.
- Never commit secrets: only `.env.example` files. The Supabase service-role/secret key stays in the API only, never in the Angular app. `PRIMEUI_LICENSE` and `NATIONAL_ID_KEY` come from the environment.
- Every database migration ends with the full revoke/grant block for `app_api` (see the latest migration).
- Verify before committing: `npx supabase db reset` then `npx supabase test db`; in `apps/api`: ruff, ruff format, mypy, pytest; in `apps/web`: `ng build`, `ng lint`, `npm test`, Playwright E2E from a clean reset.
