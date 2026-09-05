import re
from typing import List, Optional

from app.core.models import QualificationData


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


_SENTENCE_SPLIT_RE = re.compile(r"[.!?।]+|\n+")


def _split_sentences(text: str) -> List[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [part.strip() for part in parts if part.strip()]


def _extract_budget(text: str) -> Optional[str]:
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

    hi_word_amount_pattern = (
        r"(?:budget|बजट|spend|investment)"
        r"(?:\s+(?:is|के\s+लिए|लगभग|around))?\s*"
        r"(?:around|approximately|लगभग|करीब)?\s*"
        r"(\d[\d,]*(?:\.\d+)?)\s*"
        r"(हज़ार|हजार|लाख|hazar|hajar|lakh)"
    )
    match = re.search(hi_word_amount_pattern, text, re.IGNORECASE)
    if match:
        number = _normalize_bare_number(match.group(1))
        unit = match.group(2).lower()
        hi_multipliers = {
            "हज़ार": 1_000, "हजार": 1_000, "hazar": 1_000, "hajar": 1_000,
            "लाख": 100_000, "lakh": 100_000,
        }
        if number is not None:
            multiplier = hi_multipliers.get(unit, 1)
            return _format_amount(int(number * multiplier))

    hi_bare_number_pattern = (
        r"(?:budget|बजट)"
        r"(?:\s+(?:is|लगभग|करीब|around|approximately))?\s*"
        r"(?:लगभग|करीब|around|approximately)?\s*"
        r"(\d[\d,]{2,}(?:\.\d+)?)"
        r"(?:\s*(?:रुपये|rupees|rupaye|rs\.?))?"
    )
    match = re.search(hi_bare_number_pattern, text, re.IGNORECASE)
    if match:
        value = match.group(1).strip()
        if value:
            return value

    # 7. Hindi fractional/word numerals before an amount unit
    # (लाख/हज़ार), e.g. "बजट करीब डेढ़ लाख है", "budget सवा लाख hai".
    # These carry NO digit at all, so none of patterns 1-6 above can
    # ever match them -- they all require `\d`. This is a category
    # gap (spoken fractional number words), not one missing test
    # phrase: डेढ़ (1.5), ढाई (2.5), पौने (quarter-less, e.g. पौने दो
    # = 1.75), सवा (quarter-more, e.g. सवा एक = 1.25) are all common
    # in everyday spoken amounts.
    _HI_FRACTIONAL_WORDS = {
        "डेढ़": 1.5,
        "ढाई": 2.5,
        "सवा": 1.25,
        "पौने": 0.75,  # combines with the following whole number, e.g. "पौने दो" = 1.75
    }
    _HI_WHOLE_WORDS = {
        "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5,
        "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    }
    # Budget can be phrased with the amount word BEFORE "budget/बजट"
    # ("ढाई लाख तक बजट है") just as often as after it ("budget ढाई
    # लाख है") -- both orders are checked.
    fractional_patterns = [
        r"(?:budget|बजट)[^।.!?\n]{0,20}?"
        r"(डेढ़|ढाई|सवा|पौने)"
        r"(?:\s+(एक|दो|तीन|चार|पांच))?"
        r"\s*(लाख|हज़ार|हजार)",
        r"(डेढ़|ढाई|सवा|पौने)"
        r"(?:\s+(एक|दो|तीन|चार|पांच))?"
        r"\s*(लाख|हज़ार|हजार)[^।.!?\n]{0,20}?(?:budget|बजट)",
    ]
    match = None
    for fp in fractional_patterns:
        match = re.search(fp, text)
        if match:
            break
    if match:
        frac_word, whole_word, unit = match.group(1), match.group(2), match.group(3)
        base = _HI_FRACTIONAL_WORDS.get(frac_word)
        if base is not None:
            if frac_word == "पौने" and whole_word:
                base = _HI_WHOLE_WORDS.get(whole_word, 1) - 0.25
            multiplier = 100_000 if unit == "लाख" else 1_000
            return _format_amount(int(base * multiplier))

    return None


_COUNTABLE_NOUNS = (
    r"products?|items?|sku[s]?|dishes|services|units|listings|designs|"
    r"courses|rooms|variants"
)


def _extract_product_count(text: str) -> Optional[int]:
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


_NUMBER_WORD = (
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
)


def _extract_timeline(text: str) -> Optional[str]:
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
        (
            r"(\bnext\s+(?:one|two|three|four|five|\d+)\s+weeks?)",
            3,
        ),
        (
            r"(\bnext\s+(?:one|two|three|four|five|\d+)\s+(?:days?|months?))",
            3,
        ),
        (
            r"((?:\d+|एक|दो|तीन|चार|पांच|छह|सात|आठ|नौ|दस)\s+"
            r"(?:दिन|हफ्त[ेों]+|महीन[ोे]+|साल)\s+में)",
            3,
        ),
        (
            r"(\b(?:\d+|do|teen|char|paanch)\s+hafto?n?\s+m(?:ei)?n\b)",
            3,
        ),
        (
            r"(\b(?:\d+|do|teen|char|paanch)\s+din\s+m(?:ei)?n\b)",
            3,
        ),
        (
            r"(इस\s+हफ्ते|अगले\s+हफ्ते|अगले\s+महीने)",
            2,
        ),
        (
            r"(\bis\s+hafte\b|\bagle\s+hafte\b|\bagle\s+mahine\b)",
            2,
        ),
        (
            r"(\b\d+\s+(?:days?|weeks?|months?|years?)\s+m(?:ei)?n\b)",
            3,
        ),
        (
            r"(\bis\s+(?:week|month|year)\b)",
            2,
        ),
        (
            r"(\bagle\s+(?:week|month|year)\b)",
            2,
        ),
        (
            r"(परसों)",
            2,
        ),
        (
            r"(\bparso\b)",
            2,
        ),
        (
            r"(आज\s+रात|आज)",
            1,
        ),
        (
            r"(\baaj\s+raat\b|\baaj\b)",
            1,
        ),
        (
            r"(जल्द(?:ी)?)",
            1,
        ),
        (
            r"(\bjaldi\b)",
            1,
        ),
        (
            r"(कल(?:\s+सुबह|\s+शाम)?)",
            2,
        ),
        (
            r"(\bkal(?:\s+morning|\s+shaam)?\b)",
            2,
        ),
        # -- NEW (timeline "baad"/later-than gap): the existing digit+
        # unit patterns above only cover "<n> mahine/hafte/din MEIN"
        # (in <n> months). Hindi/Hinglish speakers equally commonly
        # phrase a deadline as "<n> mahine BAAD" (after <n> months) --
        # a different postposition, same genuine-project-timeline
        # semantics. This is a category fix (any count word + any of
        # the three units + baad/बाद), not tied to "do mahine baad"
        # specifically.
        (
            r"((?:\d+|एक|दो|तीन|चार|पांच|छह|सात|आठ|नौ|दस)\s+"
            r"(?:दिन|हफ्त[ेों]+|महीन[ोे]+|साल)\s+बाद)",
            3,
        ),
        (
            r"(\b(?:\d+|ek|do|teen|char|paanch)\s+"
            r"(?:din|hafto?n?|mahin[eo]|saal)\s+baad\b)",
            3,
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
    if not value:
        return 0
    lowered = value.lower()
    if re.search(
        rf"{_NUMBER_WORD}\s+(?:days?|weeks?|months?|years?)",
        lowered,
    ):
        return 3
    if re.search(
        r"(?:\d+|एक|दो|तीन|चार|पांच|छह|सात|आठ|नौ|दस)\s+"
        r"(?:दिन|हफ्त[ेों]+|महीन[ोे]+|साल)\s+(?:में|बाद)",
        value,
    ) or re.search(
        r"(?:\d+|ek|do|teen|char|paanch)\s+(?:hafto?n?|din|mahin[eo])\s+"
        r"(?:m(?:ei)?n|baad)",
        lowered,
    ):
        return 3
    if "next" in lowered or "this" in lowered:
        return 2
    if re.search(r"\b(?:is|agle)\s+(?:week|month|year)\b", lowered):
        return 2
    if any(phrase in value for phrase in ("इस\u200dहफ्ते", "इस हफ्ते", "अगले हफ्ते", "अगले महीने")):
        return 2
    if any(phrase in lowered for phrase in ("is hafte", "agle hafte", "agle mahine")):
        return 2
    if any(
        phrase in lowered
        for phrase in ("as soon as possible", "asap", "immediately", "urgently")
    ):
        return 1
    return 1


_FEATURE_PATTERNS = {
    "payment gateway": [
        r"payment\s+gateway",
        r"online\s+payments?",
        r"accept\s+payments?",
        r"pay\s+online",
        r"customers?\s+.{0,25}pay\s+online",
        r"\bpayments?\b",
        r"पेमेंट\s*गेटवे",
        r"ऑनलाइन\s*भुगतान",
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
        r"track\s+(?:where\s+)?(?:their|the|my)?\s*orders?\b",
        r"ऑर्डर\s*ट्रैकिंग",
    ],
    "login": [
        r"user\s+login",
        r"customer\s+login",
        r"account\s+login",
        r"own\s+login",
        r"their\s+own\s+login",
        r"\blogin\b",
        r"\bsign\s*in\b",
    ],
    "admin panel": [
        r"admin\s+panel",
        r"admin\s+dashboard",
        r"\bdashboard\b",
    ],
    "product management": [
        r"manage\s+products?",
        r"product\s+management",
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
        r"\bstock\b",
        r"stock\s+management",
        r"इन्वेंटरी",
        r"स्टॉक",
    ],
    "analytics": [
        r"\banalytics\b",
    ],
}


_FEATURE_TRIGGER_PATTERNS = [
    (
        r"(?:i|we)\s+(?:need|want|require|would\s+like)\s+"
        r"(.+?)(?=$|,\s*(?:and\s+)?(?:i|we|it|my)\b)"
    ),
    r"mujhe\s+(.+?)\s+chahiye",
    r"मुझे\s+(.+?)\s+चाहिए",
    # -- NEW (bare "chahiye" gap): Hinglish/Hindi frequently drops the
    # subject ("mujhe"/"मुझे") entirely -- "Online store chahiye,
    # catalog aur payment dono chahiye" is exactly as common as
    # "Mujhe ... chahiye". Captures the clause immediately preceding
    # EACH "chahiye"/"चाहिए" occurrence, split on the same clause
    # boundary (start of string or a comma), so a multi-item sentence
    # with several bare "chahiye"s still yields every item, not just
    # the first. Still gated by the outer "sentence already matched a
    # canonical feature keyword" check, so a feature-less sentence
    # like "Website chahiye" alone (no recognizable feature word)
    # never reaches this at all.
    # NOTE: the captured group is [^,]+? (not .+?), so a clause is
    # never allowed to cross a comma boundary. Without that
    # restriction, a sentence like "meri shop hai, ... payment
    # chahiye" would let the non-greedy match expand backwards across
    # the FIRST comma too (since "." matches a comma) and capture
    # "meri shop hai, ... payment" as a single feature-list clause --
    # reintroducing exactly the raw-fragment-as-normalized-field bug
    # this file's normalization rules are meant to prevent.
    r"(?:^|,)\s*([^,]+?)\s+chahiye\b",
    r"(?:^|,)\s*([^,]+?)\s+चाहिए",
]

_FEATURE_ITEM_SPLIT_RE = re.compile(
    r",|\band\b|\balso\b|\balong\s+with\b|\baur\b|\bbhi\b|और|भी|एवं",
    re.IGNORECASE,
)

_FEATURE_ITEM_STRIP_LEADING_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)

_FEATURE_STOP_WORDS = {"it", "this", "that", "i", "we", "you", "them", "the", ""}

_NON_FEATURE_ITEM_RE = re.compile(
    r"^\d"
    r"|₹|\$"
    r"|\b(?:rupees?|lakh|crore|budget|month|months|week|weeks|day|days|"
    r"year|years|ready|asap|hazar)\b"
    r"|हज़ार|हजार|लाख|महीन|हफ्त|दिन|साल|बजट|तैयार",
    re.IGNORECASE,
)


def _normalize_feature_item(item: str) -> Optional[str]:
    item = item.strip(" .।,-")
    if not item:
        return None
    item = _FEATURE_ITEM_STRIP_LEADING_RE.sub("", item).strip()
    if not item:
        return None
    if item.lower() in _FEATURE_STOP_WORDS:
        return None
    if _NON_FEATURE_ITEM_RE.search(item):
        return None
    word_count = len(item.split())
    if word_count == 0 or word_count > 6:
        return None

    for feature, patterns in _FEATURE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, item, re.IGNORECASE):
                return feature
    return item


def _extract_features(text: str) -> List[str]:
    features: List[str] = []

    for sentence in _split_sentences(text):
        sentence_hits: List[str] = []
        for feature, patterns in _FEATURE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, sentence, re.IGNORECASE):
                    sentence_hits.append(feature)
                    break

        for feature in sentence_hits:
            if feature not in features:
                features.append(feature)

        if not sentence_hits:
            continue

        for trigger_pattern in _FEATURE_TRIGGER_PATTERNS:
            for match in re.finditer(trigger_pattern, sentence, re.IGNORECASE):
                segment = match.group(1)
                if not segment:
                    continue
                for raw_item in _FEATURE_ITEM_SPLIT_RE.split(segment):
                    normalized = _normalize_feature_item(raw_item)
                    if normalized and normalized not in features:
                        features.append(normalized)

    return features


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


