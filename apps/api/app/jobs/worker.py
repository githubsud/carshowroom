"""Background worker (D-03, BACKLOG 5.7): the same image as the API, run as
``python -m app.jobs``. Every hour it takes a Postgres advisory lock (so only
one worker acts when several run) and, for each active tenant, runs the daily
installment reminders in that tenant's own date. reminder_jobs makes each
tenant's run happen once per day, however often the loop wakes up.
"""

import argparse
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import Database, create_db_engine
from app.integrations.messaging import LogSmsProvider, MessageProvider
from app.services import notifications

logger = logging.getLogger(__name__)
LOCK_KEY = "sayyara.daily_reminders"


def run_once(db: Database, sms: MessageProvider) -> dict[str, dict[str, int] | None]:
    results: dict[str, dict[str, int] | None] = {}
    with db.engine.connect() as lock_conn:
        locked = lock_conn.execute(text("select pg_try_advisory_lock(hashtext(:key))"), {"key": LOCK_KEY}).scalar_one()
        if not locked:
            logger.info("another worker holds the reminders lock; skipping")
            return results
        try:
            with db.engine.begin() as conn:
                tenants = list(conn.execute(text("select private.active_tenant_ids()")).scalars())
            for tenant_id in tenants:
                try:
                    with db.transaction(user_id=None, tenant_id=tenant_id) as conn:
                        timezone = conn.execute(
                            text("select timezone from public.tenants where id = :id"), {"id": tenant_id}
                        ).scalar_one()
                        today = datetime.now(ZoneInfo(timezone)).date()
                        results[str(tenant_id)] = notifications.run_reminders(conn, today, sms)
                except Exception:
                    # One tenant's failure must not stop the others.
                    logger.exception("reminders failed", extra={"tenant_id": str(tenant_id)})
        finally:
            lock_conn.execute(text("select pg_advisory_unlock(hashtext(:key))"), {"key": LOCK_KEY})
            lock_conn.commit()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="SayyaraDMS background worker")
    parser.add_argument("--once", action="store_true", help="run the jobs once and exit (cron style)")
    parser.add_argument("--interval", type=int, default=3600, help="seconds between runs")
    args = parser.parse_args()

    configure_logging()
    db = Database(create_db_engine(get_settings().database_url))
    sms = LogSmsProvider()
    while True:
        logger.info("reminders run: %s", run_once(db, sms))
        if args.once:
            return
        time.sleep(args.interval)
