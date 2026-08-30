"""
Lead action orchestration.

Coordinates actions triggered by lead intent, callbacks,
mid-call qualification, and post-call follow-ups.
"""

from dataclasses import dataclass
from typing import Optional

from app.actions.callback import (
    CallbackManager,
    CallbackResult,
)
from app.actions.followup import (
    FollowUpManager,
    FollowUpResult,
)
from app.actions.whatsapp import (
    WhatsAppClient,
    WhatsAppResult,
)
from app.core.models import (
    Conversation,
    Lead,
    LeadTemperature,
)
from app.storage.repository import (
    conversation_repository,
    lead_repository,
)


@dataclass
class LeadActionResult:
    """Combined result from a lead action."""

    success: bool
    action: str
    message: str
    whatsapp_result: Optional[WhatsAppResult] = None
    callback_result: Optional[CallbackResult] = None
    followup_result: Optional[FollowUpResult] = None


class LeadActionManager:
    """Coordinates all actions associated with a lead."""

    def __init__(
        self,
        whatsapp_client: Optional[
            WhatsAppClient
        ] = None,
        callback_manager: Optional[
            CallbackManager
        ] = None,
        followup_manager: Optional[
            FollowUpManager
        ] = None,
    ) -> None:
        self.whatsapp_client = whatsapp_client
        self.callback_manager = (
            callback_manager
            or CallbackManager()
        )
        self.followup_manager = (
            followup_manager
            or FollowUpManager(
                whatsapp_client=whatsapp_client
            )
        )

    def save_lead_state(
        self,
        lead: Lead,
        conversation: Optional[
            Conversation
        ] = None,
    ) -> None:
        """Persist the latest lead and conversation state."""

        lead_repository.save(lead)

        if conversation:
            conversation_repository.save(
                conversation
            )

    def handle_high_intent(
        self,
        lead: Lead,
        conversation: Conversation,
    ) -> LeadActionResult:
        """
        Handle a high-intent lead during a call.

        Sends a WhatsApp message once per conversation.
        """

        if conversation.whatsapp_sent_mid_call:
            return LeadActionResult(
                success=True,
                action="high_intent",
                message=(
                    "High-intent WhatsApp already sent."
                ),
            )

        if not self.whatsapp_client:
            return LeadActionResult(
                success=False,
                action="high_intent",
                message=(
                    "No WhatsApp client is configured."
                ),
            )

        message = (
            "Hi! Thanks for your interest in our "
            "e-commerce website development service. "
            "We've noted your requirements and will "
            "be happy to discuss the next steps."
        )

        result = self.whatsapp_client.send_to_lead(
            lead,
            message,
        )

        if result.success:
            conversation.whatsapp_sent_mid_call = True

            self.save_lead_state(
                lead,
                conversation,
            )

        return LeadActionResult(
            success=result.success,
            action="high_intent",
            message=result.message,
            whatsapp_result=result,
        )

    def handle_callback_request(
        self,
        lead: Lead,
        conversation: Conversation,
        requested_time_text: str,
    ) -> LeadActionResult:
        """Create and persist a callback request."""

        result = self.callback_manager.request_callback(
            lead,
            requested_time_text,
        )

        if result.success:
            conversation.callback_requested = True

            self.save_lead_state(
                lead,
                conversation,
            )

        return LeadActionResult(
            success=result.success,
            action="callback",
            message=result.message,
            callback_result=result,
        )

    def handle_post_call_followup(
        self,
        lead: Lead,
        conversation: Conversation,
    ) -> LeadActionResult:
        """Send a follow-up after a completed call."""

        result = self.followup_manager.send(
            lead
        )

        if result.success:
            self.save_lead_state(
                lead,
                conversation,
            )

        return LeadActionResult(
            success=result.success,
            action="followup",
            message=result.message,
            followup_result=result,
        )

    def should_trigger_high_intent(
        self,
        lead: Lead,
    ) -> bool:
        """Determine whether a lead qualifies for a high-intent action."""

        return (
            lead.temperature
            == LeadTemperature.HOT
            and lead.intent_score >= 0.70
        )