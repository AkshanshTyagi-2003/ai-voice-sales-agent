"""
Post-call follow-up actions.

Provides reusable follow-up message generation and delivery.
"""

from dataclasses import dataclass
from typing import Optional, Protocol

from app.actions.whatsapp import (
    WhatsAppClient,
    WhatsAppResult,
)
from app.core.models import Lead


@dataclass
class FollowUpResult:
    """Result of a follow-up action."""

    success: bool
    message: str
    whatsapp_result: Optional[WhatsAppResult] = None


class FollowUpMessageBuilder(Protocol):
    """Interface for generating follow-up content."""

    def build(
        self,
        lead: Lead,
    ) -> str:
        ...


class DefaultFollowUpMessageBuilder:
    """Builds a simple sales follow-up message."""

    def build(
        self,
        lead: Lead,
    ) -> str:
        """Generate a personalized follow-up."""

        name = lead.name or "there"

        return (
            f"Hi {name}, thank you for speaking with us today. "
            "We'd be happy to help you with your e-commerce "
            "website project. Please reply here if you'd like "
            "to discuss the next steps."
        )


class FollowUpManager:
    """Manages post-call follow-ups."""

    def __init__(
        self,
        whatsapp_client: Optional[WhatsAppClient] = None,
        message_builder: Optional[
            FollowUpMessageBuilder
        ] = None,
    ) -> None:
        self.whatsapp_client = whatsapp_client
        self.message_builder = (
            message_builder
            or DefaultFollowUpMessageBuilder()
        )

    def build_message(
        self,
        lead: Lead,
    ) -> str:
        """Build a follow-up message."""

        return self.message_builder.build(lead)

    def send(
        self,
        lead: Lead,
    ) -> FollowUpResult:
        """Send a post-call WhatsApp follow-up."""

        message = self.build_message(lead)

        if not self.whatsapp_client:
            return FollowUpResult(
                success=False,
                message=(
                    "No WhatsApp client is configured."
                ),
            )

        result = self.whatsapp_client.send_to_lead(
            lead,
            message,
        )

        return FollowUpResult(
            success=result.success,
            message=(
                "Follow-up sent successfully."
                if result.success
                else result.message
            ),
            whatsapp_result=result,
        )