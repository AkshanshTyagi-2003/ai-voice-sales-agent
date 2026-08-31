# whatsapp.py
"""
WhatsApp outbound action layer.

Uses Twilio's WhatsApp API. This module does not receive inbound
WhatsApp messages -- it only sends outbound messages.

This is the ONE place Twilio is called from. app/api/retell_webhook.py
used to have its own duplicate copy of this HTTP/HMAC-adjacent plumbing
(_send_whatsapp_message, _get_whatsapp_from_number, _format_phone_number,
_build_mid_call_whatsapp) inline in the webhook file. That duplicate is
removed -- the webhook now imports WhatsAppClient and the two message
builders from here.
"""

import base64
import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings
from app.core.models import Lead


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


class WhatsAppClient:
    """Outbound WhatsApp sender."""

    def __init__(self) -> None:
        self.account_sid = getattr(settings, "twilio_account_sid", None)
        self.auth_token = getattr(settings, "twilio_auth_token", None)
        self.whatsapp_from = getattr(settings, "twilio_whatsapp_from", None)

        if not self.account_sid:
            raise ValueError("TWILIO_ACCOUNT_SID is not configured.")
        if not self.auth_token:
            raise ValueError("TWILIO_AUTH_TOKEN is not configured.")
        if not self.whatsapp_from:
            raise ValueError("TWILIO_WHATSAPP_FROM is not configured.")

    def _from_header(self) -> str:
        return (
            self.whatsapp_from
            if self.whatsapp_from.startswith("whatsapp:")
            else "whatsapp:" + self.whatsapp_from
        )

    def _post(self, payload: Dict[str, str]) -> WhatsAppResult:
        url = (
            "https://api.twilio.com/2010-04-01/"
            f"Accounts/{self.account_sid}/Messages.json"
        )
        body = urlencode(payload).encode("utf-8")
        credentials = base64.b64encode(
            f"{self.account_sid}:{self.auth_token}".encode("utf-8")
        ).decode("ascii")

        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
            return WhatsAppResult(
                success=True,
                message_sid=data.get("sid"),
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

        to_number = format_phone_number(to_number)
        return self._post(
            {
                "From": self._from_header(),
                "To": f"whatsapp:{to_number}",
                "Body": body,
            }
        )

    def send_media(
        self,
        to_number: str,
        body: str,
        media_urls: List[str],
    ) -> WhatsAppResult:
        """
        Send a WhatsApp message with one or more media attachments
        (Twilio's MediaUrl parameter). Used for the final follow-up
        message (resume + architecture image).

        NOTE: Twilio's form-encoded API accepts repeated "MediaUrl"
        fields for multiple attachments; urlencode with a list of
        (key, value) tuples (rather than a dict) preserves the repeats.
        """

        to_number = format_phone_number(to_number)
        fields = [
            ("From", self._from_header()),
            ("To", f"whatsapp:{to_number}"),
            ("Body", body),
        ]
        for media_url in media_urls:
            if media_url:
                fields.append(("MediaUrl", media_url))

        url = (
            "https://api.twilio.com/2010-04-01/"
            f"Accounts/{self.account_sid}/Messages.json"
        )
        body_bytes = urlencode(fields).encode("utf-8")
        credentials = base64.b64encode(
            f"{self.account_sid}:{self.auth_token}".encode("utf-8")
        ).decode("ascii")

        request = Request(
            url,
            data=body_bytes,
            method="POST",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
            return WhatsAppResult(
                success=True,
                message_sid=data.get("sid"),
                message="WhatsApp media message sent successfully.",
                raw_response=data,
            )
        except Exception as exc:
            return WhatsAppResult(
                success=False,
                message=f"WhatsApp media send failed: {exc}",
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
    parts.append("Let me know if you have any questions or want to move forward.")
    return " ".join(parts)