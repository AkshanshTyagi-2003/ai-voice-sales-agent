"""
Call API endpoints.

Creates conversations and starts outbound calls through
the Retell AI telephony layer.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.models import Conversation, Lead
from app.core.state import state
from app.storage.repository import (
    conversation_repository,
    lead_repository,
)
from app.utils.helpers import (
    generate_id,
    normalize_phone_number,
)
from app.voice.telephony import (
    RetellTelephonyProvider,
    TelephonyClient,
)

router = APIRouter(
    prefix="/calls",
    tags=["calls"],
)


class CallRequest(BaseModel):
    """Request to start an outbound call."""

    phone_number: Optional[str] = None


class CallResponse(BaseModel):
    """Outbound call response."""

    success: bool
    call_id: Optional[str] = None
    conversation_id: Optional[str] = None
    phone_number: Optional[str] = None
    message: str


def get_telephony_client() -> TelephonyClient:
    """
    Build the Retell telephony client.

    Retell credentials are loaded from environment variables.
    """

    return TelephonyClient(
        provider=RetellTelephonyProvider(
            api_key=settings.retell_api_key,
            agent_id=settings.retell_agent_id,
            phone_number=settings.retell_phone_number,
        )
    )


@router.get("/retell/verify")
def verify_retell_configuration():
    """
    Verify Retell configuration without placing a call.

    This endpoint performs only read-only Retell API requests.
    It never creates a phone call.
    """

    try:
        provider = RetellTelephonyProvider(
            api_key=settings.retell_api_key,
            agent_id=settings.retell_agent_id,
            phone_number=settings.retell_phone_number,
        )

        verification = provider.verify_configuration()

        return {
            "success": True,
            "provider": "retell",
            "verification": verification,
            "ready_for_call": verification["ready_for_call"],
            "call_created": False,
            "message": (
                "Retell configuration verified. "
                "No phone call was created."
            ),
        }

    except Exception as exc:
        return {
            "success": False,
            "provider": "retell",
            "ready_for_call": False,
            "call_created": False,
            "message": str(exc),
        }


@router.post(
    "/outbound",
    response_model=CallResponse,
)
def create_outbound_call(
    request: CallRequest,
):
    """
    Create a conversation and initiate a real
    Retell AI outbound call.

    WARNING:
    Calling this endpoint WILL create a real call
    and consume Retell/telephony usage.
    """

    phone_number = normalize_phone_number(
        request.phone_number
        if request.phone_number
        else settings.target_phone_number
    )

    if not phone_number:
        raise HTTPException(
            status_code=400,
            detail="A valid phone number is required.",
        )

    lead = lead_repository.get_by_phone(
        phone_number
    )

    if lead is None:

        lead = Lead(
            lead_id=generate_id("lead"),
            phone_number=phone_number,
        )

        lead_repository.save(lead)

    conversation = Conversation(
        conversation_id=generate_id(
            "conversation"
        ),
        lead_id=lead.lead_id,
        phone_number=phone_number,
    )

    state.save_conversation(
        conversation
    )

    conversation_repository.save(
        conversation
    )

    try:

        client = get_telephony_client()

        result = client.make_outbound_call(
            conversation_id=(
                conversation.conversation_id
            ),
            phone_number=phone_number,
        )

    except Exception as exc:

        return CallResponse(
            success=False,
            call_id=None,
            conversation_id=(
                conversation.conversation_id
            ),
            phone_number=phone_number,
            message=(
                f"Unable to create Retell call: {exc}"
            ),
        )

    if not result.success:

        return CallResponse(
            success=False,
            call_id=result.call_id,
            conversation_id=(
                conversation.conversation_id
            ),
            phone_number=phone_number,
            message=result.message,
        )

    return CallResponse(
        success=True,
        call_id=result.call_id,
        conversation_id=(
            conversation.conversation_id
        ),
        phone_number=phone_number,
        message=result.message,
    )


@router.get("/{conversation_id}")
def get_call(
    conversation_id: str,
):
    """Retrieve a conversation associated with a call."""

    conversation = conversation_repository.get(
        conversation_id
    )

    if conversation is None:

        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return conversation.model_dump()