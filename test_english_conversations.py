from app.api.retell_webhook import (
    _process_new_user_turns,
    _send_mid_call_whatsapp,
    _send_final_followup_whatsapp,
)
from app.actions.callback import detect_callback_request
from app.core.models import Lead, Conversation, ConversationStatus


def run_case(
    name,
    messages,
    expected_temperature,
    expect_midcall,
    expect_callback,
):
    print("\n" + "=" * 90)
    print(name)
    print("=" * 90)

    lead = Lead(
        lead_id=f"test-lead-{name.lower().replace(' ', '-')}",
        phone_number="+919999999971",
        language="en",
    )

    conversation = Conversation(
        conversation_id=f"test-conversation-{name.lower().replace(' ', '-')}",
        lead_id=lead.lead_id,
        phone_number=lead.phone_number,
        status=ConversationStatus.ACTIVE,
        language="en",
    )

    transcript = [
        {
            "role": "user",
            "content": message,
        }
        for message in messages
    ]

    print("\n--- PROCESSING ENGLISH CONVERSATION ---")

    processing_result = _process_new_user_turns(
        conversation=conversation,
        lead=lead,
        transcript_object=transcript,
    )

    print("Processed turns   :", processing_result["processed"])

    print("\n--- CLASSIFICATION ---")

    actual_temperature = (
        lead.temperature.value.lower()
        if lead.temperature is not None
        else None
    )

    print("Language          :", lead.language)
    print("Temperature       :", actual_temperature)
    print("Expected          :", expected_temperature)
    print("Intent score      :", lead.intent_score)
    print("High intent       :", processing_result["high_intent"])

    classification_ok = (
        actual_temperature == expected_temperature.lower()
    )

    print(
        "Classification     :",
        "PASS" if classification_ok else "FAIL",
    )

    print("\n--- CALLBACK ---")

    detected_callback_text = None

    for message in messages:
        callback_text = detect_callback_request(message)

        if callback_text:
            detected_callback_text = callback_text
            break

    callback_detected = detected_callback_text is not None

    print("Callback detected  :", callback_detected)
    print("Expected           :", expect_callback)
    print("Detected text      :", detected_callback_text)

    callback_detection_ok = (
        callback_detected == expect_callback
    )

    print(
        "Detection          :",
        "PASS" if callback_detection_ok else "FAIL",
    )

    print("Stored callback    :", conversation.callback_requested)

    if expect_callback:
        callback_storage_ok = (
            conversation.callback_requested is True
        )
    else:
        callback_storage_ok = (
            conversation.callback_requested is False
        )

    print(
        "Callback storage   :",
        "PASS" if callback_storage_ok else "FAIL",
    )

    scheduled_for = processing_result.get(
        "callback_scheduled_for"
    )

    print("Scheduled for      :", scheduled_for)

    if expect_callback:
        scheduled_time_ok = scheduled_for is not None
    else:
        scheduled_time_ok = scheduled_for is None

    print(
        "Schedule result    :",
        "PASS" if scheduled_time_ok else "FAIL",
    )

    print("\n--- MID-CALL WHATSAPP ---")

    should_fire_midcall = (
        lead.intent_score >= 0.70
    )

    print("Intent score       :", lead.intent_score)
    print("HOT threshold      :", 0.70)
    print("Should fire        :", should_fire_midcall)
    print("Expected           :", expect_midcall)

    midcall_gate_ok = (
        should_fire_midcall == expect_midcall
    )

    print(
        "Mid-call decision  :",
        "PASS" if midcall_gate_ok else "FAIL",
    )

    midcall_result = None

    if should_fire_midcall:
        midcall_result = _send_mid_call_whatsapp(
            lead=lead,
            conversation=conversation,
        )

        print("\nMid-call result:")
        print(midcall_result)

        midcall_dry_run_ok = (
            midcall_result.get("dry_run") is True
        )

        print(
            "Dry-run            :",
            "PASS" if midcall_dry_run_ok else "FAIL",
        )

        midcall_message = (
            midcall_result.get("message", "")
        )

        print("\nMid-call message:")
        print(midcall_message)

        english_words = [
            "budget",
            "timeline",
            "website",
            "details",
            "price",
            "send",
        ]

        english_midcall_ok = (
            sum(
                1
                for word in english_words
                if word.lower() in midcall_message.lower()
            ) > 0
        )

        print(
            "English message    :",
            "PASS" if english_midcall_ok else "FAIL",
        )

    else:
        midcall_dry_run_ok = True
        english_midcall_ok = True

        print("Mid-call WhatsApp  : NOT TRIGGERED")

    print("\n--- FINAL FOLLOW-UP WHATSAPP ---")

    final_result = _send_final_followup_whatsapp(
        lead=lead,
        conversation=conversation,
    )

    print("\nFinal WhatsApp result:")
    print(final_result)

    final_dry_run_ok = (
        final_result.get("dry_run") is True
    )

    print(
        "\nDry-run            :",
        "PASS" if final_dry_run_ok else "FAIL",
    )

    final_message = (
        final_result.get("message", "")
    )

    media_urls = (
        final_result.get("media_urls", [])
    )

    print("\nFINAL MESSAGE:")
    print("-" * 90)
    print(final_message)
    print("-" * 90)

    print("\n--- VERIFY ENGLISH FINAL MESSAGE ---")

    english_keywords = [
        "budget",
        "timeline",
        "website",
        "business",
        "online",
        "product",
        "order",
        "feature",
        "partner",
        "price",
        "details",
    ]

    context_found = [
        keyword
        for keyword in english_keywords
        if keyword.lower() in final_message.lower()
    ]

    context_ok = len(context_found) > 0

    print("Context keywords   :", context_found)
    print(
        "English context    :",
        "PASS" if context_ok else "FAIL",
    )

    contact_number = "+91 9536216821"

    contact_ok = (
        contact_number in final_message
    )

    print(
        "Mobile number      :",
        "PASS" if contact_ok else "FAIL",
    )

    expected_architecture_url = (
        "https://drive.google.com/uc?export=download"
        "&id=1HixSFcbK-kv6or59LEblaqydERxHRdGy"
    )

    architecture_ok = (
        expected_architecture_url in media_urls
    )

    print(
        "Architecture image :",
        "PASS" if architecture_ok else "FAIL",
    )

    expected_resume_url = (
        "https://drive.google.com/uc?export=download"
        "&id=1Lve636wJgmjknwsj17QhpE5wm3nIMb7G"
    )

    resume_ok = (
        expected_resume_url in media_urls
    )

    print(
        "Resume PDF         :",
        "PASS" if resume_ok else "FAIL",
    )

    final_followup_ok = (
        final_dry_run_ok
        and context_ok
        and contact_ok
        and architecture_ok
        and resume_ok
    )

    print(
        "\nFinal follow-up    :",
        "PASS" if final_followup_ok else "FAIL",
    )

    case_ok = (
        classification_ok
        and callback_detection_ok
        and callback_storage_ok
        and scheduled_time_ok
        and midcall_gate_ok
        and midcall_dry_run_ok
        and english_midcall_ok
        and final_followup_ok
    )

    print("\n" + "-" * 90)
    print(
        name,
        ":",
        "PASS" if case_ok else "FAIL",
    )
    print("-" * 90)

    return case_ok


