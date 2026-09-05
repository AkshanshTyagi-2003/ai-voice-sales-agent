"""
Tests for app.ai.qualification (budget / product count / timeline /
features / business description / decision maker / objections
extraction).

Covers the same fields for English, Hindi, and Hinglish input, per
section 4/19 of the modification spec: Hindi/Hinglish must populate
the SAME QualificationData fields as English, with no new/renamed
fields.
"""
from app.ai.qualification import extract_qualification


def test_english_regression():
    q = extract_qualification(
        "My business is a clothing store. Budget is around 75000. "
        "I have 300 products. I need payment gateway and order tracking. "
        "My brother handles the final decision. It's a bit too expensive "
        "though."
    )
    assert q.business_description == "clothing store"
    assert q.budget == "75000"
    assert q.product_count == 300
    assert "payment gateway" in q.features
    assert "order tracking" in q.features
    assert q.decision_maker == "brother"
    assert q.objections


def test_hindi_hot_example():
    q = extract_qualification(
        "मुझे अपनी कपड़ों की दुकान के लिए ecommerce website बनवानी है। "
        "मेरा बजट लगभग 80000 रुपये है। करीब 300 products हैं। Payment "
        "gateway और order tracking चाहिए। मुझे दो हफ्ते में शुरू करना है "
        "और मैं अभी आगे बढ़ना चाहता हूं।"
    )
    assert q.budget == "80000"
    assert q.product_count == 300
    assert "payment gateway" in q.features
    assert "order tracking" in q.features
    assert q.timeline is not None
    assert q.business_description is not None


def test_hindi_warm_example_decision_maker():
    q = extract_qualification(
        "मुझे website बनवानी है लेकिन पहले मुझे अपने partner से budget के "
        "बारे में बात करनी होगी। मैं दूसरी companies से भी बात कर रहा हूं।"
    )
    assert q.decision_maker == "partner"


def test_hinglish_hot_example():
    q = extract_qualification(
        "Mujhe ecommerce website chahiye. Budget around 80k hai, 300 "
        "products hain, payment gateway aur order tracking chahiye. Main "
        "next two weeks mein start karna chahta hoon aur ready hoon "
        "proceed karne ke liye."
    )
    assert q.budget == "approximately 80,000"
    assert q.product_count == 300
    assert "payment gateway" in q.features
    assert "order tracking" in q.features
    assert q.timeline == "next two weeks"


def test_hinglish_warm_decision_maker_and_objection_not_confused():
    q = extract_qualification(
        "Website chahiye but budget partner se discuss karna hai. Main "
        "kuch companies compare kar raha hoon."
    )
    assert q.decision_maker == "partner"
    # "budget partner se discuss karna hai" is qualification uncertainty,
    # not a genuine sales objection -- should not leak into objections.
    assert q.objections == []