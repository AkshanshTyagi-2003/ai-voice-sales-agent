"""
WhatsApp webhook endpoints.

Receives inbound WhatsApp messages and connects them to the lead
and AI conversation pipeline.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ai.agent import create_sales_agent
from app.core.models import Conversation
from app.storage.repository import (
    conversation_repository,
    lead_repository,
)
from app.utils.helpers import (
    generate_id,
    normalize_phone_number,
)
from app.voice.conversation import ConversationManager
from app.voice.speech_to_text import (
    MockSpeechToTextProvider,
    SpeechToTextClient,
)
from app.voice.text_to_speech import (
    MockTextToSpeechProvider,
    TextToSpeechClient,
)

router = APIRouter(
    prefix="/webhook/whatsapp",
    tags=["whatsapp"],
)


class WhatsAppWebhook(BaseModel):
    """Incoming WhatsApp message."""

    phone_number: str
    message: str
    language: Optional[str] = "en"


def get_or_create_lead(
    phone_number: str,
):
    """Find an existing lead or create one."""

    from app.core.models import Lead

    normalized = normalize_phone_number(
        phone_number
    )

    lead = lead_repository.get_by_phone(
        normalized
    )

    if lead:
        return lead

    lead = Lead(
        lead_id=generate_id("lead"),
        phone_number=normalized,
    )

    lead_repository.save(lead)

    return lead


def get_or_create_conversation(
    lead,
):
    """Find an active conversation or create a new one."""

    conversations = (
        conversation_repository.get_by_lead(
            lead.lead_id
        )
    )

    for conversation in conversations:
        if conversation.status.value == "active":
            return conversation

    conversation = Conversation(
        conversation_id=generate_id(
            "conversation"
        ),
        lead_id=lead.lead_id,
        phone_number=lead.phone_number,
    )

    conversation_repository.save(
        conversation
    )

    return conversation


@router.post("")
def receive_whatsapp_message(
    event: WhatsAppWebhook,
):
    """Process an inbound WhatsApp message."""

    phone_number = normalize_phone_number(
        event.phone_number
    )

    if not phone_number:
        raise HTTPException(
            status_code=400,
            detail="Invalid phone number.",
        )

    if not event.message.strip():
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    lead = get_or_create_lead(
        phone_number
    )

    conversation = get_or_create_conversation(
        lead
    )

    stt = SpeechToTextClient(
        MockSpeechToTextProvider(
            text=event.message,
            language=event.language or "en",
        )
    )

    tts = TextToSpeechClient(
        MockTextToSpeechProvider()
    )

    manager = ConversationManager(
        speech_to_text=stt,
        text_to_speech=tts,
        sales_agent=create_sales_agent(),
    )

    if conversation.status.value != "active":
        manager.start(conversation)

    result = manager.process_audio(
        conversation=conversation,
        lead=lead,
        audio=event.message.encode("utf-8"),
        language=event.language or "en",
    )

    lead_repository.save(lead)
    conversation_repository.save(
        conversation
    )

    return {
        "success": True,
        "phone_number": lead.phone_number,
        "conversation_id": (
            conversation.conversation_id
        ),
        "response": result.response_text,
        "intent_score": lead.intent_score,
        "temperature": (
            lead.temperature.value
            if lead.temperature
            else None
        ),
    }