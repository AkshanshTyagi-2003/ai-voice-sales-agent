# datetime_parser.py
"""
Natural-language relative-datetime parsing.

Turns spoken phrasing like "call me back tomorrow morning" or
"ring me at 5pm" into a concrete datetime, anchored to a reference
time (normally "now" in the business's configured timezone).

This module was previously empty, which meant CallbackRequest.scheduled_for
was never populated by any caller -- NaturalLanguageCallbackScheduler in
app/actions/callback.py depends directly on parse_relative_datetime().

UPDATE: broadened to cover the natural-language phrases customers
actually use on a call ("I'll call you tonight at 9 PM", "the day
after tomorrow", "September 10", "at nine tonight", "5 in the
evening"), on top of what already worked. All previously-working
phrases keep producing the same result -- this only ADDS recognized
patterns, and adds a "day after tomorrow" check ahead of the plain
"tomorrow" check (a phrase like "the day after tomorrow" contains the
substring "tomorrow", so without that ordering it would have been
misread as +1 day instead of +2).
"""
import re
from datetime import datetime, timedelta, time as dtime
from typing import Optional

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

TIME_OF_DAY = {
    "morning": dtime(hour=9, minute=0),
    "afternoon": dtime(hour=14, minute=0),
    "evening": dtime(hour=18, minute=0),
    "night": dtime(hour=20, minute=0),
    "noon": dtime(hour=12, minute=0),
    "midday": dtime(hour=12, minute=0),
}

# Context words used ONLY to disambiguate a spelled-out hour that carries
# no am/pm of its own -- e.g. "call me at nine tonight" -> 9 must mean PM
# because "tonight" is in the sentence. Without one of these words present,
# a bare "at nine" is left unparsed rather than guessed at (see
# _extract_explicit_time).
_PM_CONTEXT_WORDS = ("tonight", "evening", "night")
_AM_CONTEXT_WORDS = ("morning",)

_MONTH_NAMES_PATTERN = "|".join(MONTHS.keys())
_ABSOLUTE_DATE_PATTERN_MONTH_FIRST = re.compile(
    r"\b(" + _MONTH_NAMES_PATTERN + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b"
)
_ABSOLUTE_DATE_PATTERN_DAY_FIRST = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTH_NAMES_PATTERN + r")\b"
)


