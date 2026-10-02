"""Field-level cost masking (ARCHITECTURE §5, layer 1).

A user without vehicle.view_cost (or vehicle.view_min_price) gets responses
in which the cost keys do not exist at all — not even as null — so nothing in
the JSON hints at cost. Integration tests walk every sales-role response for
these keys.
"""

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import TenantContext
from app.domain.permissions import Permission
from app.domain.vehicles import COST_FIELDS, MIN_PRICE_FIELD


def hidden_fields(ctx: TenantContext) -> set[str]:
    hidden: set[str] = set()
    if not ctx.can(Permission.VEHICLE_VIEW_COST):
        hidden |= COST_FIELDS
    if not ctx.can(Permission.VEHICLE_VIEW_MIN_PRICE):
        hidden.add(MIN_PRICE_FIELD)
    return hidden


def strip(value: Any, hidden: set[str]) -> Any:
    if isinstance(value, dict):
        return {key: strip(item, hidden) for key, item in value.items() if key not in hidden}
    if isinstance(value, list):
        return [strip(item, hidden) for item in value]
    return value


def masked(model: BaseModel, ctx: TenantContext, *, status_code: int = 200) -> JSONResponse:
    """Serialize a response with the cost keys removed for this user, at any depth."""
    return JSONResponse(strip(model.model_dump(mode="json"), hidden_fields(ctx)), status_code=status_code)
