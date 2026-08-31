"""
Lead classification.

Determines whether a lead is HOT, WARM, or COLD.

IMPORTANT DESIGN NOTE:
app.ai.intent already runs a priority-ordered decision tree (negative ->
barrier+hot -> barrier -> hot -> urgent timeline+project -> fully-qualified
-> general interest -> cold) over the FULL combined customer transcript
(analyze_conversation joins every customer message before deciding). That
tree is the single source of truth for the HOT/WARM/COLD *verdict*.

This module used to re-derive its own verdict with a separately weighted
score (intent_score * 0.65 + qualification bonuses, thresholded at 0.45 /
0.25). That formula could -- and did -- disagree with intent.py: e.g. a
barrier-only message that intent.py deliberately caps at WARM (score <=
0.65) could still cross classification.py's own 0.45 threshold and get
promoted to HOT, silently overriding intent.py's judgement.

The fix: classify_lead() takes its temperature directly, unmodified, from
analyze_conversation()'s verdict over the full transcript. Nothing in this
module re-scores or overrides that verdict.

An earlier version of this fix tried to layer a WARM->HOT "qualification
completeness" upgrade on top, gated on `qualification.objections` being
empty. That reintroduced the exact same bug: a barrier like "my brother
handles all our decisions" is never recorded in `qualification.objections`
(app.ai.qualification only logs sales objections like "too expensive"
there, not decision-maker/approval barriers), so the gate didn't actually
protect anything -- a barrier-capped WARM lead with 3+ qualification
fields still got silently promoted to HOT. intent.py's own "fully
qualified lead" rule (case 3c in its decision tree) already runs the
equivalent check against the full raw transcript on every turn, so there
is no missing coverage from removing the duplicate here -- only a second
place for the two modules' answers to disagree.
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
    """
    Informational 0-1 score combining intent and qualification
    completeness. This is exposed for logging / ranking / sorting leads
    in dashboards -- it is NOT used to decide HOT/WARM/COLD (see module
    docstring). Do not gate temperature decisions on this value.
    """

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


def has_project_information(qualification: QualificationData) -> bool:
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


def _temperature_from_score(score: float) -> LeadTemperature:
    """
    Fallback band used only when there is no new customer message to run
    through analyze_conversation() this turn (e.g. classify_and_update is
    called with an empty message list). Uses the exact same thresholds
    app.ai.intent.analyze_intent uses (>=0.70 HOT, >=0.30 WARM) so this
    never introduces a second, disagreeing formula.
    """

    if score >= 0.70:
        return LeadTemperature.HOT
    if score >= 0.30:
        return LeadTemperature.WARM
    return LeadTemperature.COLD


def classify_lead(
    lead: Lead,
    recent_customer_messages: Optional[List[str]] = None,
) -> LeadTemperature:
    """
    Classify a lead. The verdict is exactly what app.ai.intent's
    decision tree returns for the full customer transcript -- see module
    docstring for why this module does not layer any additional scoring
    or overrides on top of that verdict.
    """

    messages = recent_customer_messages or []

    if messages:
        intent_result = analyze_conversation(messages)
        lead.intent_score = max(lead.intent_score, intent_result.score)
        return intent_result.temperature

    if lead.temperature is not None:
        return lead.temperature

    return _temperature_from_score(lead.intent_score)


def classify_and_update(
    lead: Lead,
    recent_customer_messages: Optional[List[str]] = None,
) -> Lead:
    """Calculate intent and update the lead's classification."""

    messages = recent_customer_messages or []

    if messages:
        intent_result = analyze_conversation(messages)
        lead.intent_score = max(lead.intent_score, intent_result.score)

    lead.temperature = classify_lead(lead, recent_customer_messages=messages)

    return lead