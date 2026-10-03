"""Customer requests, matching and follow-ups (SPEC §4.6, D-22).

Matching runs in the database (private.vehicle_available_match): when a car
becomes AVAILABLE it is matched against every open request and the members
who manage requests are notified. A new request is matched against the cars
available now (private.match_request).

Follow-ups are an append-only log: a call is recorded, never edited.
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.core.errors import AppError, not_found
from app.domain.consignment import (
    CustomerRequestIn,
    CustomerRequestOut,
    CustomerRequestUpdate,
    FollowUpDue,
    FollowUpIn,
    FollowUpOut,
    RequestMatch,
)
from app.domain.money import format_money
from app.services import customers, finance

_REQUESTS = """
    select r.*, c.name as customer_name, c.phone_primary as customer_phone,
           coalesce(u.full_name, u.email) as assigned_name,
           (select count(*) from public.customer_request_matches m
              join public.vehicles v on v.id = m.vehicle_id
             where m.request_id = r.id and v.status in ('AVAILABLE', 'RESERVED')) as match_count
      from public.customer_requests r
      join public.customers c on c.id = r.customer_id
      left join private.tenant_members() u on u.user_id = r.assigned_to
"""

_MATCHES = """
    select m.id, m.request_id, m.vehicle_id, v.stock_no, concat_ws(' ', v.make, v.model, v.year) as vehicle_label,
           v.status as vehicle_status, v.asking_price, r.customer_id, c.name as customer_name,
           c.phone_primary as customer_phone, r.make, r.model, r.year_from, r.year_to, r.budget_max,
           m.matched_at, m.contacted, m.contacted_at
      from public.customer_request_matches m
      join public.customer_requests r on r.id = m.request_id
      join public.customers c on c.id = r.customer_id
      join public.vehicles v on v.id = m.vehicle_id
