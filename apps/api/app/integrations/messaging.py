"""Customer messaging providers (SPEC §4.8, F-13). The MVP sends nothing: the
log providers record what would be sent, so real SMS/WhatsApp providers can be
plugged in later without touching the reminder job."""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class MessageProvider(Protocol):
    def send(self, to: str, template: str, params: dict[str, str]) -> None: ...


class LogSmsProvider:
    def send(self, to: str, template: str, params: dict[str, str]) -> None:
        logger.info("sms not sent (no provider)", extra={"to_last4": to[-4:], "template": template})


class LogWhatsAppProvider:
    def send(self, to: str, template: str, params: dict[str, str]) -> None:
        logger.info("whatsapp not sent (no provider)", extra={"to_last4": to[-4:], "template": template})
