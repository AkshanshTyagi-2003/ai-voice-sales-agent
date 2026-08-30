"""
Telephony provider abstraction.

Providers:
- Mock provider for local testing
- Retell for real AI voice calls
- Twilio retained temporarily for backward compatibility

IMPORTANT:
Verification methods in this file are READ-ONLY.
They do not create phone calls and therefore do not consume
voice-call minutes.
"""

from dataclasses import dataclass
import json
from typing import Any, Dict, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.core.config import settings
from app.core.models import ConversationStatus


RETELL_API_BASE_URL = "https://api.retellai.com"


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


class RetellTelephonyProvider:
    """
    Retell implementation for AI voice calls.

    Verification is strictly read-only.

    A real call is created ONLY by make_call().
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        phone_number: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> None:

        self.api_key = (
            api_key
            or settings.retell_api_key
        )

        self.phone_number = (
            phone_number
            or settings.retell_phone_number
        )

        self.agent_id = (
            agent_id
            or settings.retell_agent_id
        )

        if not self.api_key:
            raise ValueError(
                "RETELL_API_KEY is not configured."
            )

        if not self.phone_number:
            raise ValueError(
                "RETELL_PHONE_NUMBER is not configured."
            )

        if not self.agent_id:
            raise ValueError(
                "RETELL_AGENT_ID is not configured."
            )

    # ------------------------------------------------------------------
    # Retell HTTP helper
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to Retell.

        This method itself does not create a call.
        The caller determines which Retell endpoint is used.
        """

        url = f"{RETELL_API_BASE_URL}{path}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body = None

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = Request(
            url=url,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(
                request,
                timeout=15,
            ) as response:

                response_body = (
                    response.read()
                    .decode("utf-8")
                )

                if not response_body:
                    return {}

                return json.loads(response_body)

        except HTTPError as exc:

            error_body = ""

            try:
                error_body = (
                    exc.read()
                    .decode("utf-8")
                )
            except Exception:
                pass

            raise RuntimeError(
                f"Retell API HTTP {exc.code}: "
                f"{error_body or exc.reason}"
            ) from exc

        except URLError as exc:

            raise RuntimeError(
                f"Unable to reach Retell API: {exc.reason}"
            ) from exc

    # ------------------------------------------------------------------
    # Read-only verification
    # ------------------------------------------------------------------

    def verify_configuration(self) -> Dict[str, Any]:
        """
        Verify Retell configuration without creating a call.

        Checks:

        1. API authentication
        2. Agent exists
        3. Published agent version exists
        4. Published version belongs to configured agent
        5. Configured phone number exists
        6. Phone number matches configuration
        7. Phone number is a Retell-managed voice number

        NO CALL IS CREATED.
        """

        # --------------------------------------------------------------
        # 1. Get all agent versions
        # --------------------------------------------------------------

        versions_response = self._request(
            "GET",
            f"/list-agent-versions/{self.agent_id}",
        )

        versions = (
            versions_response.get("items")
            or []
        )

        if not versions:
            raise RuntimeError(
                "Retell returned no versions for "
                f"agent {self.agent_id}."
            )

        published_versions = [
            version
            for version in versions
            if version.get("is_published") is True
        ]

        if not published_versions:
            raise RuntimeError(
                "The configured Retell agent has no "
                "published version."
            )

        # Use the newest published version.
        published_versions.sort(
            key=lambda item: item.get("version", -1),
            reverse=True,
        )

        published_version = published_versions[0]

        published_version_number = (
            published_version.get("version")
        )

        # --------------------------------------------------------------
        # 2. Get the actual published agent version
        # --------------------------------------------------------------

        agent = self._request(
            "GET",
            (
                f"/get-agent/{self.agent_id}"
                f"?version={published_version_number}"
            ),
        )

        returned_agent_id = agent.get(
            "agent_id"
        )

        if returned_agent_id != self.agent_id:
            raise RuntimeError(
                "Retell returned an unexpected agent ID. "
                f"Expected {self.agent_id}, "
                f"got {returned_agent_id}."
            )

        if agent.get("is_published") is not True:
            raise RuntimeError(
                "The selected Retell agent version "
                "is not published."
            )

        # --------------------------------------------------------------
        # 3. Get all phone numbers
        # --------------------------------------------------------------

        phone_response = self._request(
            "GET",
            "/v2/list-phone-numbers",
        )

        phone_items = (
            phone_response.get("items")
            or []
        )

        configured_phone = next(
            (
                item
                for item in phone_items
                if item.get("phone_number")
                == self.phone_number
            ),
            None,
        )

        if configured_phone is None:
            raise RuntimeError(
                "Configured Retell phone number was not found: "
                f"{self.phone_number}"
            )

        returned_phone_number = (
            configured_phone.get("phone_number")
        )

        phone_matches = (
            returned_phone_number
            == self.phone_number
        )

        phone_type = configured_phone.get(
            "phone_number_type"
        )

        country_code = configured_phone.get(
            "country_code"
        )

        # --------------------------------------------------------------
        # 4. Build verification result
        # --------------------------------------------------------------

        configuration = {
            "api_key_valid": True,
            "agent_exists": True,
            "agent_id_matches": (
                returned_agent_id
                == self.agent_id
            ),
            "published_version_exists": True,
            "published_version": (
                published_version_number
            ),
            "agent_is_published": (
                agent.get("is_published") is True
            ),
            "agent_channel_is_voice": (
                agent.get("channel") == "voice"
            ),
            "phone_exists": True,
            "phone_matches_config": phone_matches,
            "phone_type": phone_type,
            "phone_country": country_code,
        }

        ready_for_call = all(
            [
                configuration["api_key_valid"],
                configuration["agent_exists"],
                configuration["agent_id_matches"],
                configuration["published_version_exists"],
                configuration["agent_is_published"],
                configuration["agent_channel_is_voice"],
                configuration["phone_exists"],
                configuration["phone_matches_config"],
            ]
        )

        return {
            "retell_api": True,

            "agent": {
                "agent_id": returned_agent_id,
                "agent_name": agent.get(
                    "agent_name"
                ),
                "channel": agent.get(
                    "channel"
                ),
                "published": agent.get(
                    "is_published"
                ),
                "published_version": (
                    published_version_number
                ),
                "voice_id": agent.get(
                    "voice_id"
                ),
                "language": agent.get(
                    "language"
                ),
            },

            "phone_number": {
                "phone_number": returned_phone_number,
                "phone_number_type": phone_type,
                "country_code": country_code,
                "phone_number_pretty": (
                    configured_phone.get(
                        "phone_number_pretty"
                    )
                ),
            },

            "configuration": configuration,

            # This is deliberately ALWAYS false here.
            # verify_configuration() never creates calls.
            "call_created": False,

            "ready_for_call": ready_for_call,

            "message": (
                "Retell configuration verified "
                "without creating a phone call."
            ),
        }

    # ------------------------------------------------------------------
    # Real outbound call
    # ------------------------------------------------------------------

    def make_call(
        self,
        conversation_id: str,
        phone_number: str,
    ) -> CallResult:
        """
        Create a real outbound Retell AI phone call.

        WARNING:
        This method DOES create a real call and may consume
        Retell/telephony credits.

        It is intentionally separate from verification.
        """

        if not phone_number:
            return CallResult(
                success=False,
                call_id=None,
                status=ConversationStatus.CREATED,
                message="Phone number is required.",
            )

        try:

            payload = {
                "from_number": self.phone_number,
                "to_number": self._format_phone_number(
                    phone_number
                ),
                "override_agent_id": self.agent_id,
                "metadata": {
                    "conversation_id": conversation_id,
                },
            }

            response = self._request(
                "POST",
                "/v2/create-phone-call",
                payload,
            )

            return CallResult(
                success=True,
                call_id=response.get(
                    "call_id"
                ),
                status=ConversationStatus.RINGING,
                message=(
                    "Retell AI call created successfully."
                ),
                raw_response=response,
            )

        except Exception as exc:

            return CallResult(
                success=False,
                call_id=None,
                status=ConversationStatus.CREATED,
                message=(
                    f"Retell call failed: {exc}"
                ),
                raw_response={
                    "conversation_id": conversation_id,
                    "phone_number": phone_number,
                },
            )

    @staticmethod
    def _format_phone_number(
        phone_number: str,
    ) -> str:
        """
        Convert common Indian 10-digit numbers to E.164.
        """

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

        if (
            cleaned.startswith("91")
            and len(cleaned) == 12
        ):
            return f"+{cleaned}"

        if len(cleaned) == 10:
            return f"+91{cleaned}"

        return cleaned


class TwilioTelephonyProvider:
    """
    Existing Twilio provider retained temporarily.

    It is NOT the active production provider.
    """

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> None:

        self.account_sid = (
            account_sid
            or settings.twilio_account_sid
        )

        self.auth_token = (
            auth_token
            or settings.twilio_auth_token
        )

        self.phone_number = (
            phone_number
            or settings.twilio_phone_number
        )

    def make_call(
        self,
        conversation_id: str,
        phone_number: str,
    ) -> CallResult:

        return CallResult(
            success=False,
            call_id=None,
            status=ConversationStatus.CREATED,
            message=(
                "Twilio provider is retained for compatibility "
                "but is no longer the active production provider."
            ),
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