"""


def request_summary(row: Any, currency: str) -> str:
    """A one-line description of what the customer wants, e.g. “Toyota Corolla 2018-2021 ≤ 450,000”."""
    parts = [" ".join(p for p in (row["make"], row["model"]) if p)]
    if row["year_from"] or row["year_to"]:
        parts.append(f"{row['year_from'] or ''}-{row['year_to'] or ''}")
    if row["budget_max"] is not None:
        parts.append(f"≤ {format_money(row['budget_max'], currency, 'en')}")
    return " ".join(parts)


def _match(row: Any, currency: str) -> RequestMatch:
    return RequestMatch.model_validate({**row, "request_summary": request_summary(row, currency)})


def get_request(conn: Connection, request_id: UUID) -> CustomerRequestOut:
    row = conn.execute(text(_REQUESTS + " where r.id = :id"), {"id": request_id}).mappings().first()
    if row is None:
        raise not_found("customer request")
    out = CustomerRequestOut.model_validate(dict(row))
    currency = finance.tenant_info(conn).currency
    out.matches = [
        _match(m, currency)
        for m in conn.execute(
            text(_MATCHES + " where m.request_id = :id order by m.contacted, m.matched_at desc"), {"id": request_id}
        ).mappings()
    ]
    return out


def list_requests(
    conn: Connection, *, status: str | None, customer_id: UUID | None, open_only: bool, q: str | None
) -> list[CustomerRequestOut]:
    rows = conn.execute(
        text(
            _REQUESTS
            + """
             where (cast(:status as text) is null or r.status = :status)
               and (cast(:customer as uuid) is null or r.customer_id = :customer)
               and (not :open_only or r.status not in ('WON', 'LOST'))
               and (cast(:q as text) is null or c.name ilike '%' || :q || '%' or r.make ilike '%' || :q || '%'
                    or r.model ilike '%' || :q || '%' or c.phone_primary like '%' || :q || '%')
             order by match_count desc, r.created_at desc
            """
        ),
        {
            "status": status,
            "customer": customer_id,
            "open_only": open_only,
            "q": q.strip() if q and q.strip() else None,
        },
    ).mappings()
    return [CustomerRequestOut.model_validate(dict(row)) for row in rows]


def _check_member(conn: Connection, user_id: UUID | None) -> None:
    if user_id is None:
        return
    found = conn.execute(
        text(
            "select 1 from public.memberships where tenant_id = private.current_tenant_id() and user_id = :id "
            "and status = 'ACTIVE'"
        ),
        {"id": user_id},
    ).first()
    if found is None:
        raise AppError("USER_INVALID", "Assign the request to an active member of this showroom", status_code=422)


def create_request(conn: Connection, payload: CustomerRequestIn) -> CustomerRequestOut:
    customers.active_customer(conn, payload.customer_id)
    _check_member(conn, payload.assigned_to)
    values = payload.model_dump()
    values["financing_needed"] = bool(values["financing_needed"])
    values["trade_in_offered"] = bool(values["trade_in_offered"])
    request_id = conn.execute(
        text(
            """
            insert into public.customer_requests
              (tenant_id, customer_id, make, model, year_from, year_to, budget_min, budget_max, color_pref, notes,
               assigned_to, source, financing_needed, trade_in_offered)
            values (private.current_tenant_id(), :customer_id, :make, :model, :year_from, :year_to, :budget_min,
                    :budget_max, :color_pref, :notes, :assigned_to, :source, :financing_needed, :trade_in_offered)
            returning id
            """
        ),
        values,
    ).scalar_one()
    conn.execute(text("select private.match_request(:id)"), {"id": request_id})
    return get_request(conn, request_id)


def update_request(conn: Connection, request_id: UUID, changes: CustomerRequestUpdate) -> CustomerRequestOut:
    current = get_request(conn, request_id)
    values = changes.model_dump(exclude_unset=True)
    if "assigned_to" in values:
        _check_member(conn, values["assigned_to"])
    for flag in ("financing_needed", "trade_in_offered"):
        if flag in values and values[flag] is None:
            values.pop(flag)
    merged = {"make": current.make, "model": current.model, **values}
    if not merged["make"] and not merged["model"]:
        raise AppError("VALIDATION_ERROR", "give at least a make or a model", status_code=422)
    year_from = values.get("year_from", current.year_from)
    year_to = values.get("year_to", current.year_to)
    if year_from is not None and year_to is not None and year_from > year_to:
        raise AppError("VALIDATION_ERROR", "year from must not be after year to", status_code=422)
    budget_min = values.get("budget_min", current.budget_min)
    budget_max = values.get("budget_max", current.budget_max)
    if budget_min is not None and budget_max is not None and budget_min > budget_max:
        raise AppError("VALIDATION_ERROR", "the minimum budget must not exceed the maximum", status_code=422)
    if values:
        assignments = ", ".join(f"{column} = :{column}" for column in values)  # keys from a StrictModel
        conn.execute(
            text(f"update public.customer_requests set {assignments} where id = :id"),  # noqa: S608
            {**values, "id": request_id},
        )
    # New criteria may fit cars already in stock.
    conn.execute(text("select private.match_request(:id)"), {"id": request_id})
    return get_request(conn, request_id)


def vehicle_matches(conn: Connection, vehicle_id: UUID) -> list[RequestMatch]:
    """“N customers asked for this car”, with their phones, still-open requests only."""
    currency = finance.tenant_info(conn).currency
    rows = conn.execute(
        text(
            _MATCHES
            + """
             where m.vehicle_id = :id and r.status in ('NEW', 'CONTACTED', 'VEHICLE_FOUND', 'NEGOTIATING')
             order by m.contacted, m.matched_at
            """
        ),
        {"id": vehicle_id},
    ).mappings()
    return [_match(row, currency) for row in rows]


def set_contacted(conn: Connection, match_id: UUID, *, contacted: bool, user_id: UUID) -> RequestMatch:
    updated = conn.execute(
        text(
            """
            update public.customer_request_matches
               set contacted = :contacted,
                   contacted_by = case when :contacted then cast(:user as uuid) end,
                   contacted_at = case when :contacted then now() end
             where id = :id
            returning id
            """
        ),
        {"contacted": contacted, "user": user_id, "id": match_id},
    ).first()
    if updated is None:
        raise not_found("match")
    if contacted:
        # The request moves forward once the customer has been told about a car.
        conn.execute(
            text(
                "update public.customer_requests r set status = 'VEHICLE_FOUND' from public.customer_request_matches m "
                "where m.id = :id and r.id = m.request_id and r.status in ('NEW', 'CONTACTED')"
            ),
            {"id": match_id},
        )
    row = conn.execute(text(_MATCHES + " where m.id = :id"), {"id": match_id}).mappings().one()
    return _match(row, finance.tenant_info(conn).currency)


# --- Follow-ups -------------------------------------------------------------------------------------------

_FOLLOW_UPS = """
    with latest as (select distinct on (customer_id) id from public.follow_ups
                     order by customer_id, occurred_at desc, created_at desc)
    select f.*, c.name as customer_name, c.phone_primary as customer_phone,
           coalesce(a.full_name, a.email) as assigned_name,
           coalesce(w.full_name, w.email) as created_by_name
      from public.follow_ups f
      join public.customers c on c.id = f.customer_id
      left join private.tenant_members() a on a.user_id = f.assigned_to
      left join private.tenant_members() w on w.user_id = f.created_by
