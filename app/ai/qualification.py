"""
Lead qualification extraction.

Extracts information relevant to the e-commerce sales conversation.
The implementation is deterministic and provider-independent so it
can later be enhanced by an LLM.
"""

import re
from typing import List, Optional

from app.core.models import QualificationData


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "hundred": 100,
    "thousand": 1000,
}


def extract_budget(text: str) -> Optional[str]:
    """Extract a budget amount when one is mentioned."""

    patterns = [
        r"(?:₹|rs\.?|inr)\s*[\d,]+(?:\.\d+)?\s*(?:k|thousand|lakh|lac|cr)?",
        r"\b[\d,]+\s*(?:k|thousand|lakh|lac|crore|cr)\b",
        r"\b(?:budget|around|approximately|upto|up to)\s*(?:is|of)?\s*₹?\s*[\d,]+\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(0).strip()

    return None


def extract_product_count(text: str) -> Optional[int]:
    """Extract a product/item/SKU count."""

    digit_patterns = [
        r"\b(\d+)\s*(?:products?|items?|skus?)\b",
        r"\b(?:around|about|approximately)\s*(\d+)\s*(?:products?|items?|skus?)?\b",
    ]

    for pattern in digit_patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None

    for word, number in NUMBER_WORDS.items():
        pattern = (
            rf"\b{word}\s+"
            r"(?:hundred|thousand)?\s*"
            r"(?:products?|items?|skus?)\b"
        )

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return number

    return None


def extract_timeline(text: str) -> Optional[str]:
    """
    Extract natural-language project timelines.

    Handles both numeric and word-based expressions such as:
    "within 1 month", "within one month", "next month",
    "in two weeks", "tomorrow", and "ASAP".
    """

    patterns = [
        r"\bwithin\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
        r"\bwithin\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:days?|weeks?|months?|years?)\b",
        r"\bin\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
        r"\bin\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:days?|weeks?|months?|years?)\b",
        r"\bnext\s+(?:day|week|month|year)\b",
        r"\bthis\s+(?:week|month|year)\b",
        r"\b(?:tomorrow|today)\b",
        r"\basap\b",
        r"\burgently\b",
        r"\bimmediately\b",
        r"\bby\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(0).strip()

    return None


def extract_business_description(
    text: str,
) -> Optional[str]:
    """Extract a simple description of the customer's business."""

    patterns = [
        r"(?:for|from|in)\s+(?:my|our)\s+([a-zA-Z][a-zA-Z\s&-]{2,40})\s+business",
        r"(?:my|our)\s+business\s+(?:is|sells?)\s+([a-zA-Z][a-zA-Z\s&-]{2,50})",
        r"(?:I|we)\s+(?:sell|deal in|manufacture|make)\s+(.+?)(?:\.|,|$)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            value = match.group(1).strip()

            if value:
                return value

    return None


def extract_products(text: str) -> Optional[str]:
    """Extract what the customer sells."""

    patterns = [
        r"(?:I|we)\s+(?:sell|deal in|manufacture|make)\s+(.+?)(?:\.|,|$)",
        r"(?:selling|sell)\s+(.+?)(?:\.|,|$)",
        r"(?:products?\s+(?:are|include))\s+(.+?)(?:\.|,|$)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            value = match.group(1).strip()

            if value:
                return value

    return None


def extract_features(text: str) -> List[str]:
    """Extract common e-commerce features."""

    feature_patterns = {
        "payment gateway": r"\bpayment gateway\b",
        "online payments": r"\bonline payments?\b",
        "cart": r"\bshopping cart\b|\bcart\b",
        "checkout": r"\bcheckout\b",
        "product search": r"\bproduct search\b",
        "login": r"\blogin\b|\bsign ?in\b",
        "customer accounts": r"\bcustomer accounts?\b",
        "order tracking": r"\border tracking\b",
        "admin panel": r"\badmin panel\b|\badministrator\b",
        "inventory": r"\binventory\b",
        "delivery integration": r"\bdelivery integration\b",
        "shipping": r"\bshipping\b",
        "analytics": r"\banalytics\b",
        "coupons": r"\bcoupons?\b|\bpromo codes?\b",
        "reviews": r"\breviews?\b",
    }

    features = []

    for feature, pattern in feature_patterns.items():
        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            features.append(feature)

    return features


def extract_objections(text: str) -> List[str]:
    """Identify common customer barriers."""

    objections = []

    patterns = {
        "budget": (
            r"\btoo expensive\b|"
            r"\blow budget\b|"
            r"\bno budget\b|"
            r"\bbudget is low\b"
        ),
        "timing": (
            r"\bnot now\b|"
            r"\blater\b|"
            r"\bnot ready\b"
        ),
        "decision maker": (
            r"\bmy brother\b|"
            r"\bmy partner\b|"
            r"\bmy boss\b|"
            r"\bmy manager\b|"
            r"\bneed to ask\b"
        ),
        "uncertainty": (
            r"\bnot sure\b|"
            r"\bneed to think\b|"
            r"\bthinking about it\b"
        ),
    }

    for objection, pattern in patterns.items():
        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            objections.append(objection)

    return objections


def extract_qualification(
    text: str,
) -> QualificationData:
    """Extract qualification information from a customer message."""

    return QualificationData(
        budget=extract_budget(text),
        products=extract_products(text),
        product_count=extract_product_count(text),
        timeline=extract_timeline(text),
        features=extract_features(text),
        business_description=extract_business_description(text),
        objections=extract_objections(text),
    )


def merge_qualification(
    current: QualificationData,
    update: QualificationData,
) -> QualificationData:
    """Merge newly discovered information into existing data."""

    if update.budget:
        current.budget = update.budget

    if update.products:
        current.products = update.products

    if update.product_count is not None:
        current.product_count = update.product_count

    if update.timeline:
        current.timeline = update.timeline

    if update.business_description:
        current.business_description = (
            update.business_description
        )

    if update.decision_maker:
        current.decision_maker = update.decision_maker

    for feature in update.features:
        if feature not in current.features:
            current.features.append(feature)

    for objection in update.objections:
        if objection not in current.objections:
            current.objections.append(objection)

    return current