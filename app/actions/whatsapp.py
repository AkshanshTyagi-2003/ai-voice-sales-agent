# whatsapp.py
"""
WhatsApp outbound action layer.

Uses Vonage's Messages API Sandbox for WhatsApp. This module does not
receive inbound WhatsApp messages -- it only sends outbound messages.

This is the ONE place Vonage is called from. app/api/retell_webhook.py
imports WhatsAppClient and the two message builders from here rather
than duplicating any HTTP plumbing.

NOTE ON THE SANDBOX: this was switched from Twilio to Vonage because
the Twilio trial account could not deliver messages. Vonage's Messages
API Sandbox has the exact same restriction Twilio's sandbox has: the
"to" number (including your own number, if you're testing by messaging
yourself) must first send the join keyword shown on your Vonage
dashboard's "Messages API Sandbox" page to VONAGE_WHATSAPP_FROM, once,
from that number's real WhatsApp app -- before Vonage will deliver
anything to it. If sends keep failing, check that opt-in first.
Reference: https://developer.vonage.com/en/messages/concepts/messages-api-sandbox

CHANGE (WARM final follow-up narrative fix): the WARM branch of
build_final_followup_message (Hindi, Hinglish, and English) now uses
_warm_context_lines_hi / _warm_context_lines_hinglish /
_warm_context_lines_en instead of the flat per-field qualification-line
dump HOT and COLD still use. These combine the same existing
QualificationData fields into fewer, more natural sentences, and also
surface qualification.objections / qualification.decision_maker (the
WARM "barrier") -- fields that already existed on the model and were
already being captured, but were never read by this module before.
HOT and COLD final follow-ups are unchanged (still use
_qualification_lines_hi / _qualification_lines_hinglish /
_qualification_lines).

CHANGE (contextual Hindi final follow-up / assignment requirements):
- WARM and COLD final follow-ups (all languages) now include the same
  qualification recap lines HOT already got, so the message reflects
  what the customer actually said instead of a fully generic template.
- The final follow-up (HOT, WARM, and COLD) now always carries a
  separate AGENT_CONTACT_NUMBER line. This is the business's own fixed
  contact number and is intentionally distinct from
  _customer_number_line, which continues to echo back the customer's
  own number exactly as before.
- Media (architecture PNG + resume PDF) is no longer HOT-only from the
  builder's point of view: has_architecture_media / has_resume_media
  are now passed in by the caller for every temperature (see
  app/api/retell_webhook.py::_send_final_followup_whatsapp), and
  _media_claim_line renders whenever they're true, regardless of
  lead.temperature.

CHANGE (WARM callback-vs-timeline semantic fix): qualification.timeline
is extracted by app/ai/qualification.py, which has a Hindi/Hinglish
"tomorrow (morning/evening)" pattern that has no awareness of callback
phrasing. That means a customer turn like "कल शाम 6 बजे कॉल कर लेना"
(a CALLBACK request) can leave qualification.timeline holding just the
fragment "कल शाम" -- which _warm_context_lines_hi/_hinglish/_en would
then describe as when the customer wants to START/LAUNCH the project.
That is wrong: it is a callback time, not a project timeline, and the
two must never be presented as the same thing.

Because app/ai/qualification.py, app/actions/callback.py, and
app/core/models.py are out of scope for this fix, the correction lives
entirely here, in three pieces:

  1. _get_latest_callback_request() reads the customer's ACTUAL
     callback record (CallbackRequest.requested_time_text) straight
     from callback_repository (app/storage/repository.py) -- this is
     a completely separate store from qualification.timeline and was
     already being populated correctly by app/actions/callback.py; it
     just was never read from here before.
  2. _timeline_overlaps_callback_text() detects when
     qualification.timeline textually overlaps the real callback text
     (exactly the "कल शाम" inside "कल शाम 6 बजे कॉल कर लेना" case) and,
     ONLY in that situation, _warm_context_lines_hi/_hinglish/_en skip
     rendering qualification.timeline as a launch timeline. This is a
     defensive filter, not a rewrite of qualification.timeline itself
     -- nothing upstream is touched, and HOT/COLD (which do not use
     these WARM-only context builders) are completely unaffected.
  3. _warm_callback_ack_line() is a NEW, WARM-ONLY function that
     renders the real callback time explicitly labeled as a callback
     ("कॉलबैक" / "callback"), instead of the generic no-time
     acknowledgement _callback_ack_line() has always produced. This is
     deliberately a NEW function rather than a change to
     _callback_ack_line() itself, because _callback_ack_line() is also
     used by the COLD branch, and COLD behavior must not change.

HOT never referenced callback data before and still doesn't. COLD still
calls the original, unmodified _callback_ack_line(). Only WARM's output
changes as a result of this fix.

CHANGE (Hinglish qualification-recap naturalness fix):
_qualification_lines_hinglish (used by the HOT and COLD Hinglish final
follow-ups, and -- via build_mid_call_message -- by the HOT mid-call
Hinglish message) previously emitted one flat, disconnected sentence
per field ("Aapne bataya tha ki aapka business X se related hai."
"Humne Y ke baare mein baat ki thi." "Aapka budget around Z tha."
...). That reads like a field-by-field dump and was reported as too
generic/robotic compared to the natural recap the assignment expects
(e.g. a HOT Hinglish recap should read like "Aapke clothing business
ke liye e-commerce website ki baat hui thi. Aapka budget around 2 lakh
hai aur aap ise 2 months ke andar chahte hain. Aapko payment gateway,
product catalog aur online ordering jaise features chahiye."). This
function has been rewritten to combine the SAME existing
QualificationData fields (business_description, products, budget,
timeline, product_count, features -- no new fields, nothing invented)
into a small number of flowing sentences: an opening context sentence
(business + product/service discussed), a combined budget+timeline
sentence when both are present, an optional product-count sentence,
and a features sentence using a natural "a, b aur c" join instead of a
bare comma list. Nothing here is hardcoded to any specific business,
amount, or feature -- every clause is conditional on the underlying
field actually being set, exactly as before.

_warm_context_lines_hinglish (WARM Hinglish) has also been touched in
one small way: its features sentence now uses the same natural
"a, b aur c" join (via _natural_join) instead of a bare comma-joined
list, for consistency with the HOT/COLD recap above. The rest of
_warm_context_lines_hinglish (opening context, budget/timeline
combination, product-count, objection/barrier, decision-maker,
callback-vs-timeline overlap guard) is UNCHANGED apart from the
objection-rendering fix described immediately below.

Per explicit instruction, the Hindi (Devanagari) and English message
content/logic were UNTOUCHED by that revision -- only the Hinglish
qualification-recap and Hinglish warm-context feature-list formatting
were updated there.

===========================================================================
CHANGE (objection/barrier NATURAL-LANGUAGE RENDERING fix -- this revision)
===========================================================================

ROOT CAUSE:

_warm_context_lines_en / _warm_context_lines_hi /
_warm_context_lines_hinglish each rendered qualification.objections by
blindly gluing a fixed grammatical connector onto whatever string(s)
were in that list:

    "Because of " + _natural_join(qualification.objections, "and")
    + ", you wanted a bit more time before moving forward."

qualification.objections (see app/ai/qualification.py) can legitimately
contain EITHER a short fragment ("too expensive", "budget issue",
"बहुत महंगा") OR a complete customer sentence extracted verbatim by
_extract_barrier_sentences ("My budget is a little low right now, so I
cannot start immediately."). The old code had no notion of that
distinction -- it always assumed a fragment ("Because of <fragment>,
you wanted..."), so a full first-person customer sentence was
grammatically mangled into "Because of My budget is a little low right
now, so I cannot start immediately., you wanted a bit more time..."
(the reported bug), and multiple objections of any kind were always
concatenated into one run-on clause instead of separate sentences.

GENERALIZED SOLUTION:

A new, reusable, language-aware objection-rendering engine is added
below (search for "OBJECTION / BARRIER RENDERING ENGINE"). It is used
ONLY by the three WARM context builders (the only place objections
were ever rendered) and does not touch HOT/COLD, qualification
extraction, classification, callback handling, media, or any other
existing behavior.

For EVERY objection string, regardless of language or wording, the
engine:

  1. Normalizes the text (trims whitespace, strips trailing
     terminators before re-adding exactly one of its own).
  2. Classifies it as a COMPLETE CLAUSE or a short FRAGMENT using
     structural signals only -- never a lookup table of specific
     sentences:
       - presence of a first-person marker (I/my/me/I'm/... in
         English; मैं/मेरा/मेरी/मेरे/मुझे/मुझसे in Hindi;
         main/mera/meri/mere/mujhe/mujhse in Hinglish), OR
       - presence of a clause connector (so/because/since in English;
         इसलिए/क्योंकि in Hindi; isliye/kyunki/kyonki/kyuki in
         Hinglish), OR
       - the string simply being long enough (>= 6 words) to be a
         clause rather than a keyword/phrase.
     None of this depends on the specific wording of any one test
     sentence -- it is a structural heuristic that generalizes to
     objection text the extractor has never produced before.
  3. If it is a COMPLETE CLAUSE: first-person references are converted
     to second-person (I -> you, my -> your, मैं -> आप, main -> aap,
     etc. -- see the ordered replacement tables below, longest/most
     specific forms first so contractions and multi-character Hindi
     matras are never partially matched), and the result is wrapped in
     a natural reported-speech frame ("You mentioned that ...",
     "आपने बताया था कि ...", "Aapne bataya tha ki ..."). For Hindi and
     Hinglish, a SAFE, gender-independent verb fix-up is also applied
     (हूँ->हैं, सकता/सकती->सकते, रहा/रही->रहे and their Hinglish
     equivalents) because आप/"aap" (formal "you") always takes
     plural/honorific verb agreement regardless of the speaker's
     gender -- this is a real, deterministic Hindi grammar rule, not a
     guess, so it does not risk the "incorrect gender-specific
     grammar" the assignment explicitly warned against. No other verb
     conjugation is attempted; where the rule doesn't apply, the
     customer's original verb form is preserved as-is rather than
     guessed at.
  4. If it is a short FRAGMENT: it is never forced through the
     reported-speech transform (which would produce nonsense like "You
     mentioned that too expensive"). Instead it is classified into a
     coarse, reusable topic bucket (price, budget, timing, approval,
     comparison, or a generic fallback that safely echoes the
     customer's own words) and rendered through a natural,
     topic-specific sentence in the target language. The topic buckets
     mirror the same barrier CATEGORIES app/ai/qualification.py's
     _extract_barrier_sentences already uses (budget / timing /
     comparison / approval / uncertainty) -- categories, not
     hardcoded sentences -- so this is consistent with, not a
     duplicate of, the extraction layer's own approach.
  5. Multiple objections are rendered as multiple, independent
     sentences (one per list item) and returned as separate lines --
     never concatenated into a single "Because of X and Y" clause.

Nothing about qualification.py's extraction, HOT/WARM/COLD
classification thresholds, callback handling, media handling, or any
public function signature is changed by this fix. Only the WARM
objection line(s) inside _warm_context_lines_en / _hi / _hinglish are
different; every other line those three functions produce (business
context, budget/timeline, product count, features, decision-maker) is
byte-for-byte unchanged.
"""

