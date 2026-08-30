"""
WhatsApp action layer.

Provides a provider-independent interface for sending WhatsApp
messages to leads.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from app.core.models import Lead
from app.core.config import settings
from app.utils.helpers import normalize_phone_number


@dataclass
class WhatsAppMessage:
    """WhatsApp message request."""

    phone_number: str
    message: str


@dataclass
class WhatsAppResult:
    """Result of a WhatsApp send operation."""

    success: bool
    message_id: Optional[str] = None
    message: str = ""
    raw_response: Optional[Dict[str, Any]] = None


class WhatsAppProvider(Protocol):
    """Interface required by a WhatsApp provider."""

    def send_message(
        self,
        request: WhatsAppMessage,
    ) -> WhatsAppResult:
        ...


class WhatsAppClient:
    """Provider-independent WhatsApp client."""

    def __init__(
        self,
        provider: Optional[WhatsAppProvider] = None,
    ) -> None:
        self.provider = provider

    def send(
        self,
        phone_number: str,
        message: str,
    ) -> WhatsAppResult:
        """Send a WhatsApp message."""

        phone_number = normalize_phone_number(
            phone_number
        )

        message = message.strip()

        if not phone_number:
            return WhatsAppResult(
                success=False,
                message="Invalid phone number.",
            )

        if not message:
            return WhatsAppResult(
                success=False,
                message="WhatsApp message cannot be empty.",
            )

        if not self.provider:
            return WhatsAppResult(
                success=False,
                message=(
                    "No WhatsApp provider is configured."
                ),
            )

        request = WhatsAppMessage(
            phone_number=phone_number,
            message=message,
        )

        try:
            return self.provider.send_message(
                request
            )
        except Exception as exc:
            return WhatsAppResult(
                success=False,
                message=f"WhatsApp provider error: {exc}",
            )

    def send_to_lead(
        self,
        lead: Lead,
        message: str,
    ) -> WhatsAppResult:
        """Send a WhatsApp message to a lead."""

        return self.send(
            lead.phone_number,
            message,
        )


class MockWhatsAppProvider:
    """Local provider that records messages without sending them."""

    def __init__(self) -> None:
        self.messages = []

    def send_message(
        self,
        request: WhatsAppMessage,
    ) -> WhatsAppResult:
        """Record a simulated WhatsApp message."""

        message_id = (
            f"mock-whatsapp-{len(self.messages) + 1}"
        )

        self.messages.append(request)

        return WhatsAppResult(
            success=True,
            message_id=message_id,
            message="Mock WhatsApp message sent.",
            raw_response={
                "message_id": message_id,
                "phone_number": request.phone_number,
                "message": request.message,
            },
        )