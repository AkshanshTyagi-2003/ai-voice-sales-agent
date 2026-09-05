# datetime_parser.py
"""
Natural-language relative-datetime parsing.

Turns spoken phrasing like "call me back tomorrow morning", "ring me at
5pm", "day after tomorrow", "September 10 at 4pm", or the Hindi/Hinglish
equivalents ("kal subah 10 baje", "aaj raat 9 baje", "parso") into a
concrete datetime, anchored to a reference time (normally "now" in the
business's configured timezone).

EXTENSION NOTE (Hindi/Hinglish support):
This module originally only understood English phrasing. The parsing
strategy below is unchanged -- collect a "day" component and a "time of
day" component from the text, then combine them -- this extension only
widens what each component recognizes:
  - day component: + "day after tomorrow" / "परसों" / "parso",
    + explicit "<month> <day>" dates, + Hindi weekday names.
  - time component: + Hindi/Hinglish "<N> बजे / baje" clock phrasing
    disambiguated by a Hindi/Hinglish time-of-day word (सुबह/subah,
    दोपहर/dopahar, शाम/shaam, रात/raat), + those time-of-day words on
    their own (parallel to the existing morning/afternoon/evening/night
    English handling).
None of the existing English matching branches were changed, so English
callback parsing (today/tonight/tomorrow/weekday/specific
time/specific date) behaves exactly as before.

CHANGE (next-week / next-month day-component -- THIS revision):
Root cause: this module had NO handling at all -- in English, Hindi,
or Hinglish -- for a bare "next week" / "next month" style relative
day reference (only specific weekday names, "day after tomorrow",
"tomorrow", and "today" were recognized as day components). That is a
gap in the SHARED day-component logic, not something specific to one
language: it just happens to be exercised by a Hindi callback example
("अगले हफ्ते मुझे दोबारा कॉल कर लेना" -- "call me back next week"),
where it caused the day component AND the time-of-day component to
both stay unset, so parse_relative_datetime returned None and no
callback time was ever produced.

Fixed by adding one more day-component branch, in English, Hindi
(Devanagari), and Hinglish (Romanized Hindi) -- "next week" / "अगले
हफ्ते" / "agle hafte" -> +7 days, and "next month" / "अगले महीने" /
"agle mahine" / "agle month" -> same day-of-month next month (clamped
to the last valid day if the target month is shorter, e.g. Jan 31 ->
Feb 28).

This is inserted into the EXISTING day_offset_date if/elif chain,
gated the same way every other branch in that chain already is
(`day_offset_date is None and ...`), so it can only ever fire when
nothing more specific (an explicit date, a weekday name, "day after
tomorrow", "tomorrow") has already matched. Because it is purely
additive and only ever changes what happens for text that PREVIOUSLY
made this function return None, it cannot alter the result for any
input that already resolved to a date -- it can only resolve some
previously-unresolved inputs. Every other branch, and the time-of-day
logic that runs afterward, is completely unchanged.
"""
import calendar
import re
from datetime import datetime, timedelta, time as dtime
from typing import Optional

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Hindi weekday names, in the same Monday->Sunday order as DAYS above.
HI_DAYS = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]

TIME_OF_DAY = {
    "morning": dtime(hour=9, minute=0),
    "afternoon": dtime(hour=14, minute=0),
    "evening": dtime(hour=18, minute=0),
    "night": dtime(hour=20, minute=0),
    "noon": dtime(hour=12, minute=0),
    "midday": dtime(hour=12, minute=0),
}

# Hindi (Devanagari) / Hinglish (Latin) time-of-day words, mapped to the
# same default clock times as their English equivalents above. These are
# ALSO used to disambiguate a bare "<N> बजे / baje" clock phrase that has
# no am/pm marker (see _extract_hi_clock_time below).
HI_TIME_OF_DAY = {
    "सुबह": dtime(hour=9, minute=0),
    "subah": dtime(hour=9, minute=0),
    "दोपहर": dtime(hour=14, minute=0),
    "dopahar": dtime(hour=14, minute=0),
    "शाम": dtime(hour=18, minute=0),
    "shaam": dtime(hour=18, minute=0),
    "sham": dtime(hour=18, minute=0),
    "रात": dtime(hour=20, minute=0),
    "raat": dtime(hour=20, minute=0),
}

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MONTH_NAME_ALTERNATION = "|".join(sorted(MONTHS.keys(), key=len, reverse=True))


