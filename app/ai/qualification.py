"""
Lead qualification extraction.

Extracts structured qualification information from customer messages
while preserving information that has already been collected.
"""

import re
from typing import List, Optional

from app.core.models import QualificationData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_budget(text: str) -> Optional[str]:
    """Extract an explicit budget without confusing product counts with it."""

    patterns = [
        (
            r"(?:budget|spend|investment|can spend|willing to spend)"
            r"(?:\s+is|\s+of|\s*:)?\s*"
            r"(₹\s?[\d,]+(?:\.\d+)?|rs\.?\s?[\d,]+(?:\.\d+)?|"
            r"inr\s?[\d,]+(?:\.\d+)?|\$[\d,]+(?:\.\d+)?)"
        ),
        (
            r"(₹\s?[\d,]+(?:\.\d+)?)"
            r"\s*(?:budget|for the website|for this project)"
        ),
        (
            r"(?:around|approximately|approx\.?|about)"
            r"\s*(₹\s?[\d,]+(?:\.\d+)?)"
            r"\s*(?:budget)?"
        ),
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value = match.group(1).strip()

            if value:
                return (
                    value
                    .replace("rs ", "₹")
                    .replace("inr ", "₹")
                )

    return None


def _extract_product_count(text: str) -> Optional[int]:
    """Extract product/catalog quantity."""

    patterns = [
        (
            r"(?:around|approximately|approx\.?|about)?\s*"
            r"(\d[\d,]*)\s*(?:products?|items?|sku[s]?)\b"
        ),
        (
            r"(?:products?|items?|sku[s]?)"
            r"(?:\s+are|\s*[:\-])?\s*"
            r"(\d[\d,]*)\b"
        ),
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                continue

    return None


def _extract_timeline(text: str) -> Optional[str]:
    """Extract the most useful project timeline from the message."""

    number = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"

    patterns = [
        (
            rf"((?:within|in|by|around|about)\s+"
            rf"{number}\s+"
            r"(?:day|days|week|weeks|month|months|year|years))",
            3,
        ),
        (
            r"((?:next|this)\s+"
            r"(?:week|month|year))",
            2,
        ),
        (
            rf"((?:start|launch|go live)"
            rf"\s+(?:within|in|by)\s+"
            rf"{number}\s+"
            r"(?:day|days|week|weeks|month|months|year|years))",
            3,
        ),
        (
            r"((?:as soon as possible|asap|immediately|urgently))",
            1,
        ),
    ]

    best_value: Optional[str] = None
    best_priority = 0

    for pattern, priority in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match and priority > best_priority:
            best_value = match.group(1).strip()
            best_priority = priority

    return best_value


def _timeline_priority(value: Optional[str]) -> int:
    """Return a priority representing timeline specificity."""

    if not value:
        return 0

    lowered = value.lower()

    number = (
        r"(?:\d+|one|two|three|four|five|six|seven|eight|"
        r"nine|ten)"
    )

    if re.search(
        rf"{number}\s+(?:day|days|week|weeks|month|months|year|years)",
        lowered,
    ):
        return 3

    if "next" in lowered or "this" in lowered:
        return 2

    if any(
        phrase in lowered
        for phrase in (
            "as soon as possible",
            "asap",
            "immediately",
            "urgently",
        )
    ):
        return 1

    return 1


def _extract_features(text: str) -> List[str]:
    """Extract commonly requested website features."""

    feature_patterns = {
        "payment gateway": [
            r"payment\s+gateway",
            r"online\s+payment",
            r"online\s+payments?",
        ],
        "checkout": [
            r"\bcheckout\b",
        ],
        "order tracking": [
            r"order\s+tracking",
            r"track\s+(?:orders?|shipments?)",
        ],
        "login": [
            r"user\s+login",
            r"customer\s+login",
            r"\blogin\b",
            r"\bsign\s*in\b",
        ],
        "admin panel": [
            r"admin\s+panel",
            r"admin\s+dashboard",
        ],
        "search": [
            r"\bsearch\b",
            r"product\s+search",
        ],
        "wishlist": [
            r"\bwishlist\b",
            r"wish\s+list",
        ],
        "reviews": [
            r"product\s+reviews?",
            r"customer\s+reviews?",
            r"\breviews?\b",
        ],
    }

    features: List[str] = []

    for feature, patterns in feature_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                features.append(feature)
                break

    return features


def _extract_business_description(text: str) -> Optional[str]:
    """Extract a concise business description."""

    patterns = [
        (
            r"(?:my\s+)?business\s+is\s+(?:a\s+|an\s+)?"
            r"([A-Za-z][A-Za-z\s&\-]{2,80}?)"
            r"(?:\s+and\s+|\s*,|\s*\.|$)"
        ),
        (
            r"(?:i\s+(?:run|own|have))\s+(?:a\s+|an\s+)?"
            r"([A-Za-z][A-Za-z\s&\-]{2,80}?)"
            r"(?:\s+and\s+|\s*,|\s*\.|$)"
        ),
        (
            r"(?:for\s+my)\s+(?:a\s+|an\s+)?"
            r"([A-Za-z][A-Za-z\s&\-]{2,80}?)"
            r"(?:\s+business|\s+company|\s+store|\s*,|\s*\.|$)"
        ),
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value = match.group(1).strip()

            value = re.sub(
                r"\s+company$",
                "",
                value,
                flags=re.IGNORECASE,
            ).strip()

            if value:
                return value

    match = re.search(
        r"(?:business|company|store)\s+"
        r"(?:is|deals?\s+in|sells?)\s+"
        r"(?:a\s+|an\s+)?"
        r"([A-Za-z][A-Za-z\s&\-]{2,50})",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).strip()

    return None


def _extract_decision_maker(text: str) -> Optional[str]:
    """Extract decision-maker information."""

    patterns = [
        (
            r"(?:i\s+am|i'm)\s+(?:the\s+)?"
            r"(owner|founder|co-founder|director|manager|decision maker)"
        ),
        (
            r"(?:the\s+)?"
            r"(owner|founder|co-founder|director|manager)"
            r"\s+(?:will\s+)?(?:decide|make\s+the\s+decision)"
        ),
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return match.group(1).strip()

    return None


def _extract_objections(text: str) -> List[str]:
    """Extract explicit customer objections."""

    objection_patterns = [
        (
            r"(?:i\s+am\s+concerned\s+about|"
            r"i'm\s+concerned\s+about)\s+([^.!?]+)"
        ),
        (
            r"(?:my\s+concern\s+is)\s+([^.!?]+)"
        ),
        (
            r"(?:i\s+worry\s+about)\s+([^.!?]+)"
        ),
        (
            r"(?:too\s+expensive)\b"
        ),
        (
            r"(?:too\s+costly)\b"
        ),
        (
            r"(?:not\s+sure\s+about)\s+([^.!?]+)"
        ),
    ]

    objections: List[str] = []

    for pattern in objection_patterns:
        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE,
        )

        for match in matches:
            if isinstance(match, tuple):
                value = " ".join(
                    part for part in match if part
                )
            else:
                value = match

            value = value.strip()

            if value and value not in objections:
                objections.append(value)

    return objections


# ---------------------------------------------------------------------------
# Qualification merge
# ---------------------------------------------------------------------------

def merge_qualification(
    existing: Optional[QualificationData],
    new: Optional[QualificationData],
) -> QualificationData:
    """
    Merge newly extracted qualification data into existing data.

    Existing concrete information is preserved when a new value is
    less specific or missing.
    """

    existing = existing or QualificationData()
    new = new or QualificationData()

    # -----------------------------------------------------------------------
    # Budget
    # -----------------------------------------------------------------------

    budget = (
        new.budget
        if new.budget is not None
        else existing.budget
    )

    # -----------------------------------------------------------------------
    # Products
    # -----------------------------------------------------------------------

    products = (
        new.products
        if new.products is not None
        else existing.products
    )

    product_count = (
        new.product_count
        if new.product_count is not None
        else existing.product_count
    )

    # -----------------------------------------------------------------------
    # Timeline
    # -----------------------------------------------------------------------

    if existing.timeline and new.timeline:
        existing_priority = _timeline_priority(existing.timeline)
        new_priority = _timeline_priority(new.timeline)

        if new_priority >= existing_priority:
            timeline = new.timeline
        else:
            timeline = existing.timeline

    else:
        timeline = new.timeline or existing.timeline

    # -----------------------------------------------------------------------
    # Features
    # -----------------------------------------------------------------------

    features = list(existing.features)

    for feature in new.features:
        if feature not in features:
            features.append(feature)

    # -----------------------------------------------------------------------
    # Business description
    # -----------------------------------------------------------------------

    business_description = (
        new.business_description
        if new.business_description is not None
        else existing.business_description
    )

    # -----------------------------------------------------------------------
    # Decision maker
    # -----------------------------------------------------------------------

    decision_maker = (
        new.decision_maker
        if new.decision_maker is not None
        else existing.decision_maker
    )

    # -----------------------------------------------------------------------
    # Objections
    # -----------------------------------------------------------------------

    objections = list(existing.objections)

    for objection in new.objections:
        if objection not in objections:
            objections.append(objection)

    return QualificationData(
        budget=budget,
        products=products,
        product_count=product_count,
        timeline=timeline,
        features=features,
        business_description=business_description,
        decision_maker=decision_maker,
        objections=objections,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_qualification(
    text: str,
    existing: Optional[QualificationData] = None,
) -> QualificationData:
    """
    Extract qualification data from a customer message.

    Existing qualification information is preserved unless the new
    message contains a more useful value.
    """

    existing = existing or QualificationData()

    extracted = QualificationData(
        budget=_extract_budget(text),
        products=None,
        product_count=_extract_product_count(text),
        timeline=_extract_timeline(text),
        features=_extract_features(text),
        business_description=_extract_business_description(text),
        decision_maker=_extract_decision_maker(text),
        objections=_extract_objections(text),
    )

    return merge_qualification(
        existing,
        extracted,
    )