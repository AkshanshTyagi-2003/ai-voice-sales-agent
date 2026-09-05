"""
Tests for app.actions.whatsapp message builders.

Covers section 9/10 of the modification spec: the post-call follow-up
(and mid-call HOT message) must reference real qualification data from
the conversation, and must be written in the customer's language
(English / Hindi / Hinglish) rather than a generic template.
"""
from app.actions.whatsapp import build_final_followup_message, build_mid_call_message
from app.core.models import Lead, QualificationData


def _lead(language, **qual_kwargs):
    return Lead(
        lead_id="l1",
        phone_number="+911234567890",
        language=language,
        qualification=QualificationData(**qual_kwargs),
    )


def test_english_followup_references_real_content():
    lead = _lead(
        "en",
        business_description="clothing store",
        budget="75000",
        product_count=300,
        features=["payment gateway", "order tracking"],
        timeline="one month",
    )
    message = build_final_followup_message(lead)
    assert "clothing store" in message
    assert "75000" in message
    assert "300" in message
    assert "payment gateway" in message


def test_hindi_followup_is_in_hindi_and_references_content():
    lead = _lead(
        "hi",
        business_description="कपड़ों",
        budget="80000",
        product_count=300,
        features=["payment gateway", "order tracking"],
        timeline="दो हफ्ते में",
    )
    message = build_final_followup_message(lead)
    # Devanagari characters should dominate the message body.
    assert any("\u0900" <= ch <= "\u097F" for ch in message)
    assert "80000" in message
    assert "300" in message
    assert "payment gateway" in message


def test_hinglish_followup_uses_romanized_hindi():
    lead = _lead(
        "hinglish",
        budget="approximately 80,000",
        product_count=300,
        timeline="next two weeks",
    )
    message = build_final_followup_message(lead)
    assert "shukriya" in message.lower()
    assert "approximately 80,000" in message
    assert "300" in message


def test_english_default_when_language_unset():
    lead = _lead(None, budget="50000")
    message = build_final_followup_message(lead)
    assert "Thanks again for the call!" in message


def test_mid_call_message_is_language_aware_too():
    hindi_lead = _lead("hi", budget="80000")
    english_lead = _lead("en", budget="80000")
    hindi_msg = build_mid_call_message(hindi_lead)
    english_msg = build_mid_call_message(english_lead)
    assert any("\u0900" <= ch <= "\u097F" for ch in hindi_msg)
    assert "Thanks for speaking with me" in english_msg