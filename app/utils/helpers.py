# helpers.py
"""
General application helpers.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


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


# ---------------------------------------------------------------------------
# Language detection (Hindi / Hinglish / English)
# ---------------------------------------------------------------------------
# EXTENSION (multilingual support): the Retell agent itself already talks
# to the customer in whichever of English/Hindi they choose (that's
# configured directly on the Retell agent -- see README). This backend's
# job is separate: it needs to know which language a given customer turn
# was in so that OUR generated WhatsApp copy (app/actions/whatsapp.py)
# can follow the customer's current language, per doc2 sections 1/10
# ("Language must only affect how the conversation is expressed... If the
# conversation was Hindi: send the follow-up in Hindi.").
#
# This is intentionally simple, consistent with the rest of the
# qualification/intent layer (regex/keyword based, not a full language-ID
# model) -- see app/ai/intent.py, app/ai/qualification.py.

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Common Hindi function/marker words as commonly romanized (Latin script).
# Requiring TWO of these in the same turn (or one very unambiguous one) is
# enough to call a Latin-script message "Hinglish" without being fooled by
# an occasional Indian-English loanword inside an otherwise English
# sentence.
_HINGLISH_MARKERS = {
    "hai", "hain", "hoon", "hun", "ho", "tha", "thi", "the",
    "hum", "aap", "aapka", "aapke", "aapko", "mera", "meri", "mere",
    "mujhe", "humein", "humko", "kya", "kaise", "kab", "kahan", "kyun",
    "kyu", "chahiye", "karna", "karo", "kar", "kijiye", "kijiyega",
    "abhi", "baad", "baje", "kal", "aaj", "parso", "raat", "subah",
    "subha", "dopahar", "shaam", "sham", "hafte", "hafton", "mahine",
    "din", "paisa", "paise", "rupaye", "rupiya", "lakh", "hazar",
    "wala", "wale", "wali", "nahi", "nahin", "haan", "ji", "bhai",
    "yaar", "theek", "thik", "matlab", "bata", "batao", "dekho",
    "lena", "dena", "milega", "milegi", "chalo", "bilkul", "banwani",
    "karunga", "karenge", "sakte", "chahta", "chahti",
}

# A short list of especially unambiguous markers: a single occurrence of
# one of these is already a strong enough signal on its own (unlike
# something like "ji", which is common enough as a name suffix to want
# corroboration).
_HINGLISH_STRONG_MARKERS = {"hai", "hain", "chahiye", "karna", "kijiye", "banwani"}


def detect_language(text: str) -> Optional[str]:
    """
    Best-effort detection of which language a single customer turn is in.

    Returns:
        "hi"        - Hindi written in Devanagari script.
        "hinglish"  - Hindi written in Latin script, mixed with English
                      (the common spoken style -- see app/ai/prompts.py).
        "en"        - English, or nothing else was detected.
        None        - Not enough signal in this turn to decide (e.g. a
                      bare number, "yes", a name). Callers should keep
                      whatever language was already recorded (e.g.
                      Lead.language) rather than overwrite it with this.

    This only decides which language OUR generated WhatsApp copy should
    use -- Retell's own STT/LLM already handles the real language
    understanding and speech on the live call itself.
    """
    if not text:
        return None

    stripped = text.strip()
    if not stripped:
        return None

    if _DEVANAGARI_RE.search(stripped):
        return "hi"

    words = re.findall(r"[a-zA-Z']+", stripped.lower())
    if not words:
        return None

    hinglish_hits = sum(1 for w in words if w in _HINGLISH_MARKERS)

    if hinglish_hits >= 2:
        return "hinglish"

    if hinglish_hits == 1 and any(w in _HINGLISH_STRONG_MARKERS for w in words):
        return "hinglish"

    if len(words) >= 3:
        return "en"

    return None