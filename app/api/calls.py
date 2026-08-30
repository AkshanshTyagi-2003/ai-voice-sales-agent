"""
Call API endpoints.

Creates conversations and starts outbound calls through the
provider-independent telephony layer.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.models import Conversation
from app.core.state import state
from app.storage.repository import (
    conversation_repository,
    lead_repository,
)
from app.utils.helpers import generate_id, normalize_phone_number
from app.voice.telephony import (
    MockTelephonyProvider,
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
    Build the telephony client.

    The mock provider is used until the real provider is connected.
    """

    return TelephonyClient(
        provider=MockTelephonyProvider()
    )


@router.post("/outbound", response_model=CallResponse)
def create_outbound_call(
    request: CallRequest,
):
    """Create a conversation and initiate an outbound call."""

    phone_number = normalize_phone_number(
        request.phone_number
        if request.phone_number
        else ""
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
        from app.core.models import Lead

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

    client = get_telephony_client()

    result = client.make_outbound_call(
        conversation_id=conversation.conversation_id,
        phone_number=phone_number,
    )

    if not result.success:
        return CallResponse(
            success=False,
            call_id=result.call_id,
            conversation_id=conversation.conversation_id,
            phone_number=phone_number,
            message=result.message,
        )

    return CallResponse(
        success=True,
        call_id=result.call_id,
        conversation_id=conversation.conversation_id,
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