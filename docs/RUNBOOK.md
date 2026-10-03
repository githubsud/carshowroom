# SayyaraDMS — Operations runbook

**Audience:** whoever runs the platform (today the product team; later an on-call engineer).
**Scope:** backups, restores, tenant data exports, suspension, support access, and the first checks when something is wrong.
**Status:** Phase 9 (BACKLOG 9.9). The restore drill in §3 was rehearsed on 2026-10-03 on the local stack with the performance volume.

---

## 1. What protects the data

| Layer | What it covers | Where it lives | Retention |
|---|---|---|---|
| Supabase managed backups (PITR on paid plans) | The whole database, every tenant | Supabase | Per Supabase plan; **choose a plan with PITR before the first real tenant** |
| Our logical dump (`pg_dump -Fc`), nightly | The whole database, every tenant | Off-Supabase object storage (to be chosen with Q-21 hosting) | 30 days (DECISION, D-122) |
| Per-tenant nightly export (JSON zip) | One showroom's rows, every tenant table | `EXPORT_DIR/<tenant_id>/<date>.zip` written by the worker | `EXPORT_KEEP_DAYS` (default 14) |
| Tenant on-demand export | One showroom, now | Downloaded by the owner (Settings → Subscription & support → Download now) | The owner's copy |
| Ledger immutability | Posted entries are never changed or deleted; corrections are reversals | Database triggers | Forever |

A suspended or archived showroom is never deleted: it becomes read-only in the API **and** in the database (SR040, D-113).

---

## 2. Nightly jobs

The worker (`python -m app.jobs.worker`, hourly by default, or `--once` from cron) runs, for every showroom whose tenant status is ACTIVE (suspended subscriptions included, so their owners keep a copy), at most once per day of that showroom's own time zone:

1. reminders and "needs attention" notifications (Phases 5 and 7);
2. the per-tenant export (`services/platform.nightly_export`), then deletes that showroom's exports older than `EXPORT_KEEP_DAYS`. A run is recorded in `reminder_jobs` (`tenant_export`) in the same transaction, so a failed export is retried on the next run.

Check that last night's exports exist:

```bash
ls -l "$EXPORT_DIR"/*/$(date +%F).zip | wc -l     # one per live showroom
```

If a showroom is missing, look for `reminders failed` with its `tenant_id` in the worker log (the message covers both jobs); one showroom's failure never stops the others.

The whole-database dump is a platform job outside the app (cron on the ops host):

```bash
pg_dump -Fc --no-owner "$ADMIN_DATABASE_URL" -f "sayyara-$(date +%F).dump"
# then copy to object storage and delete local copies older than 30 days
```

---

## 3. Restore drill (rehearsed)

Rehearse this **every quarter** and after any schema change that touches the ledger. Record the date and the numbers in §3.3.

### 3.1 Steps

```bash
# 1. Dump the source (the whole database: auth, storage and our schemas belong together)
pg_dump -Fc --no-owner "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -f drill.dump

# 2. Restore into an empty database
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -c "create database restore_drill"
pg_restore --no-owner -d "postgresql://postgres:postgres@127.0.0.1:54322/restore_drill" drill.dump

# 3. Compare (run against both databases; every number must match)
psql "$DB" -c "select count(*), sum(debit), sum(credit) from public.journal_lines"
psql "$DB" -c "select count(*) from (select entry_id from public.journal_lines group by entry_id
               having sum(debit) <> sum(credit)) x"                      # must be 0
psql "$DB" -c "select count(*) from public.vehicles"
psql "$DB" -c "select count(*) from auth.users"

# 4. Drop the drill database
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -c "drop database restore_drill"
```

`pg_restore` reports errors for Supabase-owned objects (realtime publications, a few role grants) when restoring into a plain database. They are expected; the comparison in step 3 is what decides success. Restoring only `public` and `private` does **not** work: memberships and audit rows reference `auth.users`.

### 3.2 Restoring production

1. Prefer Supabase PITR to a time just before the incident (Dashboard → Database → Backups). It restores the whole project.
2. Without PITR, restore the latest nightly dump into a **new** project, point a staging API at it, run §3.1 step 3, then switch the API's `DATABASE_URL`.
3. Restoring **one** showroom from its JSON export is a manual, reviewed operation (no tool yet, BACKLOG later): never overwrite a live tenant's ledger; post differences as correcting entries instead.

### 3.3 Drill log

| Date | Source | Result |
|---|---|---|
| 2026-10-03 | Local stack with the demo seed plus the performance volume (scripts/perf_seed.py) | Restored in full. 100,236 journal lines with identical debit and credit sums, 0 unbalanced entries, 5,020 vehicles, 7 auth users, all identical to the source. Only Supabase realtime/grant errors from pg_restore |

---

## 4. Common operations

### Suspend or reactivate a showroom
Platform console (`/admin`, platform admins only) → Manage → status → reason → Save. Suspended and archived showrooms are read-only; users can still sign in, read and export. Every change is audit-logged with the reason (actor kind PLATFORM).

### Support access
The showroom owner grants it (Settings → Subscription & support) for 1 to 72 hours with a reason and can revoke it at any time. Without an active grant the console shows nothing of the showroom's data (`SUPPORT_NOT_GRANTED`). Every look is audit-logged in the showroom's own log, which the owner can read.

### Mark an invoice paid
Console → Manage → Invoices → Mark paid. Paying makes the subscription ACTIVE until the invoice's period end, also for a PAST_DUE or SUSPENDED showroom (D-116).

### A user lost their authenticator
Only a platform operator can remove a factor: Supabase Dashboard → Authentication → the user → MFA factors → delete, after verifying the person out of band (a call to the showroom owner). Record it in the showroom's support ticket.

---

## 5. First checks when something is wrong

| Symptom | Check |
|---|---|
| Users get `TENANT_READ_ONLY` | The showroom's subscription status in the console (SUSPENDED or ARCHIVED) |
| Users get `PLAN_LIMIT_REACHED` | The usage meters in Settings → Subscription & support; upgrade the plan in the console |
| Users get `RATE_LIMITED` (429) | Many requests from one IP (shared office NAT?). Limits are per API instance (`app/core/http_guard.py`) |
| `MFA_REQUIRED` after sign-in | The user enabled two-step sign-in; they must enter the code (login page second step) |
| Balance check fails in CI | `supabase/tests/database` balance tests and `tests/integration/test_full_scenario.py`; never "fix" by editing posted entries |
| Slow pages | `scripts/perf_check.py` against a copy; see PERFORMANCE.md |
