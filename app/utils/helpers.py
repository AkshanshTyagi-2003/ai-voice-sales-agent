"""
General application helpers.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any


def generate_id(prefix: str = "") -> str:
    """Generate a unique identifier."""
    value = uuid.uuid4().hex

    if prefix:
        return f"{prefix}_{value}"

    return value


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def normalize_phone_number(phone_number: str) -> str:
    """
    Normalize a phone number while preserving the country code.

    The function removes spaces, brackets, hyphens and other
    formatting characters.
    """
    if not phone_number:
        return ""

    cleaned = re.sub(r"[^\d+]", "", phone_number)

    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    return cleaned


def safe_text(value: Any) -> str:
    """Convert a value to clean text."""
    if value is None:
        return ""

    return str(value).strip()


def truncate_text(text: str, max_length: int = 500) -> str:
    """Limit text to a maximum length."""
    text = safe_text(text)

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def merge_unique_strings(
    existing: list[str],
    new_items: list[str],
) -> list[str]:
    """Merge string lists while preserving insertion order."""
    result = list(existing)

    for item in new_items:
        cleaned = safe_text(item)

        if cleaned and cleaned not in result:
            result.append(cleaned)

    return result