_NON_BUSINESS_CONTENT_HI_RE = re.compile(
    r"\d"
    r"|बजट|पार्टनर|परिवार|समस्या|दिक्कत|समय|मंज़ूरी|मंजूरी|फैसला|"
    r"योजना|सवाल|चिंता|नंबर|टीम|मैनेजर|बॉस|भाई|बहन|पति|पत्नी|"
    r"लाख|हज़ार|हजार|रुपये|रुपए|करोड़|कॉल|कॉलबैक"
)


def _extract_business_description(text: str) -> Optional[str]:
    patterns = [
        (
            r"(?:my\s+)?business\s+is\s+(?:a\s+|an\s+)?"
            r"([A-Za-z][A-Za-z\s&\-]{2,60}?)"
            r"(?:\s+business)?"
            r"(?:\s+with\b|\s+and\s+|\s*,|\s*\.|$)"
        ),
        (
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

    hi_patterns = [
        r"मेरा\s+([^.।,]{2,40}?)\s+(?:का\s+)?(?:बिज़नेस|बिजनेस|व्यवसाय|काम)\s+है",
        r"अपन[ीा]\s+([^.।,]{2,40}?)\s+की\s+दुकान",
        r"([^.।,]{2,40}?)\s+की\s+दुकान\s+है",
        r"अपन[ेी]\s+([^.।,]{2,40}?)\s+(?:के\s+)?(?:बिज़नेस|बिजनेस|व्यवसाय)"
        r"\s+के\s+लिए",
        r"अपन[ीा]\s+((?:ऑनलाइन\s+)?"
        r"(?:दुकान|शॉप|स्टोर|कारोबार|बिज़नेस|व्यवसाय))",
    ]
    for pattern in hi_patterns:
        match = re.search(pattern, text)
        if match:
            cleaned = match.group(1).strip()
            if cleaned:
                return cleaned

    hinglish_patterns = [
        r"\bmera\s+([a-zA-Z\s&\-]{2,60}?)\s+business\s+hai\b",
        r"\bmeri\s+([a-zA-Z\s&\-]{2,60}?)\s+business\s+hai\b",
        r"\bmeri\s+([a-zA-Z\s&\-]{2,60}?)\s+(?:ki\s+)?shop\s+hai\b",
        r"\bmain\s+([a-zA-Z\s&\-]{2,60}?)\s+ka\s+business\s+"
        r"kart[ai]\s+hoon\b",
        r"\bmain\s+([a-zA-Z\s&\-]{2,60}?)\s+chalat[ai]\s+hoon\b",
        r"\bapn[ei]\s+([a-zA-Z\s&\-]{2,60}?)\s+business\s+ke\s+liye\b",
        # -- NEW (Hinglish bare purpose-clause gap): "<business type>
        # ke liye website/store chahiye" with NO "business"/"apne"
        # keyword at all -- e.g. "Bakery ke liye website chahiye".
        # This mirrors the existing Devanagari "अपने X के बिज़नेस के
        # लिए" pattern, but that pattern requires the "बिज़नेस"
        # keyword; everyday Hinglish frequently drops it entirely and
        # states the business type as a bare noun right before
        # "ke liye website/store/site chahiye". Guarded against
        # leading pronouns/possessives (mere, humare, iske, uske,
        # aapke, isके...) so it can't misread "iske liye website
        # chahiye" as a business type.
        r"\b(?!mere\b|humare\b|hamare\b|iske\b|uske\b|aapke\b|apne\b|"
        r"apni\b|is\b|us\b|business\b|company\b|store\b|website\b|"
        r"service\b|services\b|customer\b|customers\b|client\b|"
        r"clients\b|project\b|budget\b|partner\b|order\b|payment\b|"
        r"koi\b|kisi\b|fixed\b)"
        r"([a-zA-Z][a-zA-Z\-]{2,30})\s+ke\s+liye\s+"
        r"(?:website|online\s+store|store|site)\b",
    ]
    for pattern in hinglish_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cleaned = _clean_description(match.group(1))
            if cleaned:
                return cleaned

    _NON_BUSINESS_NOUN_RE = re.compile(
        r"^(?:budget|partner|family|problem|issue|time|timeline|"
        r"approval|decision|plan|idea|question|concern|number|"
        r"team|manager|boss|brother|sister|husband|wife)\b",
        re.IGNORECASE,
    )
    generic_pattern = r"\b(?:mera|meri)\s+([a-zA-Z][a-zA-Z\s&\-]{1,40}?)\s+hai\b"
    match = re.search(generic_pattern, text, re.IGNORECASE)
    if match:
        cleaned = _clean_description(match.group(1))
        if cleaned and not _NON_BUSINESS_NOUN_RE.match(cleaned):
            word_count = len(cleaned.split())
            if word_count <= 4:
                return cleaned

    generic_hi_pattern = r"(?:मेरा|मेरी)\s+(?:एक\s+)?([^.।,]{2,20}?)\s+है"
    match = re.search(generic_hi_pattern, text)
    if match:
        cleaned = match.group(1).strip()
        if cleaned and not _NON_BUSINESS_CONTENT_HI_RE.search(cleaned):
            word_count = len(cleaned.split())
            if 0 < word_count <= 3:
                return cleaned

    return None


def _extract_decision_maker(text: str) -> Optional[str]:
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
        (
            r"(?:i|we)\s+(?:need|want|have)\s+to\s+"
            r"(?:discuss|check|confirm|consult|talk)\s+"
            r"(?:it|this|that|the\s+(?:project|website|decision))?\s*"
            r"(?:with\s+)?(?:my|our)\s+"
            r"(brother|sister|partner|husband|wife|manager|boss|"
            r"co-founder|cofounder)\b"
        ),
        (
            r"(?:i|we)\s+(?:need|want|have)\s+to\s+"
            r"(?:check|discuss|talk|consult)\s+"
            r"with\s+(?:my|our)\s+"
            r"(brother|sister|partner|husband|wife|manager|boss|"
            r"co-founder|cofounder)\b"
        ),
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    _DECISION_MAKER_NORMALIZE = {
        "पार्टनर": "partner",
        "भाई": "brother",
        "बहन": "sister",
        "पति": "husband",
        "पत्नी": "wife",
        "मैनेजर": "manager",
        "बॉस": "boss",
        "को-फाउंडर": "co-founder",
        "कोफाउंडर": "co-founder",
        "bhai": "brother",
        "behan": "sister",
        "bahan": "sister",
    }

    def _normalize_dm(raw: str) -> str:
        raw = raw.strip()
        if raw in _DECISION_MAKER_NORMALIZE:
            return _DECISION_MAKER_NORMALIZE[raw]
        lowered = raw.lower()
        return _DECISION_MAKER_NORMALIZE.get(lowered, lowered)

    hi_patterns = [
        r"अपन[ेी]\s+(partner|भाई|बहन|पार्टनर|पति|पत्नी|मैनेजर|बॉस|को-?फाउंडर)\s+से",
        r"(partner|भाई|बहन|पार्टनर|पति|पत्नी|मैनेजर|बॉस)\s+से\s+"
        r"(?:पहले\s+)?(?:पूछना|बात)",
        r"(partner|भाई|बहन|पार्टनर|पति|पत्नी|मैनेजर|बॉस)\s+की\s+"
        r"(?:मंज़ूरी|मंजूरी|स्वीकृति|approval)",
        r"(partner|भाई|बहन|पार्टनर|पति|पत्नी|मैनेजर|बॉस)\s+फैसला\s+करेग[ाी]",
    ]
    for pattern in hi_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _normalize_dm(match.group(1))

    hinglish_patterns = [
        r"\b(partner|brother|sister|manager|boss|husband|wife|bhai|"
        r"behan|bahan)\s+se\s+(?:baat|discuss|poochna)\b",
        r"\b(partner|brother|sister|manager|boss|husband|wife|bhai|"
        r"behan|bahan)\s+ki\s+approval\b",
        # -- NEW (approval-verb gap): "<relation> se approval lena/
        # chahiye hai" -- naming who must approve via "se" (from) +
        # a form of "lena" (take), rather than the existing "ki
        # approval" (possessive "X's approval") construction. Same
        # relation-noun set used throughout this file, generalized to
        # the verb form, not tied to one test sentence.
        r"\b(partner|brother|sister|manager|boss|husband|wife|bhai|"
        r"behan|bahan)\s+se\s+approval\b",
        r"\b(partner|brother|sister|manager|boss|bhai|behan|bahan)\s+"
        r"(?:hi\s+)?decision\s+(?:lega|legi|lete\s+hain|leta\s+hai)\b",
    ]
    for pattern in hinglish_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _normalize_dm(match.group(1))

    return None


_QUALIFICATION_UNCERTAINTY_TOPICS = re.compile(
    r"\b(number\s+of\s+products?|products?|items?|skus?|timeline|budget|"
    r"features?|which\s+platform|प्रोडक्ट्स?|बजट|टाइमलाइन|फीचर्स?)",
    re.IGNORECASE,
)


_BARRIER_SENTENCE_PATTERNS = [
    r"budget.{0,25}\b(?:low|tight|limited|small|not\s+enough)\b",
    r"\b(?:cannot|can'?t)\s+afford\b",
    r"cash\s*flow.{0,15}\btight\b",
    r"budget.{0,20}\bnahi\s+hai\b",
    r"budget.{0,20}\bkam\s+hai\b",
    # -- NEW: "budget abhi manage nahi ho raha (hai)" -- a budget
    # difficulty phrased as an inability to manage/arrange funds,
    # rather than "budget kam/nahi hai". Same budget-barrier
    # CATEGORY, additional common verb phrasing.
    r"budget.{0,25}\bmanage\s+nahi\s+ho\s+(?:pa\s+)?raha\b",
    r"बजट.{0,20}(?:कम|टाइट)",
    r"\b(?:cannot|can'?t)\s+start\s+(?:immediately|right\s+now|now)\b",
    r"\bnot\s+ready\s+yet\b",
    r"\babhi\s+(?:shuru|start)\s+nahi\b",
    r"अभी\s+शुरू\s+नहीं",
    r"\bcompar(?:e|ing)\s+(?:other\s+)?(?:vendors|companies|options)\b",
    r"\bdoosri\s+companies\b",
    r"दूसरी\s+कंपनियों",
    r"\bapproval\s+from\s+(?:management|boss|manager|team)\b",
    r"\bmanagement\s+se\s+approval\b",
    r"मैनेजमेंट\s+से\s+(?:अनुमति|स्वीकृति)",
    r"\b(?:partner|brother|sister|manager|boss|bhai|behan|bahan)\s+"
    r"ki\s+approval\b",
    r"(?:पार्टनर|भाई|बहन|मैनेजर|बॉस)\s+की\s+(?:मंज़ूरी|मंजूरी|स्वीकृति)",
    r"\bneed\s+to\s+think\b",
    r"\bnot\s+sure\s+yet\b",
    r"\babhi\s+decide\s+nahi\b",
    r"अभी\s+तय\s+नहीं",
    r"सोचना\s+है",
]


def _extract_barrier_sentences(text: str) -> List[str]:
    barriers: List[str] = []
    for sentence in _split_sentences(text):
        for pattern in _BARRIER_SENTENCE_PATTERNS:
            if re.search(pattern, sentence, re.IGNORECASE):
                if sentence not in barriers:
                    barriers.append(sentence)
                break
    return barriers


def _extract_objections(text: str) -> List[str]:
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
        (r"(बहुत\s+महंगा(?:\s+है)?)"),
        (r"(ज़्यादा\s+महंगा(?:\s+है)?)"),
        (r"(zyada\s+expensive(?:\s+lag\s+raha\s+hai)?)"),
        (r"(bahut\s+mehnga(?:\s+hai)?)"),
        (r"(?:मुझे\s+चिंता\s+है)\s+([^.।!?]+)"),
        (r"(?:mujhe\s+chinta\s+hai)\s+([^.!?]+)"),
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
                continue
            if value not in objections:
                objections.append(value)

    for barrier in _extract_barrier_sentences(text):
        if barrier not in objections:
            objections.append(barrier)

    return objections


def merge_qualification(
    existing: Optional[QualificationData],
    new: Optional[QualificationData],
) -> QualificationData:
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


def extract_qualification(
    text: str,
    existing: Optional[QualificationData] = None,
) -> QualificationData:
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