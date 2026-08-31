"""
Retell webhook integration.

Receives live Retell call events and connects them to the existing
qualification / intent / classification pipeline.

Supported Retell events:
- call_started
- transcript_updated
- call_ended
- call_analyzed

Important:
- transcript_updated is used for MID-CALL intent detection.
- HOT leads can trigger WhatsApp while the call is still active.
- call_ended / call_analyzed send the post-call follow-up (resume +
  architecture image as media), exactly once, via
  app.actions.whatsapp.build_final_followup_message.
- This endpoint never creates a Retell call.
- Webhook signatures are verified using Retell's documented
  timestamp + HMAC-SHA256 scheme.

CHANGE FROM THE PREVIOUS VERSION:
All outbound WhatsApp sending (_send_whatsapp_message,
_get_whatsapp_from_number, _format_phone_number, and the message body
builder) used to live here as a duplicate of app/actions/whatsapp.py.
That duplicate is gone -- this file now imports WhatsAppClient and both
message builders from app.actions.whatsapp, which is the single place
Twilio is called from.
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request as FastAPIRequest

from app.actions.whatsapp import (
    WhatsAppClient,
    build_final_followup_message,
    build_mid_call_message,
)
from app.ai.agent import create_sales_agent
from app.core.config import settings
from app.core.models import ConversationStatus, MessageRole
from app.storage.repository import conversation_repository, lead_repository

router = APIRouter(
    prefix="/webhook",
    tags=["Retell"],
)

sales_agent = create_sales_agent()


# ============================================================================
# Retell webhook signature verification
# ============================================================================
def _verify_retell_signature(
    raw_body: bytes,
    signature: Optional[str],
) -> bool:
    """
    Verify a Retell webhook signature.

    Retell signature format:
        v=<timestamp>,d=<hex_digest>

    Retell calculates:
        HMAC-SHA256(raw_body + timestamp, RETELL_API_KEY)

    The timestamp must be within five minutes of the current time.

    IMPORTANT:
    The raw request body must be used. Do not re-serialize parsed JSON
    before verification.
    """
    if not signature:
        return False

    api_key = (settings.retell_api_key or "").strip()
    if not api_key:
        return False

    try:
        parts: Dict[str, str] = {}
        for item in signature.split(","):
            key, separator, value = item.partition("=")
            if not separator:
                continue
            parts[key.strip()] = value.strip()

        timestamp_text = parts.get("v")
        received_digest = parts.get("d")

        if not timestamp_text:
            return False
        if not received_digest:
            return False

        timestamp = int(timestamp_text)
    except (ValueError, TypeError):
        return False

    # ------------------------------------------------------------------
    # Replay protection.
    #
    # Retell documents a five-minute timestamp window.
    # ------------------------------------------------------------------
    current_timestamp = int(time.time() * 1000)
    if abs(current_timestamp - timestamp) > 5 * 60 * 1000:
        return False

    # ------------------------------------------------------------------
    # Calculate expected HMAC.
    # ------------------------------------------------------------------
    raw_body_text = raw_body.decode("utf-8")
    signed_payload = raw_body_text + timestamp_text

    expected_digest = hmac.new(
        api_key.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_digest, received_digest)


# ============================================================================
# Retell payload helpers
# ============================================================================
def _get_conversation_from_call(call: Dict[str, Any]):
    """
    Resolve our internal conversation using Retell call metadata.

    Our outbound Retell call stores:
        metadata:
          conversation_id: ...

    Retell returns that metadata in webhook payloads.
    """
    metadata = call.get("metadata") or {}
    conversation_id = metadata.get("conversation_id")
    if not conversation_id:
        return None
    return conversation_repository.get(str(conversation_id))


def _extract_user_turns(
    transcript_object: Optional[List[Dict[str, Any]]],
) -> List[str]:
    """
    Extract customer/user utterances from Retell's transcript_object.

    Retell transcript entries contain roles such as:
        user
        agent

    Only user turns are passed into our sales-agent pipeline.
    """
    if not transcript_object:
        return []

    turns: List[str] = []
    for item in transcript_object:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role", "")).strip().lower()
        if role != "user":
            continue

        content = item.get("content")
        if isinstance(content, list):
            # Some transcript formats may provide content as structured
            # items. Convert them safely.
            content = " ".join(
                str(part) for part in content if part is not None
            )
        content = str(content or "").strip()
        if content:
            turns.append(content)

    return turns


def _get_stored_customer_turns(conversation) -> List[str]:
    """
    Return customer messages already persisted in our conversation.

    This lets us process only the newly arrived Retell transcript turns
    instead of sending the same customer sentence through the AI pipeline
    repeatedly.
    """
    turns: List[str] = []
    for message in conversation.messages:
        if message.role == MessageRole.CUSTOMER:
            text = str(message.text or "").strip()
            if text:
                turns.append(text)
    return turns


def _extract_new_user_turns(
    conversation,
    transcript_object: List[Dict[str, Any]],
) -> List[str]:
    """
    Return only customer transcript turns that have not already been
    persisted.

    Retell sends an accumulated transcript in transcript_updated events,
    so processing the entire transcript on every event would duplicate
    messages.
    """
    user_turns = _extract_user_turns(transcript_object)
    if not user_turns:
        return []

    stored_turns = _get_stored_customer_turns(conversation)
    stored_count = len(stored_turns)

    if stored_count == 0:
        return user_turns

    if len(user_turns) <= stored_count:
        return []

    return user_turns[stored_count:]


# ============================================================================
# Conversation processing
# ============================================================================
def _process_new_user_turns(
    conversation,
    lead,
    transcript_object: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Process newly arrived customer turns.

    Each new customer turn is sent through the existing SalesAgent.
    """
    new_turns = _extract_new_user_turns(conversation, transcript_object)

    if not new_turns:
        return {
            "processed": 0,
            "high_intent": bool(lead.intent_score >= 0.70),
        }

    high_intent = False
    for customer_message in new_turns:
        result = sales_agent.process_customer_message(
            conversation=conversation,
            lead=lead,
            customer_message=customer_message,
            language=lead.language or "en",
        )

        # SalesAgent returns an AIResponse whose `intent` field is the
        # IntentResult produced by app.ai.intent.analyze_conversation.
        # `high_intent` lives on that IntentResult, not on AIResponse
        # itself -- reading it off `result` directly always evaluated to
        # False. Read it off `result.intent` instead.
        if getattr(result.intent, "high_intent", False):
            high_intent = True

    lead_repository.save(lead)
    conversation_repository.save(conversation)

    return {
        "processed": len(new_turns),
        "high_intent": high_intent,
    }


