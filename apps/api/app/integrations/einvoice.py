"""E-invoicing adapters (ARCHITECTURE §9). The product implements no tax rules
and submits nothing (D-39): the Egypt ETA adapter is a stub that only marks an
invoice as "not submitted", so the fields exist when the integration is built."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EInvoiceResult:
    status: str
    document_uuid: str | None = None


class EInvoiceAdapter(Protocol):
    def submit_document(self, invoice_no: str) -> EInvoiceResult: ...


class EgyptETAStub:
    def submit_document(self, invoice_no: str) -> EInvoiceResult:
        return EInvoiceResult(status="NOT_SUBMITTED")


class NoEInvoice:
    def submit_document(self, invoice_no: str) -> EInvoiceResult:
        return EInvoiceResult(status="NOT_APPLICABLE")


def adapter_for(name: str) -> EInvoiceAdapter:
    return EgyptETAStub() if name == "egypt_eta_stub" else NoEInvoice()
