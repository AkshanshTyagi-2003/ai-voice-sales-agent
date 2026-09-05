"""
Tests for app.ai.intent (HOT/WARM/COLD classification) and
app.ai.classification.

Covers section 19 of the modification spec: English regression plus the
Hindi and Hinglish HOT/WARM/COLD examples given in the spec itself.
The scoring logic (thresholds, _decide()) is untouched by the
Hindi/Hinglish extension -- these tests exist to prove that extending
*recognition* did not change any *decision*.
"""
import pytest

from app.ai.intent import analyze_intent


@pytest.mark.parametrize(
    "text,expected_temperature",
    [
        # -- English regression --------------------------------------------
        (
            "I'm ready to proceed. What's the price and how soon can you "
            "start? My budget is around 80000 and I need it within 2 weeks.",
            "hot",
        ),
        (
            "I'm interested but I need to discuss with my partner about "
            "the budget. We're comparing a few other companies too.",
            "warm",
        ),
        (
            "I'm just looking around, no concrete project or budget yet.",
            "cold",
        ),
        # -- Hindi HOT/WARM/COLD (from the modification spec, section 19) --
        (
            "मुझे अपनी कपड़ों की दुकान के लिए ecommerce website बनवानी है। "
            "मेरा बजट लगभग 80000 रुपये है। करीब 300 products हैं। Payment "
            "gateway और order tracking चाहिए। मुझे दो हफ्ते में शुरू करना "
            "है और मैं अभी आगे बढ़ना चाहता हूं।",
            "hot",
        ),
        (
            "मुझे website बनवानी है लेकिन पहले मुझे अपने partner से budget "
            "के बारे में बात करनी होगी। मैं दूसरी companies से भी बात कर "
            "रहा हूं। आप मुझे आज रात 9 बजे call कर लेना।",
            "warm",
        ),
        (
            "मैं अभी सिर्फ research कर रहा हूं। अभी कोई project तय नहीं है "
            "और budget भी तय नहीं किया है।",
            "cold",
        ),
        # -- Hinglish HOT/WARM/COLD ------------------------------------------
        (
            "Mujhe ecommerce website chahiye. Budget around 80k hai, 300 "
            "products hain, payment gateway aur order tracking chahiye. "
            "Main next two weeks mein start karna chahta hoon aur ready "
            "hoon proceed karne ke liye.",
            "hot",
        ),
        (
            "Website chahiye but budget partner se discuss karna hai. Main "
            "kuch companies compare kar raha hoon. Aaj raat 9 baje call "
            "kar lena.",
            "warm",
        ),
        (
            "Abhi main sirf research kar raha hoon, koi project final nahi "
            "hai aur budget bhi decide nahi kiya.",
            "cold",
        ),
    ],
)
def test_intent_classification(text, expected_temperature):
    result = analyze_intent(text)
    assert result.temperature == expected_temperature, (
        f"expected {expected_temperature}, got {result.temperature} "
        f"(score={result.score}, reasons={result.reasons})"
    )


def test_hot_threshold_unchanged():
    """
    Sanity check that the HOT threshold (>= 0.70, wired in
    app/api/retell_webhook.py's high_intent gate) still lines up with
    what analyze_intent produces for a clearly hot message -- this is
    the number the mid-call WhatsApp trigger depends on, and section 5/6
    of the spec explicitly forbids changing it.
    """
    result = analyze_intent(
        "I'm ready to proceed right now, what's the price?"
    )
    assert result.score >= 0.70
    assert result.high_intent is True