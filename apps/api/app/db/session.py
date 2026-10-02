"""Database access as the app_api role (D-01, D-08, D-09).

Every unit of work is one transaction that first sets the request context with
transaction-local set_config(), so RLS policies for app_api and the audit
triggers see the acting user and tenant. Transaction-local settings are safe
behind Supavisor's transaction pooler.

Commits happen inside the endpoint (``with db.transaction(...)``), never in a
dependency teardown, so a failed commit can never follow a success response.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

from app.core.request_context import current_client

_SET_CONTEXT = text(
    """
    select set_config('app.user_id', :user_id, true),
           set_config('app.tenant_id', :tenant_id, true),
           set_config('app.request_id', :request_id, true),
           set_config('app.client_ip', :client_ip, true),
           set_config('app.user_agent', :user_agent, true)
    """
)


def create_db_engine(database_url: str) -> Engine:
    url = database_url
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        # No server-side prepared statements: required behind a transaction
        # pooler (R-05).
        connect_args={"prepare_threshold": None},
    )


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def transaction(self, *, user_id: UUID | None, tenant_id: UUID | None = None) -> Iterator[Connection]:
        client = current_client()
        with self.engine.begin() as conn:
            conn.execute(
                _SET_CONTEXT,
                {
                    "user_id": str(user_id) if user_id else "",
                    "tenant_id": str(tenant_id) if tenant_id else "",
                    "request_id": client.request_id if client else "",
                    "client_ip": client.ip if client and client.ip else "",
                    "user_agent": client.user_agent if client and client.user_agent else "",
                },
            )
            yield conn

    def ping(self) -> bool:
        with self.engine.connect() as conn:
            return bool(conn.execute(text("select 1")).scalar_one() == 1)