"""


def log_follow_up(conn: Connection, payload: FollowUpIn, *, user_id: UUID) -> FollowUpOut:
    customers.active_customer(conn, payload.customer_id)
    _check_member(conn, payload.assigned_to)
    if payload.request_id is not None:
        owner = conn.execute(
            text("select customer_id from public.customer_requests where id = :id"), {"id": payload.request_id}
        ).scalar_one_or_none()
        if owner != payload.customer_id:
            raise AppError("REQUEST_MISMATCH", "The request belongs to another customer", status_code=422)
    values = payload.model_dump()
    # Unassigned follow-ups stay with whoever logged them.
    values["assigned_to"] = payload.assigned_to or user_id
    follow_up_id = conn.execute(
        text(
            """
            insert into public.follow_ups
              (tenant_id, customer_id, request_id, kind, result, notes, next_action, next_follow_up_date,
               assigned_to, priority)
            values (private.current_tenant_id(), :customer_id, :request_id, :kind, :result, :notes, :next_action,
                    :next_follow_up_date, :assigned_to, :priority)
            returning id
            """
        ),
        values,
    ).scalar_one()
    if payload.request_id is not None and payload.kind == "CALL":
        conn.execute(
            text("update public.customer_requests set status = 'CONTACTED' where id = :id and status = 'NEW'"),
            {"id": payload.request_id},
        )
    row = conn.execute(text(_FOLLOW_UPS + " where f.id = :id"), {"id": follow_up_id}).mappings().one()
    return FollowUpOut.model_validate(dict(row))


def list_follow_ups(conn: Connection, *, customer_id: UUID | None, limit: int) -> list[FollowUpOut]:
    rows = conn.execute(
        text(
            _FOLLOW_UPS
            + """
             where (cast(:customer as uuid) is null or f.customer_id = :customer)
             order by f.occurred_at desc limit :limit
            """
        ),
        {"customer": customer_id, "limit": limit},
    ).mappings()
    return [FollowUpOut.model_validate(dict(row)) for row in rows]


def due_follow_ups(conn: Connection, *, assigned_to: UUID | None) -> list[FollowUpDue]:
    """Customers whose latest follow-up asks to be contacted again today or earlier."""
    today: date = finance.tenant_info(conn).today
    rows = conn.execute(
        text(
            _FOLLOW_UPS
            + """
             join latest l on l.id = f.id
             where f.next_follow_up_date <= :today
               and (cast(:assigned as uuid) is null or f.assigned_to = :assigned)
             order by f.next_follow_up_date, f.priority = :high desc, f.occurred_at
            """
        ),
        {"today": today, "assigned": assigned_to, "high": "HIGH"},
    ).mappings()
    return [
        FollowUpDue(
            follow_up=FollowUpOut.model_validate(dict(row)), overdue_days=(today - row["next_follow_up_date"]).days
        )
        for row in rows
    ]
