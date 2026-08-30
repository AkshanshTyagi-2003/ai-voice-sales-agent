"""
Scheduler API endpoints.

Provides endpoints for creating and viewing callback requests.
Actual background scheduling will be connected later.
"""

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.actions.callback import CallbackManager
from app.core.models import Lead
from app.storage.repository import (
    callback_repository,
    lead_repository,
)

router = APIRouter(
    prefix="/scheduler",
    tags=["scheduler"],
)


class CallbackRequestBody(BaseModel):
    """Callback scheduling request."""

    lead_id: str
    requested_time_text: str


@router.post("/callback")
def schedule_callback(
    request: CallbackRequestBody,
):
    """Create a callback request."""

    lead = lead_repository.get(
        request.lead_id
    )

    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found.",
        )

    manager = CallbackManager()

    result = manager.request_callback(
        lead,
        request.requested_time_text,
    )

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail=result.message,
        )

    return {
        "success": True,
        "lead_id": lead.lead_id,
        "requested_time": (
            result.callback.requested_time_text
            if result.callback
            else None
        ),
        "message": result.message,
    }


@router.get("/callback/{lead_id}")
def get_callbacks(
    lead_id: str,
):
    """Return callback requests for a lead."""

    lead = lead_repository.get(
        lead_id
    )

    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found.",
        )

    callbacks = callback_repository.list_for_lead(
        lead_id
    )

    return {
        "lead_id": lead_id,
        "count": len(callbacks),
        "callbacks": [
            callback.model_dump()
            for callback in callbacks
        ],
    }