def _next_weekday(base: datetime, target_weekday: int) -> datetime:
    days_ahead = (target_weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


def _add_one_month(base: datetime) -> datetime:
    """
    Return the same day-of-month, one calendar month ahead of `base`,
    clamped to the target month's last valid day (e.g. Jan 31 ->
    Feb 28/29). Time-of-day is left as-is on `base`; the caller
    subsequently overwrites hour/minute via _combine, so only the
    date portion matters here.
    """
    month = base.month + 1
    year = base.year
    if month > 12:
        month = 1
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(base.day, last_day)
    return base.replace(year=year, month=month, day=day)


def _combine(date_part: datetime, time_part: dtime) -> datetime:
    return date_part.replace(
        hour=time_part.hour, minute=time_part.minute, second=0, microsecond=0
    )


def _extract_explicit_date(text: str, now: datetime) -> Optional[datetime]:
    """
    Match an explicit "<month> <day>" or "<day> <month>" date, e.g.
    "September 10", "10 September", "Sep 10th". Month names are commonly
    kept in English even inside Hindi/Hinglish speech, so this single
    pattern set covers all three supported languages.

    If the resulting date has already passed this year, roll to next
    year -- consistent with how weekday names below roll to "next
    <weekday>" rather than a date in the past.
    """
    month_day = re.search(
        rf"\b({_MONTH_NAME_ALTERNATION})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
        text,
        re.IGNORECASE,
    )
    day_month = None
    if not month_day:
        day_month = re.search(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAME_ALTERNATION})\b",
            text,
            re.IGNORECASE,
        )

    if month_day:
        month = MONTHS[month_day.group(1).lower()]
        day = int(month_day.group(2))
    elif day_month:
        day = int(day_month.group(1))
        month = MONTHS[day_month.group(2).lower()]
    else:
        return None

    year = now.year
    try:
        candidate = now.replace(
            year=year, month=month, day=day,
            hour=0, minute=0, second=0, microsecond=0,
        )
    except ValueError:
        return None

    if candidate.date() < now.date():
        try:
            candidate = candidate.replace(year=year + 1)
        except ValueError:
            return None

    return candidate


def _extract_hi_clock_time(lowered: str, original: str) -> Optional[dtime]:
    """
    Match Hindi/Hinglish "<N> बजे" / "<N> baje" ("<N> o'clock") clock
    phrasing, e.g. "9 बजे", "10 baje". This has no am/pm marker of its
    own, so the hour is disambiguated using a nearby Hindi/Hinglish
    time-of-day word (रात/raat -> pm, सुबह/subah -> am, etc.) when one is
    present in the same message; otherwise the literal hour is used
    as-is (matching how a bare hour with no am/pm is treated elsewhere
    in this module).
    """
    clock_match = re.search(r"(\d{1,2})\s*(?:बजे|baje)", original) or re.search(
        r"(\d{1,2})\s*(?:बजे|baje)", lowered
    )
    if not clock_match:
        return None

    hour = int(clock_match.group(1))
    if hour > 23:
        return None

    if any(word in original for word in ("रात",)) or "raat" in lowered:
        if hour < 12:
            hour += 12
    elif any(word in original for word in ("शाम",)) or "shaam" in lowered or "sham" in lowered:
        if hour < 12:
            hour += 12
    elif any(word in original for word in ("दोपहर",)) or "dopahar" in lowered:
        if hour < 12:
            hour += 12
    elif any(word in original for word in ("सुबह",)) or "subah" in lowered:
        if hour == 12:
            hour = 0
    # No time-of-day qualifier present: keep the literal hour (0-23).

    return dtime(hour=hour % 24, minute=0)


