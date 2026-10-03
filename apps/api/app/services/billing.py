"""Payment collection behind one interface (BACKLOG 9.3, D-116).

Today a platform admin records a payment received outside the app (bank
transfer, cash) and marks the invoice paid: `ManualPaymentGateway`. A card or
wallet provider (Paymob, Fawry, ...) later implements the same interface:
`checkout` returns where to send the customer, and the provider's confirmed
webhook calls `confirm`, which ends in the same `mark_paid`.
"""

from typing import Protocol
from uuid import UUID

from sqlalchemy import Connection

from app.domain.platform import InvoiceOut
from app.services import platform


class PaymentGateway(Protocol):
    code: str

    def checkout(self, conn: Connection, invoice_id: UUID) -> str | None:
        """Where the payer goes to pay, or None when payment happens outside the app."""
        ...

    def confirm(self, conn: Connection, invoice_id: UUID, reference: str | None, *, actor: UUID) -> InvoiceOut:
        """Record a confirmed payment: the invoice becomes PAID and the subscription ACTIVE."""
        ...


class ManualPaymentGateway:
    code = "MANUAL"

    def checkout(self, conn: Connection, invoice_id: UUID) -> str | None:
        return None

    def confirm(self, conn: Connection, invoice_id: UUID, reference: str | None, *, actor: UUID) -> InvoiceOut:
        return platform.mark_paid(conn, invoice_id, reference, actor=actor)


def gateway() -> PaymentGateway:
    return ManualPaymentGateway()
