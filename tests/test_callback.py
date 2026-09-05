"""
Tests for app.actions.callback.detect_callback_request.

Covers section 8/19/20 of the modification spec: the callback-phrase
detector must recognize English, Hindi, and Hinglish callback requests
(gated on a parseable time being present in the same turn), and must
NOT fire on unrelated sentences that merely mention a time or the word
"call" in passing.
"""
import pytest

from app.actions.callback import detect_callback_request


@pytest.mark.parametrize(
    "text",
    [
        # English
        "Call me tomorrow at 10 AM.",
        "Call me tonight at 9 PM.",
        "I'll call you Friday evening.",
        "Please call me on September 10 at 4 PM.",
        # Hindi (Devanagari)
        "मुझे कल सुबह 10 बजे कॉल कर लेना।",
        "आप मुझे आज रात 9 बजे कॉल कर सकते हैं।",
        "मुझे कल शाम फोन कर देना।",
        "मैं आपको सोमवार को 3 बजे कॉल करूंगा।",
        # Hinglish
        "Kal morning 10 baje call kar lena.",
        "Aaj raat 9 baje mujhe call karna.",
        "Friday evening mujhe call kar lena.",
        "Main kal 10 baje aapko call karunga.",
        "September 10 ko 4 baje call kar lena.",
    ],
)
def test_detects_callback_request(text):
    assert detect_callback_request(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "The website should be live by next month.",
        "मैं अभी सिर्फ research कर रहा हूं।",
        "You can call me anytime, no rush.",  # callback phrase, no time
        "I called them last week about this.",  # no callback intent
    ],
)
def test_does_not_false_positive(text):
    assert detect_callback_request(text) is None