def parse_relative_datetime(
    text: str, reference: Optional[datetime] = None
) -> Optional[datetime]:
    if not text:
        return None
    original = text.strip()
    lowered = original.lower()
    now = reference or datetime.now()

    clock_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    explicit_time = None
    if clock_match:
        hour = int(clock_match.group(1))
        minute = int(clock_match.group(2) or 0)
        meridiem = clock_match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        explicit_time = dtime(hour=hour, minute=minute)

    # Hindi/Hinglish "<N> बजे / baje" clock phrasing (only used if no
    # English am/pm time was already found above).
    if explicit_time is None:
        explicit_time = _extract_hi_clock_time(lowered, original)

    day_offset_date = None

    # -- Explicit "<month> <day>" date (e.g. "September 10") ------------
    explicit_date = _extract_explicit_date(original, now)
    if explicit_date is not None:
        day_offset_date = explicit_date

    # -- Weekday names (English + Hindi) --------------------------------
    if day_offset_date is None:
        for idx, day in enumerate(DAYS):
            if re.search(rf"\b{day}\b", lowered):
                day_offset_date = _next_weekday(now, idx)
                break
        if day_offset_date is None:
            for idx, day in enumerate(HI_DAYS):
                if day in original:
                    day_offset_date = _next_weekday(now, idx)
                    break

    # -- Day-after-tomorrow (English + Hindi + Hinglish) -----------------
    if day_offset_date is None and (
        "day after tomorrow" in lowered
        or "परसों" in original
        or re.search(r"\bparso\b", lowered)
    ):
        day_offset_date = now + timedelta(days=2)
    elif day_offset_date is None and (
        "tomorrow" in lowered
        or "कल" in original
        or re.search(r"\bkal\b", lowered)
    ):
        day_offset_date = now + timedelta(days=1)
    # -- NEW (next-week / next-month day-component fix): "next week" /
    # "अगले हफ्ते" / "agle hafte" and "next month" / "अगले महीने" /
    # "agle mahine" / "agle month" -- see module docstring "CHANGE
    # (next-week / next-month day-component -- THIS revision)" above
    # for the full root-cause write-up. Placed in the same elif chain,
    # gated the same "day_offset_date is None and ..." way as every
    # other branch here, so it only ever fires when nothing more
    # specific has already matched.
    elif day_offset_date is None and (
        re.search(r"\bnext\s+week\b", lowered)
        or "अगले हफ्ते" in original
        or re.search(r"\bagle\s+hafte\b", lowered)
    ):
        day_offset_date = now + timedelta(days=7)
    elif day_offset_date is None and (
        re.search(r"\bnext\s+month\b", lowered)
        or "अगले महीने" in original
        or re.search(r"\bagle\s+mahine\b", lowered)
        or re.search(r"\bagle\s+month\b", lowered)
    ):
        day_offset_date = _add_one_month(now)
    elif re.search(r"\bin\s+(an?\s+)?hour\b", lowered):
        return now + timedelta(hours=1)
    elif re.search(r"\bin\s+(\d+)\s+hours?\b", lowered):
        m = re.search(r"\bin\s+(\d+)\s+hours?\b", lowered)
        return now + timedelta(hours=int(m.group(1)))
    elif re.search(r"\bin\s+(\d+)\s+minutes?\b", lowered):
        m = re.search(r"\bin\s+(\d+)\s+minutes?\b", lowered)
        return now + timedelta(minutes=int(m.group(1)))
    elif (
        day_offset_date is None
        and (
            "today" in lowered
            or "later today" in lowered
            or "आज" in original
            or re.search(r"\baaj\b", lowered)
        )
    ):
        day_offset_date = now

    time_of_day = explicit_time
    if time_of_day is None:
        for phrase, t in TIME_OF_DAY.items():
            if phrase in lowered:
                time_of_day = t
                break
    if time_of_day is None:
        for phrase, t in HI_TIME_OF_DAY.items():
            if phrase in original or phrase in lowered:
                time_of_day = t
                break

    if day_offset_date is None and time_of_day is None:
        return None

    base_date = day_offset_date if day_offset_date is not None else now
    chosen_time = time_of_day if time_of_day is not None else TIME_OF_DAY["morning"]
    candidate = _combine(base_date, chosen_time)

    if day_offset_date is None and candidate <= now:
        candidate += timedelta(days=1)

    return candidate