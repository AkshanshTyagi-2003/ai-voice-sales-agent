# callback.py
"""
Callback action layer.

Handles customer callback requests while keeping scheduling
implementation independent from the rest of the application.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Protocol

from app.core.config import settings
from app.core.models import CallbackRequest, Lead
from app.storage.repository import callback_repository
from app.utils.datetime_parser import parse_relative_datetime
from app.utils.helpers import utc_now

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


@dataclass
class CallbackResult:
    """Result of processing a callback request."""

    success: bool
    callback: Optional[CallbackRequest] = None
    message: str = ""
    raw_response: Optional[Dict[str, Any]] = None


class CallbackScheduler(Protocol):
    """Interface for an external scheduling system."""

    def schedule(
        self,
        callback: CallbackRequest,
    ) -> Optional[datetime]:
        ...


class NaturalLanguageCallbackScheduler:
    """
    Default scheduler: turns the customer's spoken phrasing ("call me
    back tomorrow morning") into a concrete datetime using
    app.utils.datetime_parser, in the business's configured timezone
    (settings.timezone).

    Previously CallbackManager() defaulted to scheduler=None, which
    meant CallbackRequest.scheduled_for was NEVER populated -- not from
    the live call, and not even from the manual /scheduler/callback API
    endpoint -- because nothing computed it. This is the actual
    date/time computation that was missing.
    """

    def _now(self) -> datetime:
        if ZoneInfo is not None:
            try:
                return datetime.now(ZoneInfo(settings.timezone or "Asia/Kolkata"))
            except Exception:
                pass
        return datetime.utcnow()

    def schedule(self, callback: CallbackRequest) -> Optional[datetime]:
        return parse_relative_datetime(
            callback.requested_time_text,
            reference=self._now(),
        )


class CallbackManager:
    """Creates and persists callback requests."""

    def __init__(
        self,
        scheduler: Optional[CallbackScheduler] = None,
    ) -> None:
        self.scheduler = scheduler or NaturalLanguageCallbackScheduler()

    def request_callback(
        self,
        lead: Lead,
        requested_time_text: str,
    ) -> CallbackResult:
        """Create a callback request for a lead."""

        requested_time_text = (
            requested_time_text.strip()
        )

        if not requested_time_text:
            return CallbackResult(
                success=False,
                message=(
                    "Callback time cannot be empty."
                ),
            )

        callback = CallbackRequest(
            lead_id=lead.lead_id,
            requested_time_text=requested_time_text,
            created_at=utc_now(),
        )

        if self.scheduler:
            try:
                callback.scheduled_for = (
                    self.scheduler.schedule(callback)
                )
            except Exception as exc:
                return CallbackResult(
                    success=False,
                    message=(
                        f"Callback scheduling error: {exc}"
                    ),
                )

        callback_repository.save(callback)

        return CallbackResult(
            success=True,
            callback=callback,
            message="Callback request saved successfully.",
        )


class MockCallbackScheduler:
    """
    Test-only scheduler that returns a fixed time instead of parsing.

    Kept for existing tests that construct CallbackManager with an
    explicit scheduler; NOT the default anymore (see
    NaturalLanguageCallbackScheduler above).
    """

    def __init__(
        self,
        scheduled_time: Optional[datetime] = None,
    ) -> None:
        self.scheduled_time = scheduled_time
        self.requests = []

    def schedule(
        self,
        callback: CallbackRequest,
    ) -> Optional[datetime]:
        """Record a simulated scheduling request."""

        self.requests.append(callback)

        return self.scheduled_time


# ---------------------------------------------------------------------------
# Live-call callback detection
# ---------------------------------------------------------------------------
#
# This is the piece that was missing end-to-end: nothing in
# app/api/retell_webhook.py ever looked at a customer's live turn to
# decide "this is a callback request" and call CallbackManager. The
# scheduler existed only as a manual POST /scheduler/callback endpoint,
# so requirement #7/#8 ("If I say call me back tomorrow morning, your
# system understands it and books the callback itself") was never
# exercised during an actual call.
#
# UPDATE: the phrase pattern below was widened to cover ordinary
# callback language ("I'll call you...", "you can call me...",
# "please call me...", "ring me", "phone me", "let's talk",
# "we can talk") -- it previously only matched "call/ring/phone ...
# back" and "call me later/again", which meant everyday phrasing like
# "I will call you tonight at 9 PM" was silently never detected. All
# previously-matching phrases still match; this only adds coverage.
#
# Still kept conservative in the same way as before: a callback phrase
# alone is not enough (avoids false positives on "I'll call my partner
# tomorrow" or "our office opens at 9 PM" -- neither contains "call
# me"/"call you"/etc, so neither matches); a bare time phrase alone is
# not enough either (avoids misfiring on "the website should launch
# tomorrow", which has no callback phrase at all). Both a callback
# phrase AND a parseable time must be present in the same customer
# turn.

_CALLBACK_PHRASE_PATTERN = re.compile(
    r"\b(call|ring|phone)\s+(me\s+)?back\b"
    r"|\bcall\s+me\s+(later|again)\b"
    r"|\bschedule\s+a\s+call(back)?\b"
    r"|\bbook\s+a\s+call(back)?\b"
    r"|\bcall\s+(me|you)\b"
    r"|\bring\s+(me|you)\b"
    r"|\bphone\s+(me|you)\b"
    r"|\blet'?s\s+talk\b"
    r"|\bwe\s+can\s+talk\b",
    re.IGNORECASE,
)


def detect_callback_request(text: str) -> Optional[str]:
    """
    Return the requested-time text if a customer turn is asking to be
    called back at a specific (possibly relative/vague) time, else None.

    Returns the original text (not just the matched time phrase) so
    NaturalLanguageCallbackScheduler / parse_relative_datetime can look
    at the full sentence for context.
    """
    if not text:
        return None

    text = text.strip()
    if not text:
        return None

    if not _CALLBACK_PHRASE_PATTERN.search(text):
        return None

    if parse_relative_datetime(text) is None:
        return None

    return text