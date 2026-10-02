"""Posting engine: the only Python path into the ledger.

Calls private.post_journal_entry / private.reverse_journal_entry (the only
database entry points) and turns database rule violations into API errors.
The deferred balance check is forced to run immediately, so an unbalanced
entry fails inside the service with a clear error instead of at commit.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError
from app.domain.ledger import Account, EntryDraft, LedgerRuleError, Line

# SQLSTATEs raised by supabase/migrations/*_journal.sql
_DB_ERRORS: dict[str, tuple[str, int, str]] = {
    "SR001": ("PERIOD_LOCKED", 422, "The accounting month is locked"),
    "SR002": ("ENTRY_UNBALANCED", 422, "The journal entry does not balance"),
    "SR003": ("LEDGER_IMMUTABLE", 409, "Posted records cannot be changed; reverse them instead"),
    "SR004": ("ENTRY_ALREADY_REVERSED", 409, "This entry has already been reversed"),
    "SR005": ("ACCOUNT_NOT_POSTABLE", 422, "The account cannot receive postings"),
    "SR006": ("SUBLEDGER_MISMATCH", 422, "The account and its subledger do not match"),
    "SR007": ("INVALID_ENTRY", 422, "The journal entry is invalid"),
    "SR008": ("ENTRY_IS_REVERSAL", 409, "A reversal entry cannot be reversed"),
    "23503": ("INVALID_REFERENCE", 422, "A referenced record does not exist in this showroom"),
}


@dataclass(frozen=True)
class PostedEntry:
    id: UUID
    entry_no: int


def map_db_error(error: DBAPIError) -> AppError | None:
    sqlstate = getattr(error.orig, "sqlstate", None)
    if sqlstate not in _DB_ERRORS:
        return None
    code, status, message = _DB_ERRORS[sqlstate]
    details: dict[str, object] = {}
    diag = getattr(error.orig, "diag", None)
    detail = getattr(diag, "message_detail", None)
    if sqlstate == "SR001" and detail:
        details["period"] = detail
    elif sqlstate in ("SR005", "SR006") and detail:
        details["account_code"] = detail
    return AppError(code, message, status_code=status, details=details)


def _raise_mapped(error: DBAPIError) -> None:
    mapped = map_db_error(error)
    if mapped is not None:
        raise mapped from error
    raise error


_SYSTEM_ACCOUNTS = text(
    "select system_key, id from public.ledger_accounts where system_key is not null and archived_at is null"
)


def system_accounts(conn: Connection) -> dict[str, UUID]:
    return {row.system_key: row.id for row in conn.execute(_SYSTEM_ACCOUNTS)}


def _check_immediately(conn: Connection) -> None:
    conn.execute(text("set constraints all immediate"))
    conn.execute(text("set constraints all deferred"))


def post(conn: Connection, draft: EntryDraft) -> PostedEntry:
    """Validate and post a draft in the caller's transaction."""
    try:
        payload = draft.to_payload(system_accounts(conn))
    except LedgerRuleError as exc:
        raise AppError("INVALID_ENTRY", str(exc), status_code=422) from exc
    try:
        row = conn.execute(
            text("select journal_entry_id, entry_no from private.post_journal_entry(cast(:entry as jsonb))"),
            {"entry": json.dumps(payload)},
        ).one()
        _check_immediately(conn)
    except DBAPIError as exc:
        _raise_mapped(exc)
        raise  # unreachable; keeps type checkers satisfied
    return PostedEntry(id=row.journal_entry_id, entry_no=row.entry_no)


def reverse(conn: Connection, entry_id: UUID, reason: str, on_date: date) -> PostedEntry:
    """Rule 24 in the database: exact mirror, linked both ways."""
    try:
        row = conn.execute(
            text("select journal_entry_id, entry_no from private.reverse_journal_entry(:id, :reason, :on_date)"),
            {"id": entry_id, "reason": reason, "on_date": on_date},
        ).one()
        _check_immediately(conn)
    except DBAPIError as exc:
        _raise_mapped(exc)
        raise
    return PostedEntry(id=row.journal_entry_id, entry_no=row.entry_no)


_ENTRY_LINES = text(
    """
    select ledger_account_id, debit, credit, cash_account_id, partner_id, customer_id, vehicle_id,
           consignor_id, external_showroom_id, supplier_id, memo
      from public.journal_lines
     where journal_entry_id = :id
     order by line_no
    """
)


def entry_lines(conn: Connection, entry_id: UUID) -> tuple[Line, ...]:
    return tuple(
        Line(
            account=Account.by_id(row.ledger_account_id),
            debit=Decimal(row.debit),
            credit=Decimal(row.credit),
            cash_account_id=row.cash_account_id,
            partner_id=row.partner_id,
            customer_id=row.customer_id,
            vehicle_id=row.vehicle_id,
            consignor_id=row.consignor_id,
            external_showroom_id=row.external_showroom_id,
            supplier_id=row.supplier_id,
            memo=row.memo,
        )
        for row in conn.execute(_ENTRY_LINES, {"id": entry_id})
    )