# ============================================================================
# WhatsApp (delegates entirely to app.actions.whatsapp)
# ============================================================================
def _send_mid_call_whatsapp(lead, conversation) -> Dict[str, Any]:
    """
    Send the HOT-lead WhatsApp exactly once.

    The conversation flag prevents duplicate sends when Retell sends
    multiple transcript_updated events or retries a webhook.
    """
    if conversation.whatsapp_sent_mid_call:
        return {"sent": False, "reason": "already_sent"}

    try:
        client = WhatsAppClient()
    except ValueError as exc:
        return {"sent": False, "error": str(exc)}

    message = build_mid_call_message(lead)
    result = client.send_text(to_number=lead.phone_number, body=message)

    if result.success:
        conversation.whatsapp_sent_mid_call = True
        conversation_repository.save(conversation)
        return {"sent": True, "message_sid": result.message_sid}

    return {"sent": False, "error": result.message}


def _send_final_followup_whatsapp(lead, conversation) -> Dict[str, Any]:
    """
    Send the post-call follow-up WhatsApp exactly once, with the resume
    and architecture-overview image attached as media.

    NOTE: this reads conversation.whatsapp_sent_final and lead's resume /
    architecture-image URLs. Both need to exist for this to compile and
    run against the real models -- see the note at the bottom of this
    response about the two small additions still needed in
    app/core/models.py (a `whatsapp_sent_final` flag on Conversation) and
    app/core/config.py (RESUME_MEDIA_URL / ARCHITECTURE_IMAGE_URL
    settings), since neither existed in the files you pasted.
    """
    if getattr(conversation, "whatsapp_sent_final", False):
        return {"sent": False, "reason": "already_sent"}

    try:
        client = WhatsAppClient()
    except ValueError as exc:
        return {"sent": False, "error": str(exc)}

    resume_url = (getattr(settings, "resume_media_url", "") or "").strip()
    architecture_url = (
        getattr(settings, "architecture_image_url", "") or ""
    ).strip()
    media_urls = [url for url in (resume_url, architecture_url) if url]

    message = build_final_followup_message(lead)

    if media_urls:
        result = client.send_media(
            to_number=lead.phone_number,
            body=message,
            media_urls=media_urls,
        )
    else:
        # Media URLs aren't configured -- still send the text follow-up
        # rather than silently dropping it.
        result = client.send_text(to_number=lead.phone_number, body=message)

    if result.success:
        conversation.whatsapp_sent_final = True
        conversation_repository.save(conversation)
        return {"sent": True, "message_sid": result.message_sid}

    return {"sent": False, "error": result.message}


