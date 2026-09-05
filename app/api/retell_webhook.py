# retell_webhook.py
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
  architecture image as media, for HOT/WARM/COLD leads -- see
  _send_final_followup_whatsapp), exactly once, via
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
Vonage is called from.

CHANGE (WhatsApp content/media fix): _send_final_followup_whatsapp now
resolves the actual architecture/resume media (via
app.actions.whatsapp.resolve_final_followup_media) and attaches it for
the final follow-up regardless of lead temperature (HOT, WARM, and
COLD all now get the architecture image + resume in the final
follow-up, per the assignment's "final WhatsApp must include the
contact number, architecture image and resume" requirement -- media is
still never attached mid-call), passing explicit Vonage message types
("image"/"file") since the assignment's Google Drive share links carry
no file extension for WhatsAppClient to auto-guess from. It also tells
build_final_followup_message exactly what was actually attached (so
the message body can never claim a resume/architecture was sent when
it wasn't) and passes the conversation through so the message can
acknowledge a requested callback. See app/actions/whatsapp.py for the
full explanation of each fix.

"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request as FastAPIRequest

from app.actions.callback import CallbackManager, detect_callback_request
from app.actions.whatsapp import (
    WhatsAppClient,
    build_final_followup_message,
    build_mid_call_message,
    resolve_final_followup_media,
)
from app.ai.agent import create_sales_agent
from app.core.config import settings
from app.core.models import ConversationStatus, MessageRole
from app.storage.repository import conversation_repository, lead_repository
from app.utils.helpers import detect_language

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
            "callback_booked": False,
            "callback_scheduled_for": None,
        }

    high_intent = False
    callback_result = None
    for customer_message in new_turns:
        # EXTENSION (multilingual support): update the lead's recorded
        # language from this turn before processing it, so downstream
        # WhatsApp copy (app.actions.whatsapp) follows whichever
        # language the customer is CURRENTLY speaking -- per doc2
        # section 1 ("If the customer switches language: follow the
        # customer's current language preference naturally... Do NOT
        # repeatedly ask"). detect_language() returns None for
        # ambiguous turns (a bare "yes", a number, a name), in which
        # case we deliberately keep whatever language was already
        # recorded rather than overwrite it.
        detected_language = detect_language(customer_message)
        if detected_language is not None:
            lead.language = detected_language
            conversation.language = detected_language

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

        # Requirement #7/#8: "If I say call me back tomorrow morning,
        # your system understands it and books the callback itself."
        # This previously only existed as a manual POST
        # /scheduler/callback endpoint -- nothing on the live-call path
        # ever looked at what the customer actually said and booked a
        # callback from it. Fire this at most once per conversation.
        if not conversation.callback_requested:
            requested_time_text = detect_callback_request(customer_message)
            if requested_time_text:
                callback_result = CallbackManager().request_callback(
                    lead=lead,
                    requested_time_text=requested_time_text,
                )
                if callback_result.success:
                    conversation.callback_requested = True

    lead_repository.save(lead)
    conversation_repository.save(conversation)

    return {
        "processed": len(new_turns),
        "high_intent": high_intent,
        "callback_booked": bool(
            callback_result is not None and callback_result.success
        ),
        "callback_scheduled_for": (
            callback_result.callback.scheduled_for.isoformat()
            if callback_result
            and callback_result.success
            and callback_result.callback
            and callback_result.callback.scheduled_for
            else None
        ),
    }


# ============================================================================
# WhatsApp (delegates entirely to app.actions.whatsapp)
# ============================================================================
def _send_mid_call_whatsapp(lead, conversation) -> Dict[str, Any]:
    """
    Send the HOT-lead WhatsApp exactly once.

    In development, this is a dry run: the exact message that would be
    sent is returned without contacting Vonage.

    In production, the existing Vonage sending behavior is unchanged.

    UNCHANGED: mid-call WhatsApp remains HOT-only and text-only (no
    architecture/resume media mid-call -- that stays a final-follow-up
    only behavior, see _send_final_followup_whatsapp).
    """
    if conversation.whatsapp_sent_mid_call:
        return {"sent": False, "reason": "already_sent"}

    message = build_mid_call_message(lead)

    # Local development safety: show exactly what would be sent,
    # but never contact Vonage.
    if settings.environment != "production":
        return {
            "sent": False,
            "dry_run": True,
            "message": message,
        }

    try:
        client = WhatsAppClient()
    except ValueError as exc:
        return {"sent": False, "error": str(exc)}

    result = client.send_text(
        to_number=lead.phone_number,
        body=message,
    )

    if result.success:
        conversation.whatsapp_sent_mid_call = True
        conversation_repository.save(conversation)
        return {"sent": True, "message_sid": result.message_sid}

    return {"sent": False, "error": result.message}


def _send_final_followup_whatsapp(lead, conversation) -> Dict[str, Any]:
    """
    Send the post-call follow-up WhatsApp exactly once.

    In development, this is a dry run: the exact final message and
    the media that would actually be attached are returned without
    contacting Vonage.

    In production, the existing Vonage sending behavior is unchanged.

    CHANGE (assignment requirement): the architecture overview PNG and
    resume PDF are now resolved and attached for the final follow-up
    regardless of lead temperature -- HOT, WARM, and COLD all get both
    attachments in the final WhatsApp (previously this was gated to
    HOT leads only). This does not affect the mid-call WhatsApp, which
    remains HOT-only and text-only via _send_mid_call_whatsapp above.
    build_final_followup_message is still told exactly what was
    actually attached (has_architecture_media / has_resume_media) so
    the message body can never claim an attachment that wasn't sent
    (doc2 Problem 2), and the conversation is still passed through so
    the message can acknowledge a requested callback.
    """
    if getattr(conversation, "whatsapp_sent_final", False):
        return {"sent": False, "reason": "already_sent"}

    media_urls: List[str] = []
    media_types: List[str] = []
    has_architecture_media = False
    has_resume_media = False

    media = resolve_final_followup_media()
    architecture_url = (media.get("architecture_url") or "").strip()
    resume_url = (media.get("resume_url") or "").strip()

    if architecture_url:
        media_urls.append(architecture_url)
        media_types.append("image")  # architecture overview is PNG
        has_architecture_media = True

    if resume_url:
        media_urls.append(resume_url)
        media_types.append("file")  # resume is PDF
        has_resume_media = True

    message = build_final_followup_message(
        lead,
        conversation=conversation,
        has_architecture_media=has_architecture_media,
        has_resume_media=has_resume_media,
    )

    # Local development safety: show exactly what would be sent,
    # but never contact Vonage.
    if settings.environment != "production":
        return {
            "sent": False,
            "dry_run": True,
            "message": message,
            "media_urls": media_urls,
        }

    try:
        client = WhatsAppClient()
    except ValueError as exc:
        return {"sent": False, "error": str(exc)}

    if media_urls:
        result = client.send_media(
            to_number=lead.phone_number,
            body=message,
            media_urls=media_urls,
            media_types=media_types,
        )
    else:
        # Media URLs aren't attached for this lead -- still send the
        # text follow-up.
        result = client.send_text(
            to_number=lead.phone_number,
            body=message,
        )

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
            lead.temperature is not None
            
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
            "callback_booked": processing_result["callback_booked"],
            "callback_scheduled_for": processing_result["callback_scheduled_for"],
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