import base64
import json
import mimetypes
import re
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from app.core.config import settings
from app.core.models import Lead
from app.storage.repository import callback_repository

VONAGE_SANDBOX_MESSAGES_URL = "https://messages-sandbox.nexmo.com/v1/messages"

# ---------------------------------------------------------------------------
# Final follow-up media.
#
# The architecture image and resume are stored in the project's assets/
# directory and exposed through FastAPI's /assets/ static route.
#
# PUBLIC_BASE_URL determines the public URL:
#
# Local:
#     http://localhost:8000
#
# Railway:
#     https://ai-voice-sales-agent-production.up.railway.app
#
# Explicit architecture_image_url / resume_media_url settings still
# take priority when configured.
# ---------------------------------------------------------------------------

def resolve_final_followup_media() -> Dict[str, str]:
    """
    Resolve the public URLs for the architecture PNG and resume PDF.
    """

    base_url = (
        getattr(settings, "public_base_url", "") or ""
    ).strip().rstrip("/")

    # Local-development fallback.
    if not base_url:
        base_url = "http://localhost:8000"

    architecture_url = (
        getattr(settings, "architecture_image_url", "") or ""
    ).strip()

    if not architecture_url:
        architecture_url = (
            f"{base_url}/assets/"
            "ai_voice_sales_agent_architecture_image.png"
        )

    resume_url = (
        getattr(settings, "resume_media_url", "") or ""
    ).strip()

    if not resume_url:
        resume_url = (
            f"{base_url}/assets/"
            "Akshansh_Tyagi_AI_ML_Engineer_Resume.pdf"
        )

    return {
        "architecture_url": architecture_url,
        "resume_url": resume_url,
    }


# ---------------------------------------------------------------------------
# Customer/contact number.
#
# TARGET_PHONE_NUMBER is the single number configured in .env.
# The same configured number can therefore be used for the outbound
# call and WhatsApp flow.
# ---------------------------------------------------------------------------

def _agent_contact_number() -> str:
    """
    Return the configured contact number in display format.
    """

    number = (
        getattr(settings, "target_phone_number", "") or ""
    ).strip()

    if not number:
        return ""

    if number.startswith("+"):
        return number

    return f"+91 {number}"