# ============================================================================
# Timestamp helper
# ============================================================================
def _timestamp_to_datetime(timestamp_ms: Any) -> Optional[datetime]:
    """Convert a Retell millisecond timestamp to a timezone-aware datetime."""
    if timestamp_ms is None:
        return None
    try:
        timestamp = float(timestamp_ms)
        return datetime.fromtimestamp(timestamp / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


# ============================================================================
# Retell webhook endpoint
# ============================================================================
@router.post("/retell")
async def retell_webhook(
    request: FastAPIRequest,
    x_retell_signature: Optional[str] = Header(
        default=None,
        alias="X-Retell-Signature",
    ),
):
    """
    Receive and process Retell webhook events.

    Retell expects a successful 2xx response. The endpoint therefore
    returns quickly after processing the required event.
    """
    raw_body = await request.body()

    if not _verify_retell_signature(
        raw_body=raw_body,
        signature=x_retell_signature,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid Retell webhook signature.",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    event = payload.get("event")
    call = payload.get("call") or {}

    if not event:
        return {"success": True, "ignored": True, "reason": "Missing event."}

    conversation = _get_conversation_from_call(call)

    if conversation is None:
        return {
            "success": True,
            "ignored": True,
            "event": event,
            "reason": "Conversation not found.",
        }

    lead = lead_repository.get(conversation.lead_id)
    if lead is None:
        return {
            "success": True,
            "ignored": True,
            "event": event,
            "conversation_id": conversation.conversation_id,
            "reason": "Lead not found.",
        }

    # ==================================================================
    # CALL STARTED
    # ==================================================================
    if event == "call_started":
        conversation.status = ConversationStatus.ACTIVE
        conversation_repository.save(conversation)
        return {
            "success": True,
            "event": event,
            "conversation_id": conversation.conversation_id,
            "status": conversation.status.value,
        }

    # ==================================================================
    # LIVE TRANSCRIPT
    # ==================================================================
    if event == "transcript_updated":
        transcript_object = call.get("transcript_object") or []

        processing_result = _process_new_user_turns(
            conversation=conversation,
            lead=lead,
            transcript_object=transcript_object,
        )

        whatsapp_result = {"sent": False, "reason": "not_high_intent"}

        if (
            lead.intent_score >= 0.70
            and not conversation.whatsapp_sent_mid_call
        ):
            whatsapp_result = _send_mid_call_whatsapp(
                lead=lead,
                conversation=conversation,
            )

        return {
            "success": True,
            "event": event,
            "conversation_id": conversation.conversation_id,
            "processed_turns": processing_result["processed"],
            "high_intent": processing_result["high_intent"],
            "intent_score": lead.intent_score,
            "temperature": (
                lead.temperature.value if lead.temperature else None
            ),
            "whatsapp": whatsapp_result,
        }

    # ==================================================================
    # CALL ENDED
    # ==================================================================
    if event == "call_ended":
        conversation.status = ConversationStatus.COMPLETED
        ended_at = _timestamp_to_datetime(call.get("end_timestamp"))
        if ended_at is not None:
            conversation.ended_at = ended_at
        conversation_repository.save(conversation)

        whatsapp_result = _send_final_followup_whatsapp(
            lead=lead,
            conversation=conversation,
        )

        return {
            "success": True,
            "event": event,
            "conversation_id": conversation.conversation_id,
            "status": conversation.status.value,
            "disconnection_reason": call.get("disconnection_reason"),
            "whatsapp_final_followup": whatsapp_result,
        }

    # ==================================================================
    # CALL ANALYZED
    # ==================================================================
    if event == "call_analyzed":
        conversation.status = ConversationStatus.COMPLETED
        ended_at = _timestamp_to_datetime(call.get("end_timestamp"))
        if ended_at is not None:
            conversation.ended_at = ended_at
        conversation_repository.save(conversation)

        # call_analyzed can arrive instead of / in addition to
        # call_ended depending on your Retell webhook subscription --
        # _send_final_followup_whatsapp is idempotent via
        # conversation.whatsapp_sent_final, so it's safe to attempt here
        # too rather than assuming call_ended already fired.
        whatsapp_result = _send_final_followup_whatsapp(
            lead=lead,
            conversation=conversation,
        )

        return {
            "success": True,
            "event": event,
            "conversation_id": conversation.conversation_id,
            "intent_score": lead.intent_score,
            "temperature": (
                lead.temperature.value if lead.temperature else None
            ),
            "call_analysis": call.get("call_analysis"),
            "whatsapp_final_followup": whatsapp_result,
        }

    # ==================================================================
    # UNKNOWN / FUTURE EVENT
    # ==================================================================
    return {
        "success": True,
        "event": event,
        "ignored": True,
        "reason": "Event is not handled by this application.",
    }