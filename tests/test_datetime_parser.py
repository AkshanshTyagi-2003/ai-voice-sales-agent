"""
Tests for app.utils.datetime_parser.

Covers section 19/20 of the modification spec: English regression
(today/tonight/tomorrow/day after tomorrow/weekday/specific date/
explicit time must keep working exactly as before) plus the new
Hindi and Hinglish callback-time phrasing.

All cases are anchored to a fixed `now` (Tuesday 2026-09-01 10:00) so
results are deterministic regardless of when the suite actually runs.
"""
from datetime import datetime

import pytest

from app.utils.datetime_parser import parse_relative_datetime

NOW = datetime(2026, 9, 1, 10, 0)  # Tuesday


@pytest.mark.parametrize(
    "text,expected",
    [
        # -- English regression (must be unchanged) ----------------------
        ("Call me tomorrow at 10 AM.", datetime(2026, 9, 2, 10, 0)),
        ("Call me tonight at 9 PM.", datetime(2026, 9, 1, 21, 0)),
        ("Call me tomorrow morning.", datetime(2026, 9, 2, 9, 0)),
        ("I'll call you Friday evening.", datetime(2026, 9, 4, 18, 0)),
        (
            "Please call me on September 10 at 4 PM.",
            datetime(2026, 9, 10, 16, 0),
        ),
        ("day after tomorrow", datetime(2026, 9, 3, 9, 0)),
        ("later today", datetime(2026, 9, 1, 9, 0)),
        # -- Hindi (Devanagari) -------------------------------------------
        (
            "मुझे कल सुबह 10 बजे कॉल कर लेना।",
            datetime(2026, 9, 2, 10, 0),
        ),
        (
            "आप मुझे आज रात 9 बजे कॉल कर सकते हैं।",
            datetime(2026, 9, 1, 21, 0),
        ),
        ("मुझे कल शाम फोन कर देना।", datetime(2026, 9, 2, 18, 0)),
        (
            "मैं आपको सोमवार को 3 बजे कॉल करूंगा।",
            datetime(2026, 9, 7, 3, 0),
        ),
        ("परसों कॉल करना।", datetime(2026, 9, 3, 9, 0)),
        # -- Hinglish -------------------------------------------------------
        ("Kal morning 10 baje call kar lena.", datetime(2026, 9, 2, 10, 0)),
        ("Aaj raat 9 baje mujhe call karna.", datetime(2026, 9, 1, 21, 0)),
        ("Friday evening mujhe call kar lena.", datetime(2026, 9, 4, 18, 0)),
        ("Main kal 10 baje aapko call karunga.", datetime(2026, 9, 2, 10, 0)),
        (
            "September 10 ko 4 baje call kar lena.",
            datetime(2026, 9, 10, 4, 0),
        ),
    ],
)
def test_parse_relative_datetime(text, expected):
    assert parse_relative_datetime(text, reference=NOW) == expected


def test_no_match_returns_none():
    assert (
        parse_relative_datetime("Not sure yet, will let you know.", reference=NOW)
        is None
    )