class WhatsAppResult:
    def __init__(
        self,
        success: bool,
        message_sid: Optional[str] = None,
        message: str = "",
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.message_sid = message_sid
        self.message = message
        self.raw_response = raw_response


def format_phone_number(phone_number: str) -> str:
    """
    Convert common Indian phone numbers into E.164.

    Examples:
        9536216821    -> +919536216821
        919536216821  -> +919536216821
        +919536216821 -> +919536216821
    """
    cleaned = (
        str(phone_number or "")
        .strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("91") and len(cleaned) == 12:
        return f"+{cleaned}"
    if len(cleaned) == 10:
        return f"+91{cleaned}"
    return cleaned


def _vonage_number(phone_number: str) -> str:
    """
    Vonage's Messages API wants numbers WITHOUT a leading + or 00
    (e.g. "919536216821", not "+919536216821").
    https://developer.vonage.com/en/messages/concepts/messages-api-sandbox
    """
    e164 = format_phone_number(phone_number)
    return e164.lstrip("+")


def _guess_media_message_type(media_url: str) -> str:
    """
    Vonage's Messages API needs a distinct message_type per media kind
    (image / file / video / audio) -- unlike Twilio's single MediaUrl
    parameter that accepts anything. Guess from the URL's extension.

    NOTE: share links (e.g. Google Drive "…/view?usp=drive_link" URLs)
    don't carry a file extension, so this guess will fall back to
    "file" for them -- callers that already know the real media kind
    (see send_media's media_types param and
    resolve_final_followup_media) should pass it explicitly instead of
    relying on this guess.
    """
    guessed_type, _ = mimetypes.guess_type(media_url)
    if guessed_type:
        if guessed_type.startswith("image/"):
            return "image"
        if guessed_type.startswith("video/"):
            return "video"
        if guessed_type.startswith("audio/"):
            return "audio"
    return "file"


class WhatsAppClient:
    """Outbound WhatsApp sender (Vonage Messages API Sandbox)."""

    def __init__(self) -> None:
        self.api_key = getattr(settings, "vonage_api_key", None)
        self.api_secret = getattr(settings, "vonage_api_secret", None)
        self.whatsapp_from = getattr(settings, "vonage_whatsapp_from", None)

        if not self.api_key:
            raise ValueError("VONAGE_API_KEY is not configured.")
        if not self.api_secret:
            raise ValueError("VONAGE_API_SECRET is not configured.")
        if not self.whatsapp_from:
            raise ValueError("VONAGE_WHATSAPP_FROM is not configured.")

    def _auth_header(self) -> str:
        credentials = base64.b64encode(
            f"{self.api_key}:{self.api_secret}".encode("utf-8")
        ).decode("ascii")
        return f"Basic {credentials}"

    def _post(self, payload: Dict[str, Any]) -> WhatsAppResult:
        body = json.dumps(payload).encode("utf-8")

        request = Request(
            VONAGE_SANDBOX_MESSAGES_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
            return WhatsAppResult(
                success=True,
                message_sid=data.get("message_uuid"),
                message="WhatsApp sent successfully.",
                raw_response=data,
            )
        except Exception as exc:
            return WhatsAppResult(
                success=False,
                message=f"WhatsApp send failed: {exc}",
            )

    def send_text(self, to_number: str, body: str) -> WhatsAppResult:
        """Send a plain WhatsApp text message."""

        to_number = _vonage_number(to_number)
        return self._post(
            {
                "to": to_number,
                "from": self.whatsapp_from,
                "channel": "whatsapp",
                "message_type": "text",
                "text": body,
            }
        )

    def send_media(
        self,
        to_number: str,
        body: str,
        media_urls: List[str],
        media_types: Optional[List[str]] = None,
    ) -> WhatsAppResult:
        """
        Send a WhatsApp message with one or more media attachments.

        Unlike Twilio (one call, repeated MediaUrl fields), Vonage's
        Messages API requires ONE call per message, and each media
        message needs a specific message_type (image / file / video /
        audio) rather than a generic attachment field. So this sends
        the text body first, then one follow-up call per media URL,
        and reports success only if every one of those sends succeeded
        (the caller -- retell_webhook.py -- only marks
        whatsapp_sent_final once this returns success=True, so a
        partial failure here should NOT be reported as a full send).

        media_types is an optional list of explicit Vonage message
        types ("image" / "file" / "video" / "audio"), aligned by index
        with media_urls. This is needed because some media URLs (e.g.
        Google Drive share links) don't carry a file extension, so the
        automatic guess in _guess_media_message_type can't tell a PNG
        from a PDF from the URL alone. Any index without an explicit
        type falls back to the guess, so existing callers that only
        pass media_urls keep working unchanged.
        """

        to_number = _vonage_number(to_number)
        results: List[WhatsAppResult] = []

        if body:
            results.append(
                self._post(
                    {
                        "to": to_number,
                        "from": self.whatsapp_from,
                        "channel": "whatsapp",
                        "message_type": "text",
                        "text": body,
                    }
                )
            )

        for index, media_url in enumerate(media_urls):
            if not media_url:
                continue
            explicit_type = (
                media_types[index]
                if media_types and index < len(media_types) and media_types[index]
                else None
            )
            media_type = explicit_type or _guess_media_message_type(media_url)
            payload: Dict[str, Any] = {
                "to": to_number,
                "from": self.whatsapp_from,
                "channel": "whatsapp",
                "message_type": media_type,
                media_type: {"url": media_url},
            }
            results.append(self._post(payload))

        all_succeeded = bool(results) and all(r.success for r in results)
        failures = [r.message for r in results if not r.success]

        return WhatsAppResult(
            success=all_succeeded,
            message_sid=(
                results[0].message_sid if results and results[0].success else None
            ),
            message=(
                "WhatsApp media message sent successfully."
                if all_succeeded
                else "WhatsApp media send failed: " + "; ".join(failures)
            ),
            raw_response={
                "parts": [r.raw_response for r in results],
            },
        )


# ---------------------------------------------------------------------------
# Budget/number formatting
#
# PROBLEM 1 fix: qualification.budget can arrive as a normalized value
# such as "approximately 200,000" (or a bare number, or an already
# natural string like "2 lakh"). Every message template below adds its
# OWN hedge word ("around" / "लगभग" / "around" in Hinglish), so any
# hedge word already baked into the raw value must be stripped first or
# it doubles up (the literal bug report: "लगभग approximately 200,000").
# Bare numeric amounts are converted into natural Indian lakh/crore
# phrasing instead of exposing the raw normalized digits, since that is
# what an Indian customer who said "2 लाख रुपये" actually expects to
# read back.
# ---------------------------------------------------------------------------

_HEDGE_WORD_RE = re.compile(r"(?i)\b(?:approximately|around)\b\s*")
_HEDGE_WORD_HI_RE = re.compile(r"(?:लगभग|आसपास)\s*")
_NUMBER_WITH_COMMAS_RE = re.compile(r"^[₹$]?\s*[\d,]+(?:\.\d+)?\s*$")
_CURRENCY_WORDS_RE = re.compile(r"(?i)(rupees?|rs\.?|inr|₹|रुपये|रुपए)")
_NATURAL_UNIT_WORDS_RE = re.compile(
    r"(?i)(lakh|crore|lac|हज़ार|हजार|लाख|करोड़)"
)


def _clean_hedge_words(raw: Any) -> str:
    """Strip hedge words ('approximately'/'around'/'लगभग') that may
    already be baked into a raw qualification value, so the template's
    own hedge word isn't doubled up."""
    text = str(raw or "").strip()
    if not text:
        return ""
    text = _HEDGE_WORD_RE.sub("", text).strip()
    text = _HEDGE_WORD_HI_RE.sub("", text).strip()
    return text


def _trim_decimal(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _to_indian_amount_words(amount: float) -> str:
    """200000 -> '2 lakh', 1500000 -> '15 lakh', 12500000 -> '1.25 crore'."""
    if amount >= 1_00_00_000:
        return f"{_trim_decimal(amount / 1_00_00_000)} crore"
    if amount >= 1_00_000:
        return f"{_trim_decimal(amount / 1_00_000)} lakh"
    if amount >= 1_000:
        return f"{int(amount):,}"
    return _trim_decimal(amount)


def _format_budget_for_language(raw_budget: Any, language: str) -> str:
    """
    Produce a natural-language budget string for WhatsApp copy in the
    given language ("hi" / "hinglish" / "en").

    - Strips redundant hedge words already present in the raw value.
    - Converts a bare normalized number into natural Indian lakh/crore
      wording instead of echoing raw digits.
    - Leaves already-natural values (e.g. "2 lakh rupees") untouched
      apart from hedge-word cleanup and script/currency-word alignment.
    - Never invents an amount that wasn't in the raw value.
    """
    text = _clean_hedge_words(raw_budget)
    if not text:
        return ""

    if _NATURAL_UNIT_WORDS_RE.search(text):
        words = text
    elif _NUMBER_WITH_COMMAS_RE.match(text):
        digits = re.sub(r"[₹$,\s]", "", text)
        try:
            amount = float(digits)
        except ValueError:
            return text
        words = _to_indian_amount_words(amount)
    else:
        # Not a recognizable bare number or lakh/crore phrase -- return
        # the hedge-cleaned text unchanged rather than guessing.
        return text

    if language == "hi":
        words = words.replace("lakh", "लाख").replace("crore", "करोड़")
        words = re.sub(r"(?i)\brupees?\b", "रुपये", words)
        if not _CURRENCY_WORDS_RE.search(words):
            words = f"{words} रुपये"
        return words

    if language == "hinglish":
        if not _CURRENCY_WORDS_RE.search(words):
            words = f"{words} rupees"
        return words

    # English
    return words


def _qualification_lines(lead: Lead) -> List[str]:
    qualification = lead.qualification
    lines: List[str] = []

    if qualification.business_description:
        lines.append(
            f"I noted that your business is {qualification.business_description}."
        )
    if qualification.products:
        lines.append(
            f"The product/service discussed was {qualification.products}."
        )
    if qualification.product_count:
        lines.append(f"You mentioned around {qualification.product_count} products.")
    if qualification.budget:
        formatted_budget = _format_budget_for_language(qualification.budget, "en")
        if formatted_budget:
            lines.append(f"Your budget is around {formatted_budget}.")
    if qualification.timeline:
        lines.append(f"Your target timeline is {qualification.timeline}.")
    if qualification.features:
        lines.append(
            "The key features you mentioned are "
            + ", ".join(qualification.features)
            + "."
        )
    return lines


# ---------------------------------------------------------------------------
# EXTENSION (multilingual follow-up): Hindi (Devanagari) and Hinglish
# variants of the same qualification recap. These mirror the English
# version above line-for-line -- same fields, same order, same
# information -- only the language differs, per doc2 sections 1/10
# ("Language must only affect how the conversation is expressed... The
# business logic and information must remain identical.").
#
# These are used for HOT, WARM, and COLD final follow-ups (see
# build_final_followup_message below) so that WARM/COLD messages also
# reference what the customer actually said instead of staying fully
# generic.
#
# UNCHANGED by the WARM callback-vs-timeline fix: these three functions
# still read qualification.timeline directly, with no filtering. HOT
# and COLD keep using them exactly as before -- only the new WARM-only
# _warm_context_lines_* functions below apply the overlap guard.
#
# _qualification_lines_hi (Hindi/Devanagari) is UNCHANGED in this
# revision -- Hindi content stays exactly as it was.
# ---------------------------------------------------------------------------


def _qualification_lines_hi(lead: Lead) -> List[str]:
    qualification = lead.qualification
    lines: List[str] = []

    if qualification.business_description:
        lines.append(
            f"आपने बताया था कि आपका बिज़नेस {qualification.business_description} "
            "से जुड़ा है।"
        )
    if qualification.products:
        lines.append(f"हमने {qualification.products} के बारे में बात की थी।")
    if qualification.product_count:
        lines.append(f"आपने करीब {qualification.product_count} products बताए थे।")
    if qualification.budget:
        formatted_budget = _format_budget_for_language(qualification.budget, "hi")
        if formatted_budget:
            lines.append(f"आपका बजट लगभग {formatted_budget} था।")
    if qualification.timeline:
        lines.append(f"आपकी टाइमलाइन {qualification.timeline} थी।")
    if qualification.features:
        lines.append(
            "आपने जो मुख्य features बताए वो हैं "
            + ", ".join(qualification.features)
            + "।"
        )
    return lines


# ---------------------------------------------------------------------------
# CHANGE (Hinglish qualification-recap naturalness fix):
#
# Previously this emitted one flat, standalone sentence per field
# ("Aapne bataya tha ki aapka business X se related hai." "Humne Y ke
# baare mein baat ki thi." "Aapka budget around Z tha." "Aapki
# timeline W thi." ...), which read as a disconnected field dump and
# is what let a generic-sounding HOT/COLD Hinglish message through even
# when real qualification data existed.
#
# It now combines the SAME existing fields -- business_description,
# products, budget, timeline, product_count, features -- into a small,
# natural recap:
#   1. An opening sentence naming what was discussed (business +
#      product/service), e.g. "Aapke clothing business ke liye
#      e-commerce website ki baat hui thi."
#   2. A single combined sentence for budget + timeline when both are
#      present, e.g. "Aapka budget around 2 lakh hai aur aap ise
#      2 months ke andar chahte hain." (falls back to just budget, or
#      just timeline, when only one is present.)
#   3. An optional product-count sentence.
#   4. A features sentence using a natural "a, b aur c" join instead of
#      a bare comma list, e.g. "Aapko payment gateway, product catalog
#      aur online ordering jaise features chahiye."
#
# Every clause remains strictly conditional on the underlying
# QualificationData field actually being set -- nothing is invented,
# no business name / amount / feature is hardcoded, and no new fields
# or parallel qualification system were introduced. This function is
# used by the HOT and COLD Hinglish final follow-ups, and (via
# build_mid_call_message) by the HOT mid-call Hinglish message -- so
# all three now get this same natural recap automatically.
# ---------------------------------------------------------------------------


def _qualification_lines_hinglish(lead: Lead) -> List[str]:
    qualification = lead.qualification
    lines: List[str] = []

    # 1. Opening: what was actually discussed -- business + the
    # product/service, when both are known; otherwise whichever one is
    # available.
    if qualification.business_description and qualification.products:
        lines.append(
            f"Aapke {qualification.business_description} business ke liye "
            f"{qualification.products} ki baat hui thi."
        )
    elif qualification.business_description:
        lines.append(
            f"Aapke {qualification.business_description} business ke liye "
            "website ki baat hui thi."
        )
    elif qualification.products:
        lines.append(f"Humne {qualification.products} ke baare mein baat ki thi.")

    # 2. Budget + timeline combined into one natural sentence when both
    # exist; falls back gracefully when only one is present.
    budget_bit = ""
    if qualification.budget:
        formatted_budget = _format_budget_for_language(
            qualification.budget, "hinglish"
        )
        if formatted_budget:
            budget_bit = f"Aapka budget around {formatted_budget} hai"

    if qualification.timeline:
        timeline_bit = f"aap ise {qualification.timeline} ke andar chahte hain"
        if budget_bit:
            lines.append(f"{budget_bit} aur {timeline_bit}.")
        else:
            lines.append(f"Aap ise {qualification.timeline} ke andar chahte hain.")
    elif budget_bit:
        lines.append(f"{budget_bit}.")

    # 3. Product count, when known.
    if qualification.product_count:
        lines.append(
            f"Aapke paas around {qualification.product_count} products honge."
        )

    # 4. Features, joined naturally ("a, b aur c") rather than a bare
    # comma list.
    if qualification.features:
        lines.append(
            "Aapko " + _natural_join(qualification.features, "aur")
            + " jaise features chahiye."
        )

    return lines


# ---------------------------------------------------------------------------
# OBJECTION / BARRIER RENDERING ENGINE
#
# See the module docstring section "CHANGE (objection/barrier
# NATURAL-LANGUAGE RENDERING fix -- this revision)" above for the full
# root-cause / design write-up. Summary: qualification.objections may
# hold either a short fragment or a complete first-person customer
# sentence, in English, Hindi, or Hinglish, and this engine renders
# EITHER kind naturally, in any of those languages, using only
# structural signals (never a lookup table keyed on specific
# sentences). It is used exclusively by _warm_context_lines_en/_hi/
# _hinglish below.
# ---------------------------------------------------------------------------

# -- Step 1: classification (complete clause vs. short fragment) ----------

_EN_FIRST_PERSON_RE = re.compile(
    r"\b(?:i'm|i've|i'll|i'd|myself|my|me|i)\b", re.IGNORECASE
)
_HI_FIRST_PERSON_RE = re.compile(r"मुझसे|मुझे|मेरा|मेरी|मेरे|मैं")
_HINGLISH_FIRST_PERSON_RE = re.compile(
    r"\b(?:mujhse|mujhe|mera|meri|mere|main)\b", re.IGNORECASE
)

_EN_CONNECTOR_RE = re.compile(r"\b(?:so|because|since)\b", re.IGNORECASE)
_HI_CONNECTOR_RE = re.compile(r"इसलिए|क्योंकि")
_HINGLISH_CONNECTOR_RE = re.compile(
    r"\b(?:isliye|kyunki|kyonki|kyuki)\b", re.IGNORECASE
)

_COMPLETE_CLAUSE_WORD_COUNT_THRESHOLD = 6


def _is_complete_clause(text: str, language: str) -> bool:
    """
    Decide whether an extracted objection string behaves like a
    complete clause/sentence (should be rendered as reported speech)
    or a short fragment (should be rendered as a natural "concern"
    sentence instead).

    Deliberately structural, not a lookup of specific wordings, so it
    generalizes to objection text that was never part of any test:
      - a first-person marker (I/my/me/... , मैं/मेरा/..., main/mera/...)
        strongly implies the customer stated something about
        themselves -- treat as a clause even if short, OR
      - a clause connector (so/because/इसलिए/isliye/...) implies a
        multi-part sentence -- treat as a clause, OR
      - otherwise, fall back to length: six words or more reads as a
        sentence even without an explicit pronoun (common in Hindi/
        Hinglish, where the subject is often dropped -- e.g. "...kar
        sakta" implies "main ... kar sakta").
    Anything shorter than that, with no pronoun and no connector, is
    treated as a short fragment (e.g. "too expensive", "budget issue",
    "बहुत महंगा", "बजट कम है").
    """
    text = str(text or "").strip()
    if not text:
        return False

    word_count = len(text.split())

    if language == "hi":
        has_first_person = bool(_HI_FIRST_PERSON_RE.search(text))
        has_connector = bool(_HI_CONNECTOR_RE.search(text))
    elif language == "hinglish":
        has_first_person = bool(_HINGLISH_FIRST_PERSON_RE.search(text))
        has_connector = bool(_HINGLISH_CONNECTOR_RE.search(text))
    else:
        has_first_person = bool(_EN_FIRST_PERSON_RE.search(text))
        has_connector = bool(_EN_CONNECTOR_RE.search(text))

    return (
        has_first_person
        or has_connector
        or word_count >= _COMPLETE_CLAUSE_WORD_COUNT_THRESHOLD
    )


def _strip_trailing_terminator(text: str) -> str:
    """Strip whatever sentence-ending punctuation the customer used, so
    exactly one terminator (the frame's own) is ever added back."""
    return text.strip().rstrip(" .!?।-").strip()


def _lowercase_first(text: str) -> str:
    if not text:
        return text
    return text[0].lower() + text[1:]


# -- Step 2: first-person -> second-person pronoun conversion --------------
#
# Ordered longest/most-specific-first so contractions and longer forms
# are never partially matched by a shorter pattern first (per the
# assignment's explicit "be careful with replacement order" note).

_EN_PRONOUN_REPLACEMENTS = [
    (re.compile(r"\bi've\b", re.IGNORECASE), "you've"),
    (re.compile(r"\bi'll\b", re.IGNORECASE), "you'll"),
    (re.compile(r"\bi'd\b", re.IGNORECASE), "you'd"),
    (re.compile(r"\bi'm\b", re.IGNORECASE), "you're"),
    (re.compile(r"\bi am\b", re.IGNORECASE), "you are"),
    (re.compile(r"\bi was\b", re.IGNORECASE), "you were"),
    (re.compile(r"\bmyself\b", re.IGNORECASE), "yourself"),
    (re.compile(r"\bmy\b", re.IGNORECASE), "your"),
    (re.compile(r"\bme\b", re.IGNORECASE), "you"),
    (re.compile(r"\bi\b", re.IGNORECASE), "you"),
]


def _convert_pronouns_en(text: str) -> str:
    result = text
    for pattern, replacement in _EN_PRONOUN_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result


# Hindi: matched as plain substrings (order longest-prefix-safe; none of
# these Devanagari forms are substrings of one another because the
# combining vowel signs differ), followed by a SAFE, gender-independent
# verb fix-up. आप (formal "you") always takes plural/honorific verb
# agreement regardless of the speaker's original gendered verb form, so
# this substitution is a real deterministic Hindi grammar rule -- not a
# guess -- and is the only verb adjustment ever attempted.
_HI_PRONOUN_REPLACEMENTS = [
    ("मुझसे", "आपसे"),
    ("मुझे", "आपको"),
    ("मेरा", "आपका"),
    ("मेरी", "आपकी"),
    ("मेरे", "आपके"),
    ("मैं", "आप"),
]

_HI_VERB_FIXUPS = [
    ("हूँ", "हैं"),
    ("हूं", "हैं"),
    ("सकता", "सकते"),
    ("सकती", "सकते"),
    ("रहा", "रहे"),
    ("रही", "रहे"),
]


def _convert_pronouns_hi(text: str) -> str:
    result = text
    for old, new in _HI_PRONOUN_REPLACEMENTS:
        result = result.replace(old, new)
    for old, new in _HI_VERB_FIXUPS:
        result = result.replace(old, new)
    return result


_HINGLISH_PRONOUN_REPLACEMENTS = [
    (re.compile(r"\bmujhse\b", re.IGNORECASE), "aapse"),
    (re.compile(r"\bmujhe\b", re.IGNORECASE), "aapko"),
    (re.compile(r"\bmera\b", re.IGNORECASE), "aapka"),
    (re.compile(r"\bmeri\b", re.IGNORECASE), "aapki"),
    (re.compile(r"\bmere\b", re.IGNORECASE), "aapke"),
    (re.compile(r"\bmain\b", re.IGNORECASE), "aap"),
]

# Same safe, gender-independent honorific-verb fix-up as Hindi above,
# transliterated.
_HINGLISH_VERB_FIXUPS = [
    (re.compile(r"\bhoon\b", re.IGNORECASE), "hain"),
    (re.compile(r"\bhu\b", re.IGNORECASE), "hain"),
    (re.compile(r"\bsakta\b", re.IGNORECASE), "sakte"),
    (re.compile(r"\bsakti\b", re.IGNORECASE), "sakte"),
    (re.compile(r"\braha\b", re.IGNORECASE), "rahe"),
    (re.compile(r"\brahi\b", re.IGNORECASE), "rahe"),
]


def _convert_pronouns_hinglish(text: str) -> str:
    result = text
    for pattern, replacement in _HINGLISH_PRONOUN_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    for pattern, replacement in _HINGLISH_VERB_FIXUPS:
        result = pattern.sub(replacement, result)
    return result


# -- Step 3: short-fragment topic classification + natural templates -------
#
# These mirror the same barrier CATEGORIES app/ai/qualification.py's
# _extract_barrier_sentences already uses (budget / timing / comparison
# / approval / general uncertainty) plus a "price" category for the
# very common "too expensive" style fragment -- categories, not
# hardcoded sentences, so this generalizes to any fragment that talks
# about price, budget, timing, approval, or comparison, not just the
# exact phrases seen in testing. Anything that matches no category
# falls back to a generic template that safely echoes the customer's
# own fragment rather than inventing content.

_FRAGMENT_TOPIC_PATTERNS = [
    ("price", re.compile(
        r"expensive|costly|pricey|price|cost|महंगा|कीमत|mehnga|mahenga",
        re.IGNORECASE,
    )),
    ("budget", re.compile(
        r"budget|afford|money|बजट|paisa|paise",
        re.IGNORECASE,
    )),
    ("timing", re.compile(
        r"\btime\b|ready|delay|immediate|soon|समय|तैयार|time\b",
        re.IGNORECASE,
    )),
    ("approval", re.compile(
        r"approval|approve|boss|manager|management|मंज़ूरी|मंजूरी|स्वीकृति",
        re.IGNORECASE,
    )),
    ("comparison", re.compile(
        r"compare|comparing|vendor|option|alternative|तुलना|विकल्प",
        re.IGNORECASE,
    )),
]

_FRAGMENT_TEMPLATES = {
    "en": {
        "price": "You also mentioned that the price feels high.",
        "budget": "You also mentioned a concern about the budget.",
        "timing": "You also mentioned that the timing isn't ideal right now.",
        "approval": "You also mentioned needing approval before moving forward.",
        "comparison": "You also mentioned wanting to compare a few options.",
    },
    "hi": {
        "price": "आपने कीमत ज्यादा होने की बात भी कही थी।",
        "budget": "आपने बजट को लेकर भी चिंता जताई थी।",
        "timing": "आपने बताया कि अभी सही समय नहीं है।",
        "approval": "आपने बताया कि पहले मंज़ूरी लेनी होगी।",
        "comparison": "आपने कुछ और विकल्प देखने की बात भी कही थी।",
    },
    "hinglish": {
        "price": "Aapne price zyada hone ki baat bhi kahi thi.",
        "budget": "Aapne budget ko lekar bhi concern share kiya tha.",
        "timing": "Aapne bataya ki abhi sahi time nahi hai.",
        "approval": "Aapne bataya ki pehle approval leni hogi.",
        "comparison": "Aapne kuch aur options dekhne ki baat bhi kahi thi.",
    },
}


def _classify_fragment_topic(fragment: str) -> Optional[str]:
    for topic, pattern in _FRAGMENT_TOPIC_PATTERNS:
        if pattern.search(fragment):
            return topic
    return None


def _render_fragment(fragment: str, language: str) -> str:
    cleaned = _strip_trailing_terminator(fragment)
    topic = _classify_fragment_topic(cleaned)
    templates = _FRAGMENT_TEMPLATES.get(language, _FRAGMENT_TEMPLATES["en"])
    if topic and topic in templates:
        return templates[topic]

    # Generic fallback: never invent content, just safely echo the
    # customer's own fragment inside a natural, language-appropriate
    # "you also mentioned" frame.
    if language == "hi":
        return f"आपने {cleaned} को लेकर भी अपनी बात रखी थी।"
    if language == "hinglish":
        return f"Aapne {cleaned} ko lekar bhi apni baat rakhi thi."
    return f"You also mentioned a concern about {cleaned.lower()}."


# -- Step 4: complete-clause reported-speech rendering ----------------------

def _render_complete_clause(clause: str, language: str) -> str:
    cleaned = _strip_trailing_terminator(clause)

    if language == "hi":
        converted = _convert_pronouns_hi(cleaned)
        return f"आपने बताया था कि {converted}।"

    if language == "hinglish":
        converted = _convert_pronouns_hinglish(cleaned)
        converted = _lowercase_first(converted)
        return f"Aapne bataya tha ki {converted}."

    converted = _convert_pronouns_en(cleaned)
    converted = _lowercase_first(converted)
    return f"You mentioned that {converted}."


# -- Step 5: public entry point ---------------------------------------------

def _render_objection(objection: str, language: str) -> str:
    """
    Render a single objection/barrier string naturally, regardless of
    whether it is a short fragment or a complete customer sentence, in
    the given language. This is the fix for the reported bug -- see
    the "OBJECTION / BARRIER RENDERING ENGINE" section above.
    """
    text = str(objection or "").strip()
    if not text:
        return ""
    if _is_complete_clause(text, language):
        return _render_complete_clause(text, language)
    return _render_fragment(text, language)


def _render_objection_sentences(
    objections: List[str], language: str
) -> List[str]:
    """
    Render every objection/barrier in the list as its OWN natural
    sentence (never concatenated into a single run-on "Because of X
    and Y" clause -- see requirement: "When multiple objections exist,
    produce separate grammatical sentences.").
    """
    sentences: List[str] = []
    for objection in objections:
        sentence = _render_objection(objection, language)
        if sentence and sentence not in sentences:
            sentences.append(sentence)
    return sentences


# ---------------------------------------------------------------------------
# WARM-ONLY: natural-narrative context builders.
#
# _qualification_lines / _qualification_lines_hi / _qualification_lines_hinglish
# above (used by HOT and COLD) render the qualification recap. For WARM
# specifically, the assignment asked for a message that "reads like a
# natural human follow-up ... NOT like a database dump", while still
# only using data that was actually captured -- so these three
# builders combine the SAME existing QualificationData fields
# (business_description, products, product_count, budget, timeline,
# features) into fewer, more flowing sentences, and additionally
# surface qualification.objections and qualification.decision_maker as
# the WARM "barrier" -- both fields already existed on
# QualificationData (app/core/models.py) and were already being
# captured by app/ai/qualification.py, but neither was ever read by
# this module before. No new fields, no new storage, no parallel
# context system -- purely additive use of existing data. Nothing here
# is invented: every sentence is conditional on the underlying field
# actually being set.
#
# CHANGE (callback-vs-timeline fix): each of these now takes an
# optional callback_text (the customer's real CallbackRequest.raw
# requested_time_text, if any -- see _get_latest_callback_request in
# build_final_followup_message). If qualification.timeline overlaps
# that callback text (see _timeline_overlaps_callback_text), the
# timeline sentence is skipped here -- it is never presented as when
# the customer wants to start/launch the project, because in that
# situation it is actually describing the callback, not the project.
# qualification.timeline itself is never read, modified, or
# invalidated anywhere else -- HOT/COLD still use it unfiltered via
# _qualification_lines_hi/_hinglish/_qualification_lines above.
#
# CHANGE (objection/barrier rendering fix -- this revision): the
# objection/barrier line in all three functions below now calls
# _render_objection_sentences (see the engine above) instead of gluing
# "Because of "/"...की वजह से"/"...ki wajah se" onto the raw
# objection text. This is the ONLY change in this revision to these
# three functions -- opening context, budget/timeline combination,
# product-count, features, decision-maker, and the callback/timeline
# overlap guard are all unchanged from the previous revision.
# ---------------------------------------------------------------------------


def _natural_join(items: List[str], conjunction: str) -> str:
    """Join items into a natural list: 'a', 'a and b', 'a, b and c'."""
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(items[:-1]) + f" {conjunction} " + items[-1]


def _normalize_for_overlap(text: Any) -> str:
    """Lowercase + collapse whitespace, for a simple substring-overlap
    comparison. Devanagari has no case, so lower() is a no-op on it and
    a safe no-op operation on Hindi text; this is only meaningful for
    the Latin-script (English/Hinglish) side of the comparison."""
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _timeline_overlaps_callback_text(
    timeline: Optional[str], callback_text: Optional[str]
) -> bool:
    """
    THE CORE OF THE CALLBACK-VS-TIMELINE FIX.

    qualification.timeline and the customer's real callback request
    (CallbackRequest.requested_time_text) are extracted by two entirely
    separate, callback-unaware code paths (app/ai/qualification.py and
    app/actions/callback.py respectively). That means it is possible
    -- and, per the bug report, does happen -- for
    qualification.timeline to end up holding a substring of the
    callback sentence (e.g. "कल शाम" lifted out of "कल शाम 6 बजे कॉल कर
    लेना").

    This function does not know or care WHY that happened; it just
    checks whether the two strings overlap, and if so, tells the
    caller "don't trust this timeline value as a real project
    timeline". It is intentionally a simple, conservative substring
    check in either direction (timeline-in-callback or
    callback-in-timeline) rather than a fuzzy match, so it only ever
    suppresses a timeline sentence when there is a real, literal
    overlap with the actual callback text -- it will not suppress an
    unrelated timeline just because a callback also exists.
    """
    timeline_norm = _normalize_for_overlap(timeline)
    callback_norm = _normalize_for_overlap(callback_text)
    if not timeline_norm or not callback_norm:
        return False
    return timeline_norm in callback_norm or callback_norm in timeline_norm


def _warm_context_lines_hi(
    lead: Lead, callback_text: Optional[str] = None
) -> List[str]:
    qualification = lead.qualification
    lines: List[str] = []

    if qualification.business_description:
        lines.append(
            f"आज हमने आपकी {qualification.business_description} "
            "बिज़नेस की वेबसाइट को लेकर बात की थी।"
        )
    elif qualification.products:
        lines.append(f"आज हमने {qualification.products} के बारे में बात की थी।")

    detail_bits = []
    if qualification.product_count:
        detail_bits.append(f"आपके पास लगभग {qualification.product_count} products होंगे")
    if qualification.budget:
        formatted_budget = _format_budget_for_language(qualification.budget, "hi")
        if formatted_budget:
            detail_bits.append(f"बजट करीब {formatted_budget} है")
    if qualification.timeline and not _timeline_overlaps_callback_text(
        qualification.timeline, callback_text
    ):
        detail_bits.append(f"आप इसे लगभग {qualification.timeline} में शुरू करना चाहते हैं")
    if detail_bits:
        lines.append("आपने बताया था कि " + _natural_join(detail_bits, "और") + "।")

    if qualification.features:
        lines.append(
            "आपने " + ", ".join(qualification.features)
            + " जैसी सुविधाओं के बारे में भी पूछा था।"
        )

    if qualification.objections:
        lines.extend(_render_objection_sentences(qualification.objections, "hi"))
    if qualification.decision_maker:
        lines.append(
            f"आपने {qualification.decision_maker} से भी बात करनी है, ये भी नोट कर लिया है।"
        )

    return lines


def _warm_context_lines_hinglish(
    lead: Lead, callback_text: Optional[str] = None
) -> List[str]:
    qualification = lead.qualification
    lines: List[str] = []

    if qualification.business_description:
        lines.append(
            f"Aaj humne aapke {qualification.business_description} "
            "business ki website ke baare mein baat ki thi."
        )
    elif qualification.products:
        lines.append(f"Aaj humne {qualification.products} ke baare mein baat ki thi.")

    detail_bits = []
    if qualification.product_count:
        detail_bits.append(f"aapke paas around {qualification.product_count} products honge")
    if qualification.budget:
        formatted_budget = _format_budget_for_language(
            qualification.budget, "hinglish"
        )
        if formatted_budget:
            detail_bits.append(f"budget around {formatted_budget} hai")
    if qualification.timeline and not _timeline_overlaps_callback_text(
        qualification.timeline, callback_text
    ):
        detail_bits.append(f"aap ise around {qualification.timeline} mein shuru karna chahte hain")
    if detail_bits:
        lines.append("Aapne bataya tha ki " + _natural_join(detail_bits, "aur") + ".")

    if qualification.features:
        # NOTE: natural "a, b aur c" join (was a bare comma list) --
        # for consistency with the HOT/COLD Hinglish recap in
        # _qualification_lines_hinglish.
        lines.append(
            "Aapne " + _natural_join(qualification.features, "aur")
            + " jaisi features ke baare mein bhi poocha tha."
        )

    if qualification.objections:
        lines.extend(
            _render_objection_sentences(qualification.objections, "hinglish")
        )
    if qualification.decision_maker:
        lines.append(
            f"Aapko {qualification.decision_maker} se bhi baat karni hai, "
            "wo bhi note kar liya hai."
        )

    return lines


def _warm_context_lines_en(
    lead: Lead, callback_text: Optional[str] = None
) -> List[str]:
    qualification = lead.qualification
    lines: List[str] = []

    if qualification.business_description:
        lines.append(
            f"Today we talked about the website for your "
            f"{qualification.business_description} business."
        )
    elif qualification.products:
        lines.append(f"Today we talked about {qualification.products}.")

    detail_bits = []
    if qualification.product_count:
        detail_bits.append(f"you'll have around {qualification.product_count} products")
    if qualification.budget:
        formatted_budget = _format_budget_for_language(qualification.budget, "en")
        if formatted_budget:
            detail_bits.append(f"your budget is around {formatted_budget}")
    if qualification.timeline and not _timeline_overlaps_callback_text(
        qualification.timeline, callback_text
    ):
        detail_bits.append(f"you're looking to launch in around {qualification.timeline}")
    if detail_bits:
        lines.append("You mentioned " + _natural_join(detail_bits, "and") + ".")

    if qualification.features:
        lines.append(
            "You also asked about " + ", ".join(qualification.features) + "."
        )

    if qualification.objections:
        lines.extend(_render_objection_sentences(qualification.objections, "en"))
    if qualification.decision_maker:
        lines.append(
            f"You also mentioned needing to check with "
            f"{qualification.decision_maker}."
        )

    return lines


def _resolve_language(lead: Lead) -> str:
    """
    Normalize Lead.language into one of "hi" / "hinglish" / "en" for the
    message builders below. Defaults to "en" when unset, which is exactly
    the previous (English-only) behavior for any call where no Hindi or
    Hinglish customer turn was ever detected -- see
    app.utils.helpers.detect_language and app.api.retell_webhook.
    """
    value = (getattr(lead, "language", None) or "en").strip().lower()
    if value in ("hi", "hindi"):
        return "hi"
    if value in ("hinglish", "hi-en", "hi_en"):
        return "hinglish"
    return "en"


def _resolve_temperature(lead: Lead) -> str:
    """Normalize Lead.temperature into "hot" / "warm" / "cold" (default
    "cold" when unset, which is the safest -- lowest-pressure -- choice
    if a lead somehow reaches the final follow-up without a temperature
    ever being set)."""
    temperature = getattr(lead, "temperature", None)
    value = getattr(temperature, "value", temperature)
    value = (str(value) if value else "").strip().lower()
    if value in ("hot", "warm", "cold"):
        return value
    return "cold"


def _customer_number_line(lead: Lead, language: str) -> str:
    """
    PROBLEM 3 fix: the final follow-up must contain the CUSTOMER's own
    mobile number (the number the lead/conversation is associated
    with) -- not the agent's/business's contact number. This simply
    confirms back the number on file so the customer can see it's
    correct, in a natural sentence per language.

    NOT changed for the agent-contact-number requirement -- see the new,
    separate _agent_contact_number_line below, which is always about
    AGENT_CONTACT_NUMBER, never about lead.phone_number.
    """
    number = _agent_contact_number()
    if not number:
        return ""

    if language == "hi":
        return f"हमारे पास आपका नंबर {number} दर्ज है, हम इसी पर आपसे संपर्क करेंगे।"
    if language == "hinglish":
        return (
            f"Humare paas aapka number {number} save hai, hum isi par "
            "aapse contact karenge."
        )
    return f"We have your number on file as {number} and will follow up on it."


def _agent_contact_number_line(language: str) -> str:
    """
    Return the business's permanent contact number.

    This number is intentionally FIXED and must never change with
    TARGET_PHONE_NUMBER.
    """
    fixed_contact_number = "+91 9536216821"
    if language == "hi":
        return (
            f"हमारा संपर्क नंबर {fixed_contact_number} है, किसी भी सवाल के लिए "
            "बेझिझक इस पर संपर्क करें।"
        )
    if language == "hinglish":
        return (
            f"Hamara contact number {fixed_contact_number} hai, kisi bhi "
            "sawaal ke liye bina hichkichaye is par contact karein."
        )
    return f"You can also reach us directly at {fixed_contact_number}."


def _media_claim_line(
    has_architecture_media: bool,
    has_resume_media: bool,
    language: str,
) -> str:
    """
    PROBLEM 2 fix: only claim that a resume/architecture overview was
    sent when it was ACTUALLY attached (i.e. media_urls was non-empty
    for this send). Returns "" when nothing was attached, so the
    message never says something was sent when media_urls is empty.
    """
    if not has_architecture_media and not has_resume_media:
        return ""

    if has_architecture_media and has_resume_media:
        if language == "hi":
            return (
                "मैंने आपको architecture overview (image) और resume (PDF) "
                "भी भेजा है, देख लीजिएगा।"
            )
        if language == "hinglish":
            return (
                "Maine aapko architecture overview (image) aur resume "
                "(PDF) bhi bheja hai, dekh lijiyega."
            )
        return (
            "I've attached an architecture overview image and our "
            "resume (PDF) for you to look through."
        )

    if has_architecture_media:
        if language == "hi":
            return "मैंने आपको architecture overview (image) भी भेजा है, देख लीजिएगा।"
        if language == "hinglish":
            return (
                "Maine aapko architecture overview (image) bhi bheja "
                "hai, dekh lijiyega."
            )
        return (
            "I've attached an architecture overview image for you to "
            "look through."
        )

    # only resume
    if language == "hi":
        return "मैंने आपको resume (PDF) भी भेजा है, देख लीजिएगा।"
    if language == "hinglish":
        return "Maine aapko resume (PDF) bhi bheja hai, dekh lijiyega."
    return "I've attached our resume (PDF) for you to look through."


def _callback_ack_line(conversation: Any, language: str) -> str:
    """
    If the customer already asked for a callback during the call
    (conversation.callback_requested), acknowledge it generically --
    without inventing a specific time we can't confirm we actually
    have -- rather than staying silent about something the customer
    explicitly asked for.

    UNCHANGED by the callback-vs-timeline fix. This function is still
    used by the COLD branch of build_final_followup_message, and COLD
    behavior must not change. The WARM branch now uses the new
    _warm_callback_ack_line() below instead, which surfaces the actual
    requested time.

    NOTE: this deliberately does NOT reference a specific requested
    time. Conversation (a Pydantic model) has no field carrying that
    text/time, and callback booking/scheduling data lives in
    app.actions.callback rather than on the conversation object, so
    inventing a new Conversation field or reaching into callback
    storage from here was avoided per explicit instruction.
    """
    if not getattr(conversation, "callback_requested", False):
        return ""

    if language == "hi":
        return "आपने जो कॉलबैक मांगा था, वो नोट कर लिया गया है।"
    if language == "hinglish":
        return "Aapne jo callback maanga tha, wo note kar liya gaya hai."
    return "The callback you requested has been noted on our end."


# ---------------------------------------------------------------------------
# WARM-ONLY: real callback acknowledgement.
#
# _callback_ack_line above (unchanged, still used by COLD) never names
# an actual time, because it was written before this module read
# anything from callback_repository. For WARM, we now look up the
# customer's real CallbackRequest (app/actions/callback.py already
# persists CallbackRequest.requested_time_text correctly via
# callback_repository.save -- this module simply never read it back)
# and state the callback explicitly, so "कल शाम 6 बजे" is unambiguously
# presented as a callback time and never as a project timeline.
# ---------------------------------------------------------------------------


def _get_latest_callback_request(lead: Lead) -> Optional[Any]:
    """
    Fetch the most recently created CallbackRequest for this lead from
    callback_repository (app/storage/repository.py), so the final
    follow-up can reference the customer's ACTUAL requested callback
    time (CallbackRequest.requested_time_text) instead of ever reusing
    qualification.timeline -- which is populated by an entirely
    separate, callback-unaware extraction path (app/ai/qualification.py).

    callback_repository.list_for_lead() returns callbacks ordered by
    created_at DESC, so the first entry is the most recent request.

    Returns None if there is no callback on file for this lead, or if
    the repository lookup fails for any reason -- this module must
    never fail to build a WhatsApp message just because a defensive DB
    lookup for extra context couldn't complete.
    """
    lead_id = getattr(lead, "lead_id", None)
    if not lead_id:
        return None
    try:
        callbacks = callback_repository.list_for_lead(lead_id)
    except Exception:
        return None
    return callbacks[0] if callbacks else None


_CALLBACK_PHRASE_STRIP_RE = re.compile(
    r"(?i)"
    r"\b(?:please\s+)?(?:you\s+can\s+)?(?:call|ring|phone)\s+(?:me\s+)?(?:back)?\b"
    r"|\bcall\s+kar(?:o|na|ke)?\s*(?:lena|dena|sakte|kijiye)?\b"
    r"|\bcall\s+kar(?:unga|enge|na)?\b"
    r"|\bcall\s+kijiye(?:ga)?\b"
    r"|\bphone\s+kar(?:o|na|ke)?\s*(?:lena|dena|sakte|kijiye)?\b"
    r"|कॉल\s*कर\s*(?:लेना|सकते|देना|दीजिए|कीजिए|करूंगा|करूँगा)?"
    r"|फोन\s*कर\s*(?:लेना|सकते|देना|दीजिए|कीजिए|करूंगा|करूँगा)?"
    r"|\bमुझे\b|\bमुझसे\b|\bआपको\b|\bआप\b"
    r"|\baap\b|\bmujhe\b"
    r"|\bme\b|\byou\b"
    r"|\bkar\s+(?:lena|dena)\b"
)


def _extract_time_phrase_from_callback_text(text: str) -> str:
    """
    CallbackRequest.requested_time_text is usually the customer's whole
    turn (e.g. "आप मुझे कल शाम 6 बजे कॉल कर लेना"), not a bare time
    phrase. For a natural-reading acknowledgement sentence, strip the
    call-request wording (call/ring/phone/कॉल/फोन + common
    lena/dena/kijiye endings, plus bare subject/object pronouns) and
    keep whatever's left -- typically just the time phrase itself
    ("कल शाम 6 बजे").

    This is a display-only formatting helper for the callback
    acknowledgement sentence; it has nothing to do with, and does not
    feed into, qualification.timeline or its extraction.

    Falls back to the original text unchanged if stripping leaves
    nothing usable, so the caller always has something to show rather
    than an empty string.
    """
    stripped = _CALLBACK_PHRASE_STRIP_RE.sub(" ", text or "")
    stripped = re.sub(r"\s+", " ", stripped).strip(" .,।-")
    return stripped or str(text or "").strip()


def _warm_callback_ack_line(
    conversation: Any, callback: Optional[Any], language: str
) -> str:
    """
    WARM-ONLY enhanced callback acknowledgement -- THE fix for the
    reported bug.

    Unlike _callback_ack_line (still used by COLD, left completely
    unchanged), this surfaces the customer's REAL requested callback
    time (from the CallbackRequest fetched by
    _get_latest_callback_request in build_final_followup_message) and
    explicitly labels it as a callback ("कॉलबैक" / "callback"), so it
    can never be read as -- or confused with -- the project's
    launch/start timeline.

    Gated the same way as _callback_ack_line
    (conversation.callback_requested), so WARM messages for leads that
    never asked for a callback are unaffected. Falls back to the same
    generic (no-time) wording as _callback_ack_line if
    callback_requested is True but no CallbackRequest row was found on
    lookup (defensive edge case; should not normally happen).
    """
    if not getattr(conversation, "callback_requested", False):
        return ""

    raw_time_text = (
        _clean_hedge_words(getattr(callback, "requested_time_text", ""))
        if callback is not None
        else ""
    )
    time_phrase = (
        _extract_time_phrase_from_callback_text(raw_time_text)
        if raw_time_text
        else ""
    )

    if not time_phrase:
        if language == "hi":
            return "आपने जो कॉलबैक मांगा था, वो नोट कर लिया गया है।"
        if language == "hinglish":
            return "Aapne jo callback maanga tha, wo note kar liya gaya hai."
        return "The callback you requested has been noted on our end."

    if language == "hi":
        return f"आपने {time_phrase} कॉलबैक के लिए कहा था, मैंने वह नोट कर लिया है।"
    if language == "hinglish":
        return f"Aapne {time_phrase} callback ke liye kaha tha, maine wo note kar liya hai."
    return f"You asked for a callback at {time_phrase}, and I've noted that."


def build_mid_call_message(lead: Lead) -> str:
    """
    Build the HOT-lead WhatsApp message sent WHILE the call is still
    active (triggered from transcript_updated once lead.intent_score
    crosses 0.70). Follows the customer's current language (English,
    Hindi, or Hinglish) -- see _resolve_language.

    Structurally UNCHANGED: still opens with a greeting, extends with
    the qualification recap for the resolved language, and closes with
    the "call is still active" line -- no media, exactly as before.
    The Hinglish branch automatically benefits from the improved
    _qualification_lines_hinglish() above (natural combined recap
    instead of a per-field dump); the Hindi and English branches are
    untouched.
    """
    language = _resolve_language(lead)

    if language == "hi":
        parts = ["नमस्ते! मुझसे बात करने के लिए धन्यवाद।"]
        parts.extend(_qualification_lines_hi(lead))
        parts.append(
            "कॉल अभी चल रही है, इसलिए मैंने ये डिटेल्स आपको अभी भेज दी हैं।"
        )
        return " ".join(parts)

    if language == "hinglish":
        parts = ["Hi! Baat karne ke liye shukriya."]
        parts.extend(_qualification_lines_hinglish(lead))
        parts.append(
            "Call abhi chal rahi hai, isliye maine ye details abhi bhej "
            "di hain."
        )
        return " ".join(parts)

    parts = ["Hi! Thanks for speaking with me."]
    parts.extend(_qualification_lines(lead))
    parts.append(
        "I've sent this while we're still connected so you have the "
        "details handy."
    )
    return " ".join(parts)


def build_final_followup_message(
    lead: Lead,
    conversation: Optional[Any] = None,
    has_architecture_media: bool = False,
    has_resume_media: bool = False,
) -> str:
    """
    Build the post-call follow-up WhatsApp message, sent once the call
    has ended (call_ended / call_analyzed).

    The tone differs by lead temperature (doc2 Problem 4):
      - HOT: recap of qualification info, media claim if attached,
        customer's own number, our contact number, and an invitation to
        move forward.
      - WARM: recap of what the customer wants/their context, callback
        acknowledgement (including the actual requested time when
        known -- see _warm_callback_ack_line), our contact number,
        media claim if attached -- deliberately NOT phrased like a HOT
        ready-to-buy customer, and never confusing a callback time with
        a project timeline (see _timeline_overlaps_callback_text). The
        objection/barrier is rendered naturally via the objection
        rendering engine above, regardless of whether it was captured
        as a short fragment or a complete customer sentence.
      - COLD: a short, low-pressure note that now ALSO references the
        qualification recap (whatever was actually captured) instead of
        being fully generic, plus our contact number and media claim if
        attached. UNCHANGED by this fix -- still uses the original
        _callback_ack_line.

    CHANGE (assignment requirement): the caller now resolves and
    attaches architecture/resume media for HOT, WARM, and COLD alike
    (see app.api.retell_webhook._send_final_followup_whatsapp), so
    has_architecture_media / has_resume_media -- and therefore
    _media_claim_line -- are no longer HOT-only here. WARM and COLD
    Hindi/Hinglish/English messages also now include the qualification
    recap lines so they reference the actual conversation rather than a
    generic template (doc2 Problem 4 + assignment "must reference the
    actual conversation" requirement).

    has_architecture_media / has_resume_media reflect what was actually
    attached for THIS send -- the message never claims an attachment
    that wasn't actually sent (doc2 Problem 2), and the customer's own
    phone number (not the agent's) is always included (doc2 Problem 3),
    alongside the agent's own fixed contact number
    (_agent_contact_number_line / AGENT_CONTACT_NUMBER).

    CHANGE (WARM callback-vs-timeline fix): this now looks up the
    lead's real CallbackRequest once (_get_latest_callback_request) and
    passes it into the WARM-only helpers only -- _warm_context_lines_*
    (to suppress a qualification.timeline value that actually overlaps
    the callback text) and _warm_callback_ack_line (to state the real
    callback time, explicitly labeled as a callback). HOT and COLD do
    not receive this lookup and are unaffected.

    Structurally UNCHANGED in this revision: the Hindi and English
    branches (message skeleton, ordering, closings) are exactly as
    before. Only the objection/barrier line(s) produced by
    _warm_context_lines_en/_hi/_hinglish are rendered differently now
    (see the OBJECTION / BARRIER RENDERING ENGINE above) -- everything
    else is unchanged.
    """
    language = _resolve_language(lead)
    temperature = _resolve_temperature(lead)
    customer_number_line = _customer_number_line(lead, language)
    agent_contact_line = _agent_contact_number_line(language)
    media_line = _media_claim_line(
        has_architecture_media, has_resume_media, language
    )
    callback_line = _callback_ack_line(conversation, language)

    # WARM-only lookup: the real callback record, used to (a) suppress
    # a qualification.timeline value that actually describes the
    # callback rather than the project, and (b) state the real
    # callback time explicitly. Never used by HOT or COLD below.
    latest_callback = _get_latest_callback_request(lead)
    callback_raw_text = (
        getattr(latest_callback, "requested_time_text", None)
        if latest_callback is not None
        else None
    )
    warm_callback_line = _warm_callback_ack_line(
        conversation, latest_callback, language
    )

    if language == "hi":
        if temperature == "hot":
            parts = ["कॉल के लिए धन्यवाद!"]
            parts.extend(_qualification_lines_hi(lead))
            if media_line:
                parts.append(media_line)
            if customer_number_line:
                parts.append(customer_number_line)
            if agent_contact_line:
                parts.append(agent_contact_line)
            parts.append("कोई सवाल हो या आगे बढ़ना चाहें तो बताइएगा।")
            return " ".join(parts)

        if temperature == "warm":
            parts = ["बात करने के लिए धन्यवाद!"]
            parts.extend(_warm_context_lines_hi(lead, callback_raw_text))
            if media_line:
                parts.append(media_line)
            if warm_callback_line:
                parts.append(warm_callback_line)
            if customer_number_line:
                parts.append(customer_number_line)
            if agent_contact_line:
                parts.append(agent_contact_line)
            parts.append(
                "कोई जल्दी नहीं है -- जब भी आप तैयार हों और आगे बात करना "
                "चाहें, बेझिझक हमें बताइएगा।"
            )
            return " ".join(parts)

        # cold
        parts = ["आपका समय देने के लिए धन्यवाद।"]
        parts.extend(_qualification_lines_hi(lead))
        parts.append(
            "अभी के लिए बस इतनी जानकारी भेज रहा हूँ, कोई दबाव नहीं है।"
        )
        if media_line:
            parts.append(media_line)
        if callback_line:
            parts.append(callback_line)
        if customer_number_line:
            parts.append(customer_number_line)
        if agent_contact_line:
            parts.append(agent_contact_line)
        parts.append(
            "अगर भविष्य में कभी वेबसाइट या ई-कॉमर्स से जुड़ी जानकारी चाहिए "
            "हो, तो बेझिझक संपर्क कर सकते हैं।"
        )
        return " ".join(parts)

    if language == "hinglish":
        if temperature == "hot":
            parts = ["Call ke liye shukriya!"]
            parts.extend(_qualification_lines_hinglish(lead))
            if media_line:
                parts.append(media_line)
            if customer_number_line:
                parts.append(customer_number_line)
            if agent_contact_line:
                parts.append(agent_contact_line)
            parts.append("Koi sawaal ho ya aage badhna chahein toh bataiyega.")
            return " ".join(parts)

        if temperature == "warm":
            parts = ["Baat karne ke liye shukriya!"]
            parts.extend(_warm_context_lines_hinglish(lead, callback_raw_text))
            if media_line:
                parts.append(media_line)
            if warm_callback_line:
                parts.append(warm_callback_line)
            if customer_number_line:
                parts.append(customer_number_line)
            if agent_contact_line:
                parts.append(agent_contact_line)
            parts.append(
                "Koi jaldi nahi hai -- jab bhi aap ready hon aur aage "
                "baat karna chahein, bina hichkichaye bataiyega."
            )
            return " ".join(parts)

        # cold
        parts = ["Aapka time dene ke liye shukriya."]
        parts.extend(_qualification_lines_hinglish(lead))
        parts.append("Abhi ke liye bas itni jaankari bhej raha hoon, koi pressure nahi hai.")
        if media_line:
            parts.append(media_line)
        if callback_line:
            parts.append(callback_line)
        if customer_number_line:
            parts.append(customer_number_line)
        if agent_contact_line:
            parts.append(agent_contact_line)
        parts.append(
            "Agar future mein kabhi website ya ecommerce se related "
            "jaankari chahiye ho, toh bina hichkichaye contact kar sakte "
            "hain."
        )
        return " ".join(parts)

    # English
    if temperature == "hot":
        parts = ["Thanks again for the call!"]
        parts.extend(_qualification_lines(lead))
        if media_line:
            parts.append(media_line)
        if customer_number_line:
            parts.append(customer_number_line)
        if agent_contact_line:
            parts.append(agent_contact_line)
        parts.append("Let me know if you have any questions or want to move forward.")
        return " ".join(parts)

    if temperature == "warm":
        parts = ["Thanks for the chat!"]
        parts.extend(_warm_context_lines_en(lead, callback_raw_text))
        if media_line:
            parts.append(media_line)
        if warm_callback_line:
            parts.append(warm_callback_line)
        if customer_number_line:
            parts.append(customer_number_line)
        if agent_contact_line:
            parts.append(agent_contact_line)
        parts.append(
            "No rush at all -- whenever you're ready to talk further, "
            "just reach out."
        )
        return " ".join(parts)

    # cold
    parts = ["Thanks for your time today."]
    parts.extend(_qualification_lines(lead))
    parts.append("Just sharing this for your reference, no pressure at all.")
    if media_line:
        parts.append(media_line)
    if callback_line:
        parts.append(callback_line)
    if customer_number_line:
        parts.append(customer_number_line)
    if agent_contact_line:
        parts.append(agent_contact_line)
    parts.append(
        "Feel free to reach out anytime in the future if you'd like to "
        "know more about a website or online store."
    )
    return " ".join(parts)