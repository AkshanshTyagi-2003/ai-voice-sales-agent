"""
Buying-intent analysis.

Provides deterministic intent signals that recognize explicit buying
language, genuine project requirements, and combinations of strong
qualification signals.
"""

import re
from typing import List

from app.core.models import IntentResult, LeadTemperature


HIGH_INTENT_PATTERNS = [
    r"\bready to start\b",
    r"\bready to proceed\b",
    r"\bwant to proceed\b",
    r"\bmove forward\b",
    r"\bwhen can you start\b",
    r"\bhow soon can you start\b",
    r"\bhow soon\b",
    r"\bneed it asap\b",
    r"\bneed it urgently\b",
    r"\bwant it asap\b",
    r"\bwant it urgently\b",
    r"\bwhat is the price\b",
    r"\bwhat's the price\b",
    r"\bhow much does it cost\b",
    r"\bhow much will it cost\b",
    r"\bwhat will it cost\b",
    r"\bwhat would it cost\b",
    r"\bsend me the details\b",
    r"\bsend the details\b",
    r"\bcan you start\b",
    r"\bcan we start\b",
]


MEDIUM_INTENT_PATTERNS = [
    r"\binterested\b",
    r"\bneed a website\b",
    r"\bneed an ecommerce\b",
    r"\bneed an e-commerce\b",
    r"\blooking for a website\b",
    r"\blooking for an ecommerce\b",
    r"\blooking for an e-commerce\b",
    r"\bplanning to\b",
    r"\bwant to build\b",
    r"\bthinking about\b",
    r"\bwould like\b",
    r"\bneed online\b",
    r"\be-commerce website\b",
    r"\becommerce website\b",
    r"\bonline store\b",
    r"\bonline shop\b",
    r"\bwebsite for my business\b",
]


LOW_INTENT_PATTERNS = [
    r"\bjust looking\b",
    r"\bjust checking\b",
    r"\bjust curious\b",
    r"\bnot sure\b",
    r"\bmaybe later\b",
    r"\bnot interested\b",
    r"\bno plans\b",
    r"\bnot planning\b",
    r"\bjust browsing\b",
]


BUDGET_PATTERNS = [
    r"\bbudget\b",
    r"\b₹\s*[\d,]+\b",
    r"\brs\.?\s*[\d,]+\b",
    r"\binr\s*[\d,]+\b",
]


TIMELINE_PATTERNS = [
    r"\bwithin\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
    r"\bwithin\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:days?|weeks?|months?|years?)\b",
    r"\bin\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
    r"\bin\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:days?|weeks?|months?|years?)\b",
    r"\bnext\s+(?:day|week|month|year)\b",
    r"\bthis\s+(?:week|month|year)\b",
    r"\btomorrow\b",
    r"\basap\b",
    r"\burgently\b",
    r"\bimmediately\b",
]


PROJECT_PATTERNS = [
    r"\be-commerce\b",
    r"\becommerce\b",
    r"\bonline store\b",
    r"\bonline shop\b",
    r"\bwebsite\b",
    r"\bwebsite for my business\b",
    r"\bonline business\b",
]


FEATURE_PATTERNS = [
    r"\bpayment gateway\b",
    r"\bcheckout\b",
    r"\border tracking\b",
    r"\binventory\b",
    r"\bcart\b",
    r"\banalytics\b",
]


def _matches_patterns(
    text: str,
    patterns: List[str],
) -> List[str]:
    """Return all patterns that match the supplied text."""

    matches = []

    for pattern in patterns:
        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            matches.append(pattern)

    return matches


def _has_any_pattern(
    text: str,
    patterns: List[str],
) -> bool:
    """Return True when at least one pattern matches."""

    return bool(
        _matches_patterns(text, patterns)
    )