# ====================================================================
# HOT ENGLISH
# ====================================================================

hot_ok = run_case(
    name="HOT English",
    messages=[
        "Hi, I need an e-commerce website for my clothing business.",
        "My budget is around 2 lakh rupees and I need the website within 2 months.",
        "I need a payment gateway, product catalog, and online ordering.",
        "Yes, please send me the price and complete details. I want to move forward.",
    ],
    expected_temperature="hot",
    expect_midcall=True,
    expect_callback=False,
)


# ====================================================================
# WARM ENGLISH
# ====================================================================

warm_ok = run_case(
    name="WARM English",
    messages=[
        "I need an e-commerce website for my clothing business.",
        "My budget is a little low right now, so I can't start yet.",
        "I need to talk to my partner first.",
        "Can you call me tomorrow evening at 6 PM?",
    ],
    expected_temperature="warm",
    expect_midcall=False,
    expect_callback=True,
)


# ====================================================================
# COLD ENGLISH
# ====================================================================

cold_ok = run_case(
    name="COLD English",
    messages=[
        "I'm just looking for some information.",
        "I don't have a budget decided yet.",
        "I'm only checking how much a website would cost.",
    ],
    expected_temperature="cold",
    expect_midcall=False,
    expect_callback=False,
)


# ====================================================================
# FINAL SUMMARY
# ====================================================================

print("\n\n" + "=" * 90)
print("FINAL ENGLISH VERIFICATION SUMMARY")
print("=" * 90)

print(
    "HOT  :",
    "PASS" if hot_ok else "FAIL",
)

print(
    "WARM :",
    "PASS" if warm_ok else "FAIL",
)

print(
    "COLD :",
    "PASS" if cold_ok else "FAIL",
)

all_ok = (
    hot_ok
    and warm_ok
    and cold_ok
)

print("\n" + "=" * 90)

if all_ok:
    print("OVERALL: ALL ENGLISH TESTS PASSED")
else:
    print("OVERALL: SOME ENGLISH TESTS FAILED")

print("=" * 90)

if not all_ok:
    raise SystemExit(1)
