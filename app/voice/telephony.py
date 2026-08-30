"""
Telephony provider abstraction.

The application can use either the mock provider for local testing
or Twilio for real outbound phone calls.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from app.core.config import settings
from app.core.models import ConversationStatus


@dataclass
class CallResult:
    """Result returned after attempting to create a phone call."""

    success: bool
    call_id: Optional[str]
    status: ConversationStatus
    message: str
    raw_response: Optional[Dict[str, Any]] = None


class TelephonyProvider(Protocol):
    """Interface implemented by telephony providers."""

    def make_call(
        self,
        conversation_id: str,
        phone_number: str,
    ) -> CallResult:
        """Create an outbound call."""
        ...


class MockTelephonyProvider:
    """Mock provider used for local development and testing."""

    def __init__(self) -> None:
        self.call_counter = 0

    def make_call(
        self,
        conversation_id: str,
        phone_number: str,
    ) -> CallResult:
        """Create a simulated outbound call."""

        self.call_counter += 1

        call_id = f"mock-call-{self.call_counter}"

        return CallResult(
            success=True,
            call_id=call_id,
            status=ConversationStatus.RINGING,
            message="Mock call created successfully.",
            raw_response={
                "call_id": call_id,
                "phone_number": phone_number,
                "conversation_id": conversation_id,
            },
        )


class TwilioTelephonyProvider:
    """Twilio implementation for real outbound phone calls."""

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> None:
        self.account_sid = (
            account_sid or settings.twilio_account_sid
        )
        self.auth_token = (
            auth_token or settings.twilio_auth_token
        )
        self.phone_number = (
            phone_number or settings.twilio_phone_number
        )

        if not self.account_sid:
            raise ValueError(
                "TWILIO_ACCOUNT_SID is not configured."
            )

        if not self.auth_token:
            raise ValueError(
                "TWILIO_AUTH_TOKEN is not configured."
            )

        if not self.phone_number:
            raise ValueError(
                "TWILIO_PHONE_NUMBER is not configured."
            )

    def make_call(
        self,
        conversation_id: str,
        phone_number: str,
    ) -> CallResult:
        """
        Create a real outbound Twilio call.

        The current implementation uses Twilio's Python SDK.
        """

        try:
            from twilio.rest import Client
        except ImportError as exc:
            raise RuntimeError(
                "Twilio SDK is not installed. "
                "Run: pip install twilio"
            ) from exc

        try:
            client = Client(
                self.account_sid,
                self.auth_token,
            )

            call = client.calls.create(
                to=self._format_phone_number(phone_number),
                from_=self._format_phone_number(
                    self.phone_number
                ),
                url=self._build_voice_webhook_url(
                    conversation_id
                ),
            )

            return CallResult(
                success=True,
                call_id=call.sid,
                status=ConversationStatus.RINGING,
                message="Twilio call created successfully.",
                raw_response={
                    "call_sid": call.sid,
                    "status": call.status,
                    "conversation_id": conversation_id,
                    "phone_number": phone_number,
                },
            )

        except Exception as exc:
            return CallResult(
                success=False,
                call_id=None,
                status=ConversationStatus.CREATED,
                message=f"Twilio call failed: {exc}",
                raw_response={
                    "conversation_id": conversation_id,
                    "phone_number": phone_number,
                },
            )

    @staticmethod
    def _format_phone_number(phone_number: str) -> str:
        """Convert common Indian 10-digit numbers to E.164."""

        cleaned = (
            phone_number
            .strip()
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )

        if cleaned.startswith("+"):
            return cleaned

        if cleaned.startswith("91") and len(cleaned) == 12:
            return f"+{cleaned}"

        if len(cleaned) == 10:
            return f"+91{cleaned}"

        return cleaned

    @staticmethod
    def _build_voice_webhook_url(
        conversation_id: str,
    ) -> str:
        """
        Build the public webhook URL Twilio calls when the
        customer answers.
        """

        base_url = settings.public_base_url.rstrip("/")

        if not base_url:
            raise ValueError(
                "PUBLIC_BASE_URL is required for real Twilio calls."
            )

        return (
            f"{base_url}/webhook/voice"
            f"?conversation_id={conversation_id}"
        )


class TelephonyClient:
    """High-level telephony client."""

    def __init__(
        self,
        provider: TelephonyProvider,
    ) -> None:
        self.provider = provider

    def make_outbound_call(
        self,
        conversation_id: str,
        phone_number: str,
    ) -> CallResult:
        """Create an outbound call through the configured provider."""

        if not phone_number:
            return CallResult(
                success=False,
                call_id=None,
                status=ConversationStatus.CREATED,
                message="Phone number is required.",
            )

        return self.provider.make_call(
            conversation_id=conversation_id,
            phone_number=phone_number,
        )