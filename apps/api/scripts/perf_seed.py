"""Load the performance volume (scripts/perf_seed.sql) into the local database.

    .venv/Scripts/python scripts/perf_seed.py

Uses TEST_ADMIN_DATABASE_URL (default: the local Supabase postgres user).
"""

import os
import time
from pathlib import Path

import psycopg

URL = os.environ.get("TEST_ADMIN_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")

if __name__ == "__main__":
    sql = (Path(__file__).parent / "perf_seed.sql").read_text(encoding="utf-8")
    started = time.monotonic()
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute(sql)  # type: ignore[arg-type]
        lines = conn.execute(
            "select count(*) from public.journal_lines where tenant_id = '33333333-3333-3333-3333-333333333333'"
        ).fetchone()
        cars = conn.execute(
            "select count(*) from public.vehicles where tenant_id = '33333333-3333-3333-3333-333333333333'"
        ).fetchone()
    print(
        f"perf showroom ready in {time.monotonic() - started:.0f}s: {cars[0] if cars else 0} vehicles, "
        f"{lines[0] if lines else 0} journal lines"
    )
