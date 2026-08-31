# callback.py
"""
Callback action layer.

Handles customer callback requests while keeping scheduling
implementation independent from the rest of the application.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Protocol

from app.core.models import CallbackRequest, Lead
from app.storage.repository import callback_repository
from app.utils.helpers import utc_now


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


class CallbackManager:
    """Creates and persists callback requests."""

    def __init__(
        self,
        scheduler: Optional[CallbackScheduler] = None,
    ) -> None:
        self.scheduler = scheduler

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
    Local callback scheduler.

    Does not contact a calendar or external service.
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