def calculate_intent_score(text: str) -> float:
    """
    Calculate buying intent from explicit language and concrete
    project signals.

    Multiple concrete signals are intentionally treated as stronger
    evidence than isolated keywords.
    """

    normalized = text.strip()

    if not normalized:
        return 0.0

    high_matches = _matches_patterns(
        normalized,
        HIGH_INTENT_PATTERNS,
    )

    medium_matches = _matches_patterns(
        normalized,
        MEDIUM_INTENT_PATTERNS,
    )

    low_matches = _matches_patterns(
        normalized,
        LOW_INTENT_PATTERNS,
    )

    has_budget = _has_any_pattern(
        normalized,
        BUDGET_PATTERNS,
    )

    has_timeline = _has_any_pattern(
        normalized,
        TIMELINE_PATTERNS,
    )

    has_project = _has_any_pattern(
        normalized,
        PROJECT_PATTERNS,
    )

    has_feature = _has_any_pattern(
        normalized,
        FEATURE_PATTERNS,
    )

    score = 0.0

    # --------------------------------------------------------------
    # Explicit buying intent.
    # --------------------------------------------------------------

    score += min(
        len(high_matches) * 0.40,
        0.90,
    )

    # --------------------------------------------------------------
    # General interest.
    # --------------------------------------------------------------

    score += min(
        len(medium_matches) * 0.15,
        0.30,
    )

    # --------------------------------------------------------------
    # Concrete project signals.
    # --------------------------------------------------------------

    concrete_signals = sum(
        [
            has_budget,
            has_timeline,
            has_project,
            has_feature,
        ]
    )

    score += concrete_signals * 0.15

    # --------------------------------------------------------------
    # Strong combination bonus.
    #
    # A customer giving multiple concrete requirements is much more
    # valuable than someone merely mentioning "website".
    # --------------------------------------------------------------

    if has_project and has_budget:
        score += 0.15

    if has_project and has_timeline:
        score += 0.15

    if has_budget and has_timeline:
        score += 0.15

    if has_project and has_budget and has_timeline:
        score += 0.20

    # --------------------------------------------------------------
    # Explicit negative intent.
    # --------------------------------------------------------------

    score -= min(
        len(low_matches) * 0.40,
        0.80,
    )

    return max(
        0.0,
        min(1.0, score),
    )


def analyze_intent(text: str) -> IntentResult:
    """Analyze one customer message."""

    score = calculate_intent_score(text)

    high_matches = _matches_patterns(
        text,
        HIGH_INTENT_PATTERNS,
    )

    medium_matches = _matches_patterns(
        text,
        MEDIUM_INTENT_PATTERNS,
    )

    low_matches = _matches_patterns(
        text,
        LOW_INTENT_PATTERNS,
    )

    has_budget = _has_any_pattern(
        text,
        BUDGET_PATTERNS,
    )

    has_timeline = _has_any_pattern(
        text,
        TIMELINE_PATTERNS,
    )

    has_project = _has_any_pattern(
        text,
        PROJECT_PATTERNS,
    )

    has_feature = _has_any_pattern(
        text,
        FEATURE_PATTERNS,
    )

    reasons = []

    if high_matches:
        reasons.append(
            "Customer used strong buying-intent language."
        )

    if medium_matches:
        reasons.append(
            "Customer expressed a genuine business need."
        )

    if has_project:
        reasons.append(
            "Customer described a concrete project."
        )

    if has_budget:
        reasons.append(
            "Customer provided budget information."
        )

    if has_timeline:
        reasons.append(
            "Customer provided timeline information."
        )

    if has_feature:
        reasons.append(
            "Customer described requested functionality."
        )

    if low_matches:
        reasons.append(
            "Customer expressed uncertainty or low intent."
        )

    if score >= 0.70:
        temperature = LeadTemperature.HOT
    elif score >= 0.30:
        temperature = LeadTemperature.WARM
    else:
        temperature = LeadTemperature.COLD

    if not reasons:
        reasons.append(
            "No clear buying-intent signal detected."
        )

    return IntentResult(
        score=score,
        temperature=temperature,
        reasons=reasons,
        high_intent=score >= 0.70,
    )


def analyze_conversation(
    messages: List[str],
) -> IntentResult:
    """
    Analyze multiple customer messages as one combined signal.

    The complete customer conversation is evaluated so that
    qualification information accumulated across several turns
    contributes to the final intent.
    """

    combined_text = " ".join(
        message.strip()
        for message in messages
        if message and message.strip()
    )

    return analyze_intent(combined_text)