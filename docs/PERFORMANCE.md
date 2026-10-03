# SayyaraDMS — Performance

**Audience:** engineers changing queries, and whoever sizes the hosting.
**Target (SPEC §11):** dashboard, lists and reports under 2 s at p95 for a showroom with 5,000 vehicles and 100,000 journal lines.
**Result (2026-10-03):** met. Worst p95 is the dashboard at 897 ms. No summary table needed (D-12 stands, D-115).

---

## 1. How to measure

```bash
cd apps/api
.venv/Scripts/python scripts/perf_seed.py        # once: loads "معرض الأداء" (local/staging only)
.venv/Scripts/python scripts/perf_check.py 20    # 20 calls per endpoint, prints p50/p95/max
```

- `perf_seed.sql` builds one showroom (`33333333-…`, owner `perf@sayyara.example`) with 5,000 cars and about 100,000 journal lines. Every entry goes through `private.post_journal_entry`, so the ledger rules hold (balanced, numbered, immutable). It took 831 s on the development laptop.
- `perf_check.py` calls the real app in-process (FastAPI TestClient → local Supabase Postgres), signed in as the perf owner. The network hop of a deployment is not included; budget about 50–150 ms more per call from Cairo or Doha to the hosting region.

## 2. Results

Windows 11 laptop, local Supabase in Docker, 20 calls per endpoint, after warm-up.

| Endpoint | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|
| Dashboard | 504 | **897** | 1015 |
| Needs attention | 264 | 369 | 513 |
| Inventory (stock, page 1) | 45 | 49 | 51 |
| Inventory (all, by price) | 43 | 47 | 48 |
| Inventory search ("Corolla") | 66 | 104 | 163 |
| Sales list | 46 | 87 | 119 |
| Journal (page 1) | 30 | 38 | 40 |
| Customers | 27 | 49 | 115 |
| Profit and loss (one year) | 147 | 197 | 220 |
| Trial balance | 70 | 84 | 86 |
| Inventory aging | 225 | 320 | 351 |
| Vehicle profit (one year) | 194 | 316 | 318 |

An earlier run the same day gave a dashboard p95 of 524 ms; numbers on a laptop vary with load by about ±50%. Even the worst run stays well under the target.

## 3. What makes it fast

- Indexes on the hot filters, added in Phase 9 (`20261010000100_saas.sql`): `vehicles (tenant_id, status, stock_date)`, `journal_lines (tenant_id, ledger_account_id, entry_date)`, `sales (tenant_id, status, sale_date)`, on top of the earlier per-tenant indexes (ERD §10).
- Balances are indexed aggregates over `journal_lines` with the denormalized `entry_date` (no join to entries for date ranges).
- Lists are paged and sorted on the server.

## 4. When to revisit

- The dashboard is the heaviest call: it aggregates the whole ledger for its cards. If a showroom passes about 500,000 lines, or p95 on production passes 1.5 s, add a per-account daily balance table maintained in the posting transaction (the D-12 fallback). Measure first with `perf_check.py` on a copy.
- Set a statement timeout for the API role once real volumes are known (SECURITY.md S-07).
