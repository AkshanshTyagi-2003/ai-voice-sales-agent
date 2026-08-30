"""
Webhook endpoints for external providers.

Handles:
- Twilio voice events
- Twilio speech input
- WhatsApp messages
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.ai.agent import create_sales_agent
from app.core.models import ConversationStatus
from app.storage.repository import (
    conversation_repository,
    lead_repository,
)


router = APIRouter(prefix="/webhook", tags=["Webhooks"])

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


@router.post("/voice")
async def voice_webhook(payload: VoiceEventRequest):
    """
    Handle voice lifecycle events.

    Events:
    - answered
    - completed
    - failed
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

    conversation_repository.save(conversation)

    return {
        "success": True,
        "conversation_id": payload.conversation_id,
        "event": payload.event,
        "status": conversation.status.value,
    }


@router.post("/voice/speech")
async def voice_speech_webhook(payload: VoiceSpeechRequest):
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

    lead = lead_repository.get(conversation.lead_id)

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

    conversation = conversation_repository.get_active_for_lead(
        lead.lead_id
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
    """

    conversation = conversation_repository.get(
        conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="/webhook/voice/twilio-speech/{conversation_id}"
        method="POST"
        language="en-IN"
        speechTimeout="auto"
    >
        <Say language="en-IN">
            Hello, this is the AI sales assistant from ElevateBox.
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


@router.post("/voice/twilio-speech/{conversation_id}")
async def twilio_speech_webhook(
    conversation_id: str,
    request: Request,
):
    """
    Receive speech recognition results from Twilio.
    """

    conversation = conversation_repository.get(
        conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    lead = lead_repository.get(conversation.lead_id)

    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found.",
        )

    form = await request.form()

    speech_result = str(
        form.get("SpeechResult", "")
    ).strip()

    if not speech_result:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="en-IN">
        Sorry, I didn't understand that.
        Could you please say that again?
    </Say>

    <Redirect method="POST">
        /webhook/voice/twiml/{conversation_id}
    </Redirect>
</Response>
"""

        return Response(
            content=twiml,
            media_type="application/xml",
        )

    result = sales_agent.process_customer_message(
        conversation=conversation,
        lead=lead,
        customer_message=speech_result,
        language="en",
    )

    lead_repository.save(lead)
    conversation_repository.save(conversation)

    response_text = result.text

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
        input="speech"
        action="/webhook/voice/twilio-speech/{conversation_id}"
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