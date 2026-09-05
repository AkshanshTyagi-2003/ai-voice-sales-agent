# callback.py
"""
Callback action layer.

Handles customer callback requests while keeping scheduling
implementation independent from the rest of the application.

CHANGE (callback-text isolation fix):
detect_callback_request previously returned the customer's ENTIRE raw
turn whenever a callback phrase + a parseable time existed ANYWHERE in
it. For a turn like:

    "Mujhe pehle apni wife se discuss karna hai. Aap mujhe parso
    afternoon mein call kar lena."

that meant the unrelated first sentence ("Mujhe pehle apni wife se
discuss karna hai") was included in requested_time_text, even though
it has nothing to do with the callback time.

This is fixed generically -- not by hardcoding this exact sentence --
by identifying which SENTENCE/SEGMENT of the turn actually contains
the callback phrase before treating it as the callback text:

  1. The turn is split into sentences on ".", "!", "?", "।" and
     newlines (the same simple, language-agnostic sentence boundary
     any of these three languages naturally uses).
  2. Each sentence is checked against the callback-phrase pattern
     (_CALLBACK_PHRASE_PATTERN) and validated with the existing
     parse_relative_datetime (unchanged) -- the first sentence that
     both mentions a callback AND contains a parseable time is
     returned as requested_time_text.
  3. If no single sentence satisfies both conditions (e.g. the
     callback phrase and the time genuinely are in different
     sentences), the ORIGINAL whole-text behavior is used as a
     fallback, so no previously-working case regresses.

This keeps CallbackRequest.requested_time_text scoped to the relevant
callback sentence instead of the customer's entire turn, without
touching intent.py, without touching URL/media handling, and without
changing the public request_callback / CallbackManager API.

CHANGE (Hindi/Hinglish "let's talk again" callback-phrase gap --
THIS revision):
_CALLBACK_PHRASE_PATTERN previously only recognized literal
call/phone/कॉल/फोन wording ("call me back", "कॉल कर लेना", etc). A
customer proposing a FOLLOW-UP CONVERSATION without using the word
"call/phone" at all -- e.g. "कल शाम फिर बात कर लेते हैं" ("let's talk
again tomorrow evening") -- is semantically just as much a callback
request (this is explicitly called out as a required case: a
follow-up-conversation proposal should be "recognized as a follow-up
conversation request and scheduled appropriately according to the
application's existing callback scheduling conventions", without
requiring the literal word "callback").

A new, GENERALIZED category was added to _CALLBACK_PHRASE_PATTERN for
this: "(फिर से / फिर / दोबारा) बात कर(ेंगे | लेते/लेंगे हैं)" in
Devanagari, plus the Hinglish (Romanized Hindi) equivalent
"(phir se / phir / dobara) baat kar(enge | lete/lenge hain)".

Deliberately scoped narrowly to avoid false positives and to avoid any
risk of touching English behavior:
  - It REQUIRES an "again" marker (फिर / फिर से / दोबारा / phir /
    phir se / dobara) immediately before "बात कर.../baat kar...", so a
    bare "बात करते हैं" ("let's talk") with no again-marker -- which
    could appear in ordinary small talk unrelated to scheduling a
    follow-up -- does NOT match on its own. This mirrors the same
    conservative design already used for the call/phone patterns
    ("call ... back" requires "back"; the assignment's own examples
    for this category, "फिर से बात कर लेते हैं" / "कल फिर बात कर लेते
    हैं" / "next week call me", all include an explicit again/repeat
    marker).
  - It is written entirely in Devanagari script and Romanized-Hindi
    tokens (फिर/दोबारा/phir/dobara/baat/kar) that do not appear in
    ordinary English sentences, so it cannot fire on English text and
    therefore cannot affect the existing English behavior. No new
    English-language phrase was added to this pattern.
  - As with every existing entry in _CALLBACK_PHRASE_PATTERN,
    detect_callback_request() below still ALSO requires
    parse_relative_datetime() to find a real time in the same
    sentence before treating anything as a callback -- so a bare "फिर
    बात करेंगे" with no time/date phrase in the same sentence still
    will not create a callback. This is what keeps a plain
    timing/deferral remark (e.g. "अगले महीने शुरू करूँगा", "अभी थोड़ा
    इंतज़ार करना चाहता हूँ" -- WARM-barrier language with NO callback
    proposed) from ever being misread as a callback request: neither
    of those sentences contains this pattern's "फिर/दोबारा ... बात
    कर..." shape OR the call/phone wording, so
    detect_callback_request() correctly returns None for them, and no
    callback is invented.

Everything else in this file is UNCHANGED.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from app.core.config import settings
from app.core.models import CallbackRequest, Lead
from app.storage.repository import callback_repository
from app.utils.datetime_parser import parse_relative_datetime
from app.utils.helpers import utc_now

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


@dataclass
class CallbackResult:
    """Result of processing a callback request."""

    success: bool
    callback: Optional[CallbackRequest] = None
    message: str = ""
    raw_response: Optional[Dict[str, Any]] = None


class CallbackScheduler(Protocol):
    """Interface for an external scheduling system."""

    def schedule(
        self,
        callback: CallbackRequest,
    ) -> Optional[datetime]:
        ...


class NaturalLanguageCallbackScheduler:
    """
    Default scheduler: turns the customer's spoken phrasing ("call me
    back tomorrow morning") into a concrete datetime using
    app.utils.datetime_parser, in the business's configured timezone
    (settings.timezone).

    Previously CallbackManager() defaulted to scheduler=None, which
    meant CallbackRequest.scheduled_for was NEVER populated -- not from
    the live call, and not even from the manual /scheduler/callback API
    endpoint -- because nothing computed it. This is the actual
    date/time computation that was missing.
    """

    def _now(self) -> datetime:
        if ZoneInfo is not None:
            try:
                return datetime.now(ZoneInfo(settings.timezone or "Asia/Kolkata"))
            except Exception:
                pass
        return datetime.utcnow()

    def schedule(self, callback: CallbackRequest) -> Optional[datetime]:
        return parse_relative_datetime(
            callback.requested_time_text,
            reference=self._now(),
        )


class CallbackManager:
    """Creates and persists callback requests."""

    def __init__(
        self,
        scheduler: Optional[CallbackScheduler] = None,
    ) -> None:
        self.scheduler = scheduler or NaturalLanguageCallbackScheduler()

    def request_callback(
        self,
        lead: Lead,
        requested_time_text: str,
    ) -> CallbackResult:
        """Create a callback request for a lead."""

        requested_time_text = (
            requested_time_text.strip()
        )

        if not requested_time_text:
            return CallbackResult(
                success=False,
                message=(
                    "Callback time cannot be empty."
                ),
            )

        callback = CallbackRequest(
            lead_id=lead.lead_id,
            requested_time_text=requested_time_text,
            created_at=utc_now(),
        )

        if self.scheduler:
            try:
                callback.scheduled_for = (
                    self.scheduler.schedule(callback)
                )
            except Exception as exc:
                return CallbackResult(
                    success=False,
                    message=(
                        f"Callback scheduling error: {exc}"
                    ),
                )

        callback_repository.save(callback)

        return CallbackResult(
            success=True,
            callback=callback,
            message="Callback request saved successfully.",
        )


class MockCallbackScheduler:
    """
    Test-only scheduler that returns a fixed time instead of parsing.

    Kept for existing tests that construct CallbackManager with an
    explicit scheduler; NOT the default anymore (see
    NaturalLanguageCallbackScheduler above).
    """

    def __init__(
        self,
        scheduled_time: Optional[datetime] = None,
    ) -> None:
        self.scheduled_time = scheduled_time
        self.requests = []

    def schedule(
        self,
        callback: CallbackRequest,
    ) -> Optional[datetime]:
        """Record a simulated scheduling request."""

        self.requests.append(callback)

        return self.scheduled_time


# ---------------------------------------------------------------------------
# Live-call callback detection
# ---------------------------------------------------------------------------
#
# This is the piece that was missing end-to-end: nothing in
# app/api/retell_webhook.py ever looked at a customer's live turn to
# decide "this is a callback request" and call CallbackManager. The
# scheduler existed only as a manual POST /scheduler/callback endpoint,
# so requirement #7/#8 ("If I say call me back tomorrow morning, your
# system understands it and books the callback itself") was never
# exercised during an actual call.
#
# Kept deliberately simple and conservative: a callback phrase alone is
# not enough (avoids false positives on "I'll call back" small talk
# unrelated to scheduling); a bare time phrase alone is not enough
# either (avoids misfiring on "the site should be live by next month"
# being read as a callback). Both a callback-intent phrase AND a
# parseable relative time must be present in the same customer turn.

_CALLBACK_PHRASE_PATTERN = re.compile(
    r"\b(call|ring|phone)\s+(me\s+)?back\b"
    r"|\bcall\s+me\s+(later|again)\b"
    r"|\bschedule\s+a\s+call(back)?\b"
    r"|\bbook\s+a\s+call(back)?\b"
    # "Call me tomorrow at 10 AM.", "Please call me on September 10 at
    # 4 PM." -- bare "call/ring/phone me", with no "back". These are
    # the assignment's own example phrasings (doc2 section 8) and none
    # of them contain "back", so the original "call ... back"-only
    # pattern above never actually matched them. Safe to add broadly:
    # detect_callback_request() below still requires a parseable time
    # in the same turn, so "you can call me anytime" (no time) still
    # will not be treated as a callback.
    r"|\b(call|ring|phone)\s+me\b"
    r"|\bi'?ll\s+call\s+you\b"
    r"|\bi\s+will\s+call\s+you\b"
    # -- Hindi (Devanagari) / Hinglish equivalents ------------------------
    # "call kar lena" / "call karna" / "call kar dena" / "call karunga" /
    # "call kar sakte" (ho/hain) / "call kijiye(ga)", and the same set
    # with "phone" instead of "call" -- these are how a callback is
    # actually asked for or promised in Hindi/Hinglish (see doc2 section
    # 8), unlike English's "call ... back" phrasing.
    r"|\bcall\s+kar(?:o|na|ke)?\s+(?:lena|dena|sakte|kijiye)\b"
    r"|\bcall\s+kar(?:unga|enge|na)\b"
    r"|\bcall\s+kijiye(?:ga)?\b"
    r"|\bphone\s+kar(?:o|na|ke)?\s+(?:lena|dena|kijiye)\b"
    r"|कॉल\s+कर\s+(?:लेना|सकते|देना|दीजिए|कीजिए|करूंगा|करूँगा)"
    r"|फोन\s+कर\s+(?:लेना|सकते|देना|दीजिए|कीजिए|करूंगा|करूँगा)"
    r"|कॉल\s+कर(?:ूंगा|ूँगा|ना)"
    r"|फोन\s+कर(?:ूंगा|ूँगा|ना)"
    # -- NEW (Hindi/Hinglish "let's talk again" follow-up-conversation
    # gap fix -- this revision): a proposal to talk AGAIN, without the
    # literal word call/phone/कॉल/फोन -- e.g. "कल शाम फिर बात कर लेते
    # हैं" ("let's talk again tomorrow evening"). Requires an explicit
    # "again/repeat" marker (फिर / फिर से / दोबारा / phir / phir se /
    # dobara) immediately before the "talk" verb, so an unrelated bare
    # "बात करते हैं" cannot match on its own -- see the module
    # docstring's "CHANGE (Hindi/Hinglish 'let's talk again'
    # callback-phrase gap -- THIS revision)" section for the full
    # rationale, including why this cannot affect English behavior.
    r"|(?:फिर\s*से|फिर|दोबारा)\s+बात\s+कर(?:ेंगे|\s+(?:लेते|लेंगे)\s+ह(?:ैं|ें))"
    r"|\b(?:phir\s*se|phir|dobara)\s+baat\s+kar(?:enge|\s+(?:lete|lenge)\s+h(?:ain|ein))\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# CHANGE (callback-text isolation fix): sentence splitter used to scope
# detection to the sentence that actually contains the callback
# request, instead of the customer's entire turn. Deliberately simple
# and language-agnostic (same terminators used across English, Hindi,
# and Hinglish text in this codebase).
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"[.!?।]+|\n+")


def _split_sentences(text: str) -> List[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [part.strip() for part in parts if part.strip()]


def detect_callback_request(text: str) -> Optional[str]:
    """
    Return the requested-time text if a customer turn is asking to be
    called back at a specific (possibly relative/vague) time, else None.

    This first tries to isolate the SENTENCE within the turn that
    actually contains the callback phrase (and a parseable time), so
    an unrelated sentence elsewhere in the same turn (e.g. a
    partner/decision-maker remark, or an unrelated timing/deferral
    remark such as "अगले महीने शुरू करूँगा") is never included in, or
    mistaken for, the returned callback text. Falls back to the
    previous whole-turn behavior only if no single sentence satisfies
    both conditions, so no existing working case regresses.

    IMPORTANT: a callback is NEVER inferred purely from lead
    temperature or from a general deferral/timing remark -- both a
    recognized callback-intent phrase (_CALLBACK_PHRASE_PATTERN) AND a
    parseable relative time (parse_relative_datetime) must be present
    in the same sentence/turn. A WARM lead that only expresses a
    barrier ("अभी सही समय नहीं है, अगले महीने शुरू करूँगा", "अभी थोड़ा
    इंतज़ार करना चाहता हूँ") with no callback phrase present therefore
    correctly returns None here, and no callback is ever created for
    it.
    """
    if not text:
        return None

    text = text.strip()
    if not text:
        return None

    sentences = _split_sentences(text)
    for sentence in sentences:
        if not _CALLBACK_PHRASE_PATTERN.search(sentence):
            continue
        if parse_relative_datetime(sentence) is None:
            continue
        return sentence

    # Fallback: the callback phrase and the time phrase are spread
    # across sentence boundaries in a way sentence-splitting doesn't
    # cleanly isolate (or there was only ever one sentence to begin
    # with). This mirrors the original whole-text behavior exactly.
    if not _CALLBACK_PHRASE_PATTERN.search(text):
        return None
    if parse_relative_datetime(text) is None:
        return None
    return text