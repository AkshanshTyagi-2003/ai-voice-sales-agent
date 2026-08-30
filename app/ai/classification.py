"""
Lead classification.

Determines whether a lead is HOT, WARM, or COLD using buying intent,
qualification completeness, and customer barriers.
"""

from typing import List, Optional

from app.ai.intent import analyze_conversation
from app.core.models import (
    Lead,
    LeadTemperature,
    QualificationData,
)


def calculate_lead_score(
    qualification: QualificationData,
    intent_score: float,
) -> float:
    """Calculate a combined qualification and intent score."""

    score = intent_score * 0.65

    if qualification.budget:
        score += 0.08

    if qualification.products:
        score += 0.05

    if qualification.product_count is not None:
        score += 0.05

    if qualification.timeline:
        score += 0.08

    if qualification.features:
        score += 0.05

    if qualification.objections:
        score -= 0.05

    return max(0.0, min(1.0, score))


def has_project_information(
    qualification: QualificationData,
) -> bool:
    """Check whether the customer has revealed a real project need."""

    return any(
        [
            qualification.budget,
            qualification.products,
            qualification.product_count is not None,
            qualification.timeline,
            bool(qualification.features),
            qualification.business_description,
        ]
    )


def classify_lead(
    lead: Lead,
    recent_customer_messages: Optional[List[str]] = None,
) -> LeadTemperature:
    """
    Classify a lead based on conversation intent and qualification.

    HOT:
        Strong buying signal plus meaningful project information.

    WARM:
        Genuine project interest but incomplete commitment or
        meaningful barriers.

    COLD:
        Little/no buying intent or purely exploratory conversation.
    """

    messages = recent_customer_messages or []

    if messages:
        intent_result = analyze_conversation(messages)
        intent_score = max(
            lead.intent_score,
            intent_result.score,
        )
    else:
        intent_score = lead.intent_score

    qualification = lead.qualification

    has_project = has_project_information(
        qualification
    )

    has_major_barrier = bool(
        qualification.objections
    )

    score = calculate_lead_score(
        qualification,
        intent_score,
    )

    # Strong explicit intent with a real project should be HOT.
    if intent_score >= 0.70 and has_project:
        return LeadTemperature.HOT

    # A customer with several concrete project details is at least
    # meaningfully interested.
    if score >= 0.45:
        if has_major_barrier:
            return LeadTemperature.WARM

        return LeadTemperature.HOT

    if score >= 0.25 or has_project:
        return LeadTemperature.WARM

    return LeadTemperature.COLD


def classify_and_update(
    lead: Lead,
    recent_customer_messages: Optional[List[str]] = None,
) -> Lead:
    """Calculate intent and update the lead's classification."""

    messages = recent_customer_messages or []

    if messages:
        intent_result = analyze_conversation(messages)

        lead.intent_score = max(
            lead.intent_score,
            intent_result.score,
        )

    lead.temperature = classify_lead(
        lead,
        recent_customer_messages=messages,
    )

    return lead