def _next_weekday(base: datetime, target_weekday: int) -> datetime:
    days_ahead = (target_weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


def _combine(date_part: datetime, time_part: dtime) -> datetime:
    return date_part.replace(
        hour=time_part.hour, minute=time_part.minute, second=0, microsecond=0
    )


def _extract_explicit_time(lowered: str) -> Optional[dtime]:
    """
    Look for a specific clock time in the text, trying progressively
    looser patterns in order of confidence. Returns None if nothing
    safely parseable is found -- callers then fall back to the
    TIME_OF_DAY defaults (morning/evening/etc).
    """
    # 1. "9pm", "9:30 pm", "10 AM" -- unambiguous regardless of
    #    whatever else is in the sentence (this is the original,
    #    already-working pattern -- unchanged).
    clock_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    if clock_match:
        hour = int(clock_match.group(1))
        minute = int(clock_match.group(2) or 0)
        meridiem = clock_match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return dtime(hour=hour, minute=minute)

    # 2. "5 in the evening", "9 in the morning".
    descriptor_match = re.search(
        r"\b(\d{1,2})\s+in\s+the\s+(morning|afternoon|evening|night)\b",
        lowered,
    )
    if descriptor_match:
        hour = int(descriptor_match.group(1))
        descriptor = descriptor_match.group(2)
        if descriptor in ("evening", "night") and hour != 12:
            hour += 12
        elif descriptor == "afternoon" and hour < 12:
            hour += 12
        return dtime(hour=hour % 24, minute=0)

    # 3. Spelled-out hour with no am/pm of its own ("at nine tonight").
    #    Only trusted when a morning/evening/night/tonight context word
    #    is ALSO present in the sentence -- a bare "call me at nine"
    #    with nothing else is too ambiguous and is deliberately left
    #    unparsed rather than guessed at.
    word_match = re.search(
        r"\bat\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b"
        r"(?:\s*o'?clock)?",
        lowered,
    )
    if word_match:
        hour = WORD_NUMBERS[word_match.group(1)]
        if any(word in lowered for word in _PM_CONTEXT_WORDS):
            if hour != 12:
                hour += 12
            return dtime(hour=hour, minute=0)
        if any(word in lowered for word in _AM_CONTEXT_WORDS):
            if hour == 12:
                hour = 0
            return dtime(hour=hour, minute=0)
        return None

    return None


def _extract_absolute_date(lowered: str, now: datetime) -> Optional[datetime]:
    """
    "September 10", "10 September", "10th September" -> a datetime at
    midnight on that date. Year is inferred: this year, or next year
    if that month/day has already passed relative to `now`. Returns
    None if no month name is present in the text at all.
    """
    match = _ABSOLUTE_DATE_PATTERN_MONTH_FIRST.search(lowered)
    if match:
        month_name, day_num = match.group(1), int(match.group(2))
    else:
        match = _ABSOLUTE_DATE_PATTERN_DAY_FIRST.search(lowered)
        if not match:
            return None
        day_num, month_name = int(match.group(1)), match.group(2)

    month_num = MONTHS[month_name]

    try:
        candidate_date = now.replace(
            month=month_num, day=day_num, hour=0, minute=0, second=0, microsecond=0
        )
    except ValueError:
        # Invalid day for that month (e.g. "February 30") -- not
        # safely parseable, so don't guess.
        return None

    if candidate_date.date() < now.date():
        try:
            candidate_date = candidate_date.replace(year=now.year + 1)
        except ValueError:
            return None

    return candidate_date


def parse_relative_datetime(
    text: str, reference: Optional[datetime] = None
) -> Optional[datetime]:
    if not text:
        return None
    lowered = text.strip().lower()
    now = reference or datetime.now()

    # "in an hour" / "in 3 hours" / "in 20 minutes" are absolute
    # offsets from now regardless of anything else in the sentence --
    # resolve and return immediately (unchanged from before).
    if re.search(r"\bin\s+(an?\s+)?hour\b", lowered):
        return now + timedelta(hours=1)
    hours_match = re.search(r"\bin\s+(\d+)\s+hours?\b", lowered)
    if hours_match:
        return now + timedelta(hours=int(hours_match.group(1)))
    minutes_match = re.search(r"\bin\s+(\d+)\s+minutes?\b", lowered)
    if minutes_match:
        return now + timedelta(minutes=int(minutes_match.group(1)))

    explicit_time = _extract_explicit_time(lowered)

    day_offset_date = None
    # True only when the date came from a bare "today"/"tonight" (as
    # opposed to an explicit weekday/absolute date/tomorrow) -- this is
    # what decides whether we're allowed to roll the result forward a
    # day if the resolved time has already passed today.
    is_explicit_today = False

    absolute_date = _extract_absolute_date(lowered, now)
    if absolute_date is not None:
        day_offset_date = absolute_date
    elif re.search(r"\bday\s+after\s+tomorrow\b", lowered):
        day_offset_date = now + timedelta(days=2)
    elif "tomorrow" in lowered:
        day_offset_date = now + timedelta(days=1)
    else:
        for idx, day in enumerate(DAYS):
            if re.search(rf"\b{day}\b", lowered):
                day_offset_date = _next_weekday(now, idx)
                break
        if day_offset_date is None and (
            "today" in lowered or "tonight" in lowered
        ):
            day_offset_date = now
            is_explicit_today = True

    time_of_day = explicit_time
    if time_of_day is None:
        for phrase, t in TIME_OF_DAY.items():
            if phrase in lowered:
                time_of_day = t
                break

    if day_offset_date is None and time_of_day is None:
        return None

    base_date = day_offset_date if day_offset_date is not None else now
    chosen_time = time_of_day if time_of_day is not None else TIME_OF_DAY["morning"]
    candidate = _combine(base_date, chosen_time)

    if (day_offset_date is None or is_explicit_today) and candidate <= now:
        candidate += timedelta(days=1)

    return candidate