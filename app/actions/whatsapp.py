# whatsapp.py
"""
WhatsApp outbound action layer.

Uses Vonage's Messages API Sandbox for WhatsApp. This module does not
receive inbound WhatsApp messages -- it only sends outbound messages.

This is the ONE place Vonage is called from. app/api/retell_webhook.py
imports WhatsAppClient and the two message builders from here rather
than duplicating any HTTP plumbing.

NOTE ON THE SANDBOX: this was switched from Twilio to Vonage because
the Twilio trial account could not deliver messages. Vonage's Messages
API Sandbox has the exact same restriction Twilio's sandbox has: the
"to" number (including your own number, if you're testing by messaging
yourself) must first send the join keyword shown on your Vonage
dashboard's "Messages API Sandbox" page to VONAGE_WHATSAPP_FROM, once,
from that number's real WhatsApp app -- before Vonage will deliver
anything to it. If sends keep failing, check that opt-in first.
Reference: https://developer.vonage.com/en/messages/concepts/messages-api-sandbox
"""

import base64
import json
import mimetypes
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from app.core.config import settings
from app.core.models import Lead

VONAGE_SANDBOX_MESSAGES_URL = "https://messages-sandbox.nexmo.com/v1/messages"


class WhatsAppResult:
    def __init__(
        self,
        success: bool,
        message_sid: Optional[str] = None,
        message: str = "",
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message_sid = message_sid
        self.message = message
        self.raw_response = raw_response


def format_phone_number(phone_number: str) -> str:
    """
    Convert common Indian phone numbers into E.164.

    Examples:
        9536216821    -> +919536216821
        919536216821  -> +919536216821
        +919536216821 -> +919536216821
    """
    cleaned = (
        str(phone_number or "")
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("91") and len(cleaned) == 12:
        return f"+{cleaned}"
    if len(cleaned) == 10:
        return f"+91{cleaned}"
    return cleaned


def _vonage_number(phone_number: str) -> str:
    """
    Vonage's Messages API wants numbers WITHOUT a leading + or 00
    (e.g. "919536216821", not "+919536216821").
    https://developer.vonage.com/en/messages/concepts/messages-api-sandbox
    """
    e164 = format_phone_number(phone_number)
    return e164.lstrip("+")


def _guess_media_message_type(media_url: str) -> str:
    """
    Vonage's Messages API needs a distinct message_type per media kind
    (image / file / video / audio) -- unlike Twilio's single MediaUrl
    parameter that accepts anything. Guess from the URL's extension.
    """
    guessed_type, _ = mimetypes.guess_type(media_url)
    if guessed_type:
        if guessed_type.startswith("image/"):
            return "image"
        if guessed_type.startswith("video/"):
            return "video"
        if guessed_type.startswith("audio/"):
            return "audio"
    return "file"


class WhatsAppClient:
    """Outbound WhatsApp sender (Vonage Messages API Sandbox)."""

    def __init__(self) -> None:
        self.api_key = getattr(settings, "vonage_api_key", None)
        self.api_secret = getattr(settings, "vonage_api_secret", None)
        self.whatsapp_from = getattr(settings, "vonage_whatsapp_from", None)

        if not self.api_key:
            raise ValueError("VONAGE_API_KEY is not configured.")
        if not self.api_secret:
            raise ValueError("VONAGE_API_SECRET is not configured.")
        if not self.whatsapp_from:
            raise ValueError("VONAGE_WHATSAPP_FROM is not configured.")

    def _auth_header(self) -> str:
        credentials = base64.b64encode(
            f"{self.api_key}:{self.api_secret}".encode("utf-8")
        ).decode("ascii")
        return f"Basic {credentials}"

    def _post(self, payload: Dict[str, Any]) -> WhatsAppResult:
        body = json.dumps(payload).encode("utf-8")

        request = Request(
            VONAGE_SANDBOX_MESSAGES_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
            return WhatsAppResult(
                success=True,
                message_sid=data.get("message_uuid"),
                message="WhatsApp sent successfully.",
                raw_response=data,
            )
        except Exception as exc:
            return WhatsAppResult(
                success=False,
                message=f"WhatsApp send failed: {exc}",
            )

    def send_text(self, to_number: str, body: str) -> WhatsAppResult:
        """Send a plain WhatsApp text message."""

        to_number = _vonage_number(to_number)
        return self._post(
            {
                "to": to_number,
                "from": self.whatsapp_from,
                "channel": "whatsapp",
                "message_type": "text",
                "text": body,
            }
        )

    def send_media(
        self,
        to_number: str,
        body: str,
        media_urls: List[str],
    ) -> WhatsAppResult:
        """
        Send a WhatsApp message with one or more media attachments.

        Unlike Twilio (one call, repeated MediaUrl fields), Vonage's
        Messages API requires ONE call per message, and each media
        message needs a specific message_type (image / file / video /
        audio) rather than a generic attachment field. So this sends
        the text body first, then one follow-up call per media URL,
        and reports success only if every one of those sends succeeded
        (the caller -- retell_webhook.py -- only marks
        whatsapp_sent_final once this returns success=True, so a
        partial failure here should NOT be reported as a full send).
        """

        to_number = _vonage_number(to_number)
        results: List[WhatsAppResult] = []

        if body:
            results.append(
                self._post(
                    {
                        "to": to_number,
                        "from": self.whatsapp_from,
                        "channel": "whatsapp",
                        "message_type": "text",
                        "text": body,
                    }
                )
            )

        for media_url in media_urls:
            if not media_url:
                continue
            media_type = _guess_media_message_type(media_url)
            payload: Dict[str, Any] = {
                "to": to_number,
                "from": self.whatsapp_from,
                "channel": "whatsapp",
                "message_type": media_type,
                media_type: {"url": media_url},
            }
            results.append(self._post(payload))

        all_succeeded = bool(results) and all(r.success for r in results)
        failures = [r.message for r in results if not r.success]

        return WhatsAppResult(
            success=all_succeeded,
            message_sid=(
                results[0].message_sid if results and results[0].success else None
            ),
            message=(
                "WhatsApp media message sent successfully."
                if all_succeeded
                else "WhatsApp media send failed: " + "; ".join(failures)
            ),
            raw_response={
                "parts": [r.raw_response for r in results],
            },
        )


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _qualification_lines(lead: Lead) -> List[str]:
    qualification = lead.qualification
    lines: List[str] = []

    if qualification.business_description:
        lines.append(
            f"I noted that your business is {qualification.business_description}."
        )
    if qualification.products:
        lines.append(
            f"The product/service discussed was {qualification.products}."
        )
    if qualification.product_count:
        lines.append(f"You mentioned around {qualification.product_count} products.")
    if qualification.budget:
        lines.append(f"Your budget is around {qualification.budget}.")
    if qualification.timeline:
        lines.append(f"Your target timeline is {qualification.timeline}.")
    if qualification.features:
        lines.append(
            "The key features you mentioned are "
            + ", ".join(qualification.features)
            + "."
        )
    return lines


def build_mid_call_message(lead: Lead) -> str:
    """
    Build the HOT-lead WhatsApp message sent WHILE the call is still
    active (triggered from transcript_updated once lead.intent_score
    crosses 0.70).
    """

    parts = ["Hi! Thanks for speaking with me."]
    parts.extend(_qualification_lines(lead))
    parts.append(
        "I've sent this while we're still connected so you have the "
        "details handy."
    )
    return " ".join(parts)


def build_final_followup_message(lead: Lead) -> str:
    """
    Build the post-call follow-up WhatsApp message, sent once the call
    has ended (call_ended / call_analyzed). Recaps what was discussed
    and points to the attached resume + architecture image, which are
    sent as media attachments alongside this text via
    WhatsAppClient.send_media -- not embedded in the body.
    """

    parts = ["Thanks again for the call!"]
    parts.extend(_qualification_lines(lead))
    parts.append(
        "I've attached our resume and a sample architecture overview "
        "for you to look through."
    )

    agent_number = (settings.agent_phone_number or "").strip()
    if agent_number:
        # Requirement: "Your mobile number, clearly visible, so I can
        # call you back without hunting for it."
        parts.append(f"You can reach me directly on {agent_number}.")

    parts.append("Let me know if you have any questions or want to move forward.")
    return " ".join(parts)