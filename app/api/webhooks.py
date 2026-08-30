"""
Webhook endpoints for external providers.

Handles:
- Twilio voice lifecycle events
- Twilio speech input
- Twilio TwiML generation
- WhatsApp messages
"""

from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.ai.agent import create_sales_agent
from app.core.config import settings
from app.core.models import ConversationStatus
from app.storage.repository import (
    conversation_repository,
    lead_repository,
)


router = APIRouter(
    prefix="/webhook",
    tags=["Webhooks"],
)

sales_agent = create_sales_agent()


class VoiceEventRequest(BaseModel):
    """Voice webhook event payload."""

    conversation_id: str
    event: str


class VoiceSpeechRequest(BaseModel):
    """Speech webhook payload."""

    conversation_id: str
    text: str
    language: str = "en"


class WhatsAppWebhookRequest(BaseModel):
    """WhatsApp message payload."""

    phone_number: str
    message: str
    language: str = "en"


def _public_url(path: str) -> str:
    """
    Build an absolute public URL for Twilio callbacks.

    PUBLIC_BASE_URL must point to the publicly reachable Railway
    deployment when running the real Twilio integration.
    """

    base_url = settings.public_base_url.strip().rstrip("/")

    if not base_url:
        raise HTTPException(
            status_code=500,
            detail=(
                "PUBLIC_BASE_URL is not configured. "
                "Configure PUBLIC_BASE_URL before using "
                "the Twilio voice integration."
            ),
        )

    return f"{base_url}/{path.lstrip('/')}"


@router.post("/voice")
async def voice_webhook(
    payload: VoiceEventRequest,
):
    """
    Handle voice lifecycle events.

    Events:
    - answered
    - completed
    - failed

    This endpoint is kept for application-level lifecycle events.
    The real Twilio call flow uses the TwiML and speech endpoints
    below.
    """

    conversation = conversation_repository.get(
        payload.conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    if payload.event == "answered":
        conversation.status = ConversationStatus.ACTIVE

    elif payload.event == "completed":
        conversation.status = ConversationStatus.COMPLETED

    elif payload.event == "failed":
        conversation.status = ConversationStatus.FAILED

    conversation_repository.save(
        conversation
    )

    return {
        "success": True,
        "conversation_id": payload.conversation_id,
        "event": payload.event,
        "status": conversation.status.value,
    }


@router.post("/voice/speech")
async def voice_speech_webhook(
    payload: VoiceSpeechRequest,
):
    """
    Process already-transcribed speech.

    Useful for development and providers that deliver
    speech as text.
    """

    conversation = conversation_repository.get(
        payload.conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    lead = lead_repository.get(
        conversation.lead_id
    )

    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found.",
        )

    if conversation.status == ConversationStatus.CREATED:
        conversation.status = ConversationStatus.ACTIVE

    result = sales_agent.process_customer_message(
        conversation=conversation,
        lead=lead,
        customer_message=payload.text,
        language=payload.language,
    )

    lead_repository.save(lead)
    conversation_repository.save(conversation)

    return {
        "success": True,
        "conversation_id": payload.conversation_id,
        "transcript": payload.text,
        "response": result.text,
        "language": payload.language,
        "intent_score": lead.intent_score,
        "temperature": (
            lead.temperature.value
            if lead.temperature
            else None
        ),
        "high_intent": result.high_intent,
    }


@router.post("/whatsapp")
async def whatsapp_webhook(
    payload: WhatsAppWebhookRequest,
):
    """
    Process an incoming WhatsApp message.
    """

    lead = lead_repository.get_by_phone(
        payload.phone_number
    )

    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found.",
        )

    conversation = (
        conversation_repository
        .get_active_for_lead(lead.lead_id)
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Active conversation not found.",
        )

    result = sales_agent.process_customer_message(
        conversation=conversation,
        lead=lead,
        customer_message=payload.message,
        language=payload.language,
    )

    lead_repository.save(lead)
    conversation_repository.save(conversation)

    return {
        "success": True,
        "phone_number": payload.phone_number,
        "conversation_id": conversation.conversation_id,
        "response": result.text,
        "intent_score": lead.intent_score,
        "temperature": (
            lead.temperature.value
            if lead.temperature
            else None
        ),
    }


@router.get("/voice/twiml/{conversation_id}")
async def twilio_voice_twiml(
    conversation_id: str,
):
    """
    Return the initial TwiML instructions for a Twilio call.

    Twilio requests this URL when the customer answers the
    outbound call.
    """

    conversation = conversation_repository.get(
        conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    if conversation.status == ConversationStatus.CREATED:
        conversation.status = ConversationStatus.ACTIVE
        conversation_repository.save(conversation)

    speech_url = _public_url(
        f"/webhook/voice/twilio-speech/{conversation_id}"
    )

    business_name = escape(
        settings.business_name
    )

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="{speech_url}"
        method="POST"
        language="en-IN"
        speechTimeout="auto"
    >
        <Say language="en-IN">
            Hello, this is the AI sales assistant from {business_name}.
            How can I help you today?
        </Say>
    </Gather>

    <Say language="en-IN">
        I didn't hear anything. Thank you for your time.
    </Say>

    <Hangup />
</Response>
"""

    return Response(
        content=twiml,
        media_type="application/xml",
    )


@router.post(
    "/voice/twilio-speech/{conversation_id}"
)
async def twilio_speech_webhook(
    conversation_id: str,
    request: Request,
):
    """
    Receive speech recognition results from Twilio,
    process them through the sales agent, and return
    the next TwiML instructions.
    """

    conversation = conversation_repository.get(
        conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    lead = lead_repository.get(
        conversation.lead_id
    )

    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found.",
        )

    if conversation.status == ConversationStatus.CREATED:
        conversation.status = ConversationStatus.ACTIVE

    form = await request.form()

    speech_result = str(
        form.get("SpeechResult", "")
    ).strip()

    speech_url = _public_url(
        f"/webhook/voice/twilio-speech/{conversation_id}"
    )

    initial_twiml_url = _public_url(
        f"/webhook/voice/twiml/{conversation_id}"
    )

    # --------------------------------------------------------------
    # No speech detected
    # --------------------------------------------------------------

    if not speech_result:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="en-IN">
        Sorry, I didn't understand that.
        Could you please say that again?
    </Say>

    <Redirect method="GET">
        {initial_twiml_url}
    </Redirect>
</Response>
"""

        return Response(
            content=twiml,
            media_type="application/xml",
        )

    # --------------------------------------------------------------
    # Process customer speech
    # --------------------------------------------------------------

    result = sales_agent.process_customer_message(
        conversation=conversation,
        lead=lead,
        customer_message=speech_result,
        language="en",
    )

    lead_repository.save(lead)
    conversation_repository.save(conversation)

    response_text = escape(
        str(result.text)
    )

    # --------------------------------------------------------------
    # Continue the conversation
    # --------------------------------------------------------------

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="{speech_url}"
        method="POST"
        language="en-IN"
        speechTimeout="auto"
    >
        <Say language="en-IN">
            {response_text}
        </Say>
    </Gather>

    <Say language="en-IN">
        Thank you for your time. Goodbye.
    </Say>

    <Hangup />
</Response>
"""

    return Response(
        content=twiml,
        media_type="application/xml",
    )