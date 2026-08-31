"""
Lead qualification extraction.

Extracts structured qualification information from customer messages
while preserving information that has already been collected.
"""
import re
from typing import List, Optional

from app.core.models import QualificationData


# ---------------------------------------------------------------------------
# Amount-word normalization (k / thousand / lakh)
# ---------------------------------------------------------------------------

_MULTIPLIERS = {
    "k": 1_000,
    "thousand": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "l": 100_000,
}


def _normalize_bare_number(raw: str) -> Optional[int]:
    try:
        return int(raw.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _format_amount(value: int) -> str:
    return f"approximately {value:,}"


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def _extract_budget(text: str) -> Optional[str]:
    """Extract an explicit budget without confusing product counts with it."""

    # 1. Currency-symbol amounts near a budget/spend keyword.
    currency_patterns = [
        (
            r"(?:budget|spend|investment|can\s+spend|willing\s+to\s+spend)"
            r"(?:\s+is|\s+of|\s*:)?\s*"
            r"(₹\s?[\d,]+(?:\.\d+)?|rs\.?\s?[\d,]+(?:\.\d+)?|"
            r"inr\s?[\d,]+(?:\.\d+)?|\$[\d,]+(?:\.\d+)?)"
        ),
        (
            r"(₹\s?[\d,]+(?:\.\d+)?)"
            r"\s*(?:budget|for\s+the\s+website|for\s+this\s+project)"
        ),
        (
            r"(?:around|approximately|approx\.?|about)"
            r"\s*(₹\s?[\d,]+(?:\.\d+)?)"
            r"\s*(?:budget)?"
        ),
    ]
    for pattern in currency_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value.replace("rs ", "₹").replace("inr ", "₹")

    # 2. "budget/spend ... <number> k|thousand|lakh" (no currency symbol).
    word_amount_pattern = (
        r"(?:budget|spend|investment|can\s+spend|willing\s+to\s+spend)"
        r"(?:\s+is|\s+of|\s*:)?\s*"
        r"(?:around|approximately|approx\.?|about)?\s*"
        r"(\d[\d,]*(?:\.\d+)?)\s*"
        r"(k|thousand|lakhs?|l)\b"
    )
    match = re.search(word_amount_pattern, text, re.IGNORECASE)
    if match:
        number = _normalize_bare_number(match.group(1))
        unit = match.group(2).lower()
        if number is not None:
            multiplier = _MULTIPLIERS.get(unit, 1)
            return _format_amount(int(number * multiplier))

    # 3. Bare "<number> k|thousand|lakh" with no explicit budget keyword,
    #    e.g. "50k", "80 thousand" used loosely in context of the project.
    bare_word_amount_pattern = (
        r"(?:^|\s)(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?)\b"
    )
    match = re.search(bare_word_amount_pattern, text, re.IGNORECASE)
    if match and re.search(r"\bbudget\b|\bspend\b", text, re.IGNORECASE):
        number = _normalize_bare_number(match.group(1))
        unit = match.group(2).lower()
        if number is not None:
            multiplier = _MULTIPLIERS.get(unit, 1)
            return _format_amount(int(number * multiplier))

    # 4. Bare number directly after "budget is/of ₹" already covered; also
    #    accept a bare number with no currency symbol at all, e.g.
    #    "My budget is 40,000."
    bare_number_pattern = (
        r"(?:budget|spend|investment|can\s+spend|willing\s+to\s+spend)"
        r"(?:\s+is|\s+of|\s*:)?\s*"
        r"(?:around|approximately|approx\.?|about)?\s*"
        r"(\d[\d,]{2,}(?:\.\d+)?)\b"
    )
    match = re.search(bare_number_pattern, text, re.IGNORECASE)
    if match:
        value = match.group(1).strip()
        if value:
            return value

    return None


# ---------------------------------------------------------------------------
# Product count
# ---------------------------------------------------------------------------

_COUNTABLE_NOUNS = (
    r"products?|items?|sku[s]?|dishes|services|units|listings|designs|"
    r"courses|rooms|variants"
)


def _extract_product_count(text: str) -> Optional[int]:
    """Extract product/catalog quantity."""

    patterns = [
        (
            rf"catalog\s+of\s+(\d[\d,]*)\s*(?:{_COUNTABLE_NOUNS})?"
        ),
        (
            r"(?:around|approximately|approx\.?|about|roughly)?\s*"
            rf"(\d[\d,]*)\s*(?:{_COUNTABLE_NOUNS})\b"
        ),
        (
            rf"(?:{_COUNTABLE_NOUNS})"
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


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

_NUMBER_WORD = (
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
)


def _extract_timeline(text: str) -> Optional[str]:
    """Extract the most useful project timeline from the message."""

    patterns = [
        (
            rf"((?:within|in|by|around|about)\s+"
            rf"{_NUMBER_WORD}\s+"
            r"(?:days?|weeks?|months?|years?))",
            3,
        ),
        (
            r"((?:within|in)\s+a\s+(?:day|week|month|year))",
            3,
        ),
        (
            r"((?:before|by)\s+next\s+(?:day|week|month|year))",
            3,
        ),
        (
            r"((?:next|this)\s+(?:week|month|year))",
            2,
        ),
        (
            rf"((?:start|launch|go\s+live)"
            rf"\s+(?:within|in|by)\s+"
            rf"{_NUMBER_WORD}\s+"
            r"(?:days?|weeks?|months?|years?))",
            3,
        ),
        (
            r"(next\s+quarter)",
            2,
        ),
        (
            r"((?:as\s+soon\s+as\s+possible|asap|immediately|urgently))",
            1,
        ),
        (
            r"(\bsoon\b)",
            1,
        ),
        (
            r"(\btomorrow(?:\s+morning|\s+afternoon|\s+evening)?)",
            2,
        ),
    ]

    best_value: Optional[str] = None
    best_priority = 0
    for pattern, priority in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and priority > best_priority:
            best_value = match.group(1).strip()
            best_priority = priority
    return best_value


def _timeline_priority(value: Optional[str]) -> int:
    """Return a priority representing timeline specificity."""

    if not value:
        return 0
    lowered = value.lower()
    if re.search(
        rf"{_NUMBER_WORD}\s+(?:days?|weeks?|months?|years?)",
        lowered,
    ):
        return 3
    if "next" in lowered or "this" in lowered:
        return 2
    if any(
        phrase in lowered
        for phrase in ("as soon as possible", "asap", "immediately", "urgently")
    ):
        return 1
    return 1


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

_FEATURE_PATTERNS = {
    "payment gateway": [
        r"payment\s+gateway",
        r"online\s+payments?",
        r"accept\s+payments?",
        r"pay\s+online",
        r"\bpayments?\b",
    ],
    "checkout": [
        r"\bcheckout\b",
        r"shopping\s+cart\s+(?:and|/)\s+checkout",
    ],
    "order tracking": [
        r"order\s+tracking",
        r"delivery\s+tracking",
        r"shipment\s+tracking",
        r"track\s+(?:orders?|shipments?|deliveries)",
    ],
    "login": [
        r"user\s+login",
        r"customer\s+login",
        r"account\s+login",
        r"\blogin\b",
        r"\bsign\s*in\b",
    ],
    "admin panel": [
        r"admin\s+panel",
        r"admin\s+dashboard",
    ],
    "search": [
        r"product\s+search",
        r"\bsearch\b",
    ],
    "filters": [
        r"product\s+filters?",
        r"filter\s+products?",
        r"\bfilters?\b",
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
    "booking": [
        r"appointment\s+booking",
        r"session\s+booking",
        r"book(?:ing)?\s+sessions?",
        r"schedule\s+appointments?",
        r"\bbookings?\b",
    ],
    "online ordering": [
        r"online\s+ordering",
        r"order\s+online",
    ],
    "inventory": [
        r"\binventory\b",
    ],
    "analytics": [
        r"\banalytics\b",
    ],
}


def _extract_features(text: str) -> List[str]:
    """Extract commonly requested website features."""

    features: List[str] = []
    for feature, patterns in _FEATURE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                features.append(feature)
                break
    return features


# ---------------------------------------------------------------------------
# Business description
# ---------------------------------------------------------------------------

# Words that should never be treated as the start of a business description
# (they show up in "I have not decided..." / "I have around 300 products"
# style sentences that are NOT describing what the business is).
_DESCRIPTION_STOPWORDS = {
    "not", "no", "n't", "around", "about", "already", "also", "roughly",
    "approximately", "still", "just", "only",
}


def _clean_description(value: str) -> Optional[str]:
    value = value.strip()
    if not value:
        return None
    first_word = value.split()[0].lower()
    if first_word in _DESCRIPTION_STOPWORDS:
        return None
    return value


def _extract_business_description(text: str) -> Optional[str]:
    """Extract a concise business description."""

    patterns = [
        (
            r"(?:my\s+)?business\s+is\s+(?:a\s+|an\s+)?"
            r"([A-Za-z][A-Za-z\s&\-]{2,60}?)"
            r"(?:\s+business)?"
            r"(?:\s+with\b|\s+and\s+|\s*,|\s*\.|$)"
        ),
        (
            # Requires an explicit article so we never match "I have around
            # 300 products" or "I have not decided the timeline yet".
            r"i\s+(?:run|own|manage)\s+(?:a|an)\s+"
            r"([A-Za-z][A-Za-z\s&\-]{2,60}?)"
            r"(?:\s+with\b|\s+and\s+|\s*,|\s*\.|$)"
        ),
        (
            r"i\s+sell\s+"
            r"([A-Za-z][A-Za-z\s&\-]{2,60}?)"
            r"(?:\s+online\b|\s+with\b|\s+and\s+|\s*,|\s*\.|$)"
        ),
        (
            r"we\s+sell\s+"
            r"([A-Za-z][A-Za-z\s&\-]{2,60}?)"
            r"(?:\s+online\b|\s+with\b|\s+and\s+|\s*,|\s*\.|$)"
        ),
        (
            r"for\s+my\s+(?:a\s+|an\s+)?"
            r"([A-Za-z][A-Za-z\s&\-]{2,60}?)"
            r"\s+business\b"
        ),
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cleaned = _clean_description(match.group(1))
            if cleaned:
                return cleaned

    match = re.search(
        r"(?:business|company|store)\s+"
        r"(?:is|deals?\s+in|sells?)\s+"
        r"(?:a\s+|an\s+)?"
        r"([A-Za-z][A-Za-z\s&\-]{2,50})",
        text,
        re.IGNORECASE,
    )
    if match:
        cleaned = _clean_description(match.group(1))
        if cleaned:
            return cleaned

    return None


# ---------------------------------------------------------------------------
# Decision maker
# ---------------------------------------------------------------------------

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
        (
            r"(?:my|our)\s+"
            r"(brother|sister|partner|husband|wife|manager|boss|"
            r"co-founder|cofounder)\s+"
            r"(?:handles?|decides?|makes?\s+the\s+(?:final\s+)?decision)"
        ),
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Objections
# ---------------------------------------------------------------------------

# Topics that indicate the customer is expressing qualification-data
# uncertainty (e.g. "not sure about the number of products yet") rather
# than a genuine sales objection (price, trust, timing, quality...).
_QUALIFICATION_UNCERTAINTY_TOPICS = re.compile(
    r"\b(number\s+of\s+products?|products?|items?|skus?|timeline|budget|"
    r"features?|which\s+platform)\b",
    re.IGNORECASE,
)


def _extract_objections(text: str) -> List[str]:
    """Extract explicit customer objections."""

    objection_patterns = [
        (
            r"(?:i\s+am\s+concerned\s+about|"
            r"i'm\s+concerned\s+about)\s+([^.!?]+)"
        ),
        (r"(?:my\s+concern\s+is)\s+([^.!?]+)"),
        (r"(?:i\s+worry\s+about)\s+([^.!?]+)"),
        (r"(too\s+expensive)\b"),
        (r"(too\s+costly)\b"),
        (r"(?:not\s+sure\s+about)\s+([^.!?]+)"),
    ]
    objections: List[str] = []
    for pattern in objection_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            value = (
                " ".join(part for part in match if part)
                if isinstance(match, tuple)
                else match
            )
            value = value.strip()
            if not value:
                continue
            if _QUALIFICATION_UNCERTAINTY_TOPICS.search(value):
                # This is uncertainty about qualification data, not a
                # genuine sales objection -- skip it.
                continue
            if value not in objections:
                objections.append(value)
    return objections


# ---------------------------------------------------------------------------
# Merge
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

    budget = new.budget if new.budget is not None else existing.budget
    products = new.products if new.products is not None else existing.products
    product_count = (
        new.product_count
        if new.product_count is not None
        else existing.product_count
    )

    if existing.timeline and new.timeline:
        existing_priority = _timeline_priority(existing.timeline)
        new_priority = _timeline_priority(new.timeline)
        timeline = (
            new.timeline if new_priority >= existing_priority else existing.timeline
        )
    else:
        timeline = new.timeline or existing.timeline

    features = list(existing.features)
    for feature in new.features:
        if feature not in features:
            features.append(feature)

    business_description = (
        new.business_description
        if new.business_description is not None
        else existing.business_description
    )
    decision_maker = (
        new.decision_maker
        if new.decision_maker is not None
        else existing.decision_maker
    )

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
    return merge_qualification(existing, extracted)