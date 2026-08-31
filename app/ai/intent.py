"""
Buying-intent analysis.

Context-aware, priority-ordered classification:
  1. Explicit negative / COLD evidence
  2. Barrier evidence (real need, but something is blocking immediate purchase)
  3. Immediate buying / next-step evidence (HOT)
  4. Genuine project / general-interest evidence (WARM)
  5. Nothing -> COLD

A numeric 0-1 score is still produced (for logging / ranking / any code that
sorts leads by score), but the score is clamped into the band that matches
the decision actually made, so score-based thresholds elsewhere in the app
(>=0.70 == HOT, >=0.30 == WARM) stay consistent with this module's verdict.
"""
import re
from dataclasses import dataclass
from typing import List

from app.core.models import IntentResult, LeadTemperature


# ---------------------------------------------------------------------------
# Pattern families
# ---------------------------------------------------------------------------

# 1. Explicit negative / no-intent language.
NEGATIVE_PATTERNS = [
    r"\b(?:just|only)\s+(?:looking|checking|curious|browsing)\b",
    r"\bnot\s+sure\b(?!\s+(?:about\s+the\s+)?(?:number|budget|timeline|features))",
    r"\bmaybe\s+later\b",
    r"\bnot\s+interested\b",
    r"\bno\s+plans?\b",
    r"\bnot\s+planning\b",
    r"\bnot\s+looking\s+to\s+build\b",
    r"\bnot\s+looking\b",
    r"\b(?:do\s+not|don't)\s+have\s+a\s+project\b",
    r"\bno\s+project\s*(?:right\s+now|yet)?\b",
    r"\bsometime\s+in\s+the\s+future\b",
    r"\bsome\s+time\s+in\s+the\s+future\b",
    r"\bnot\s+anytime\s+soon\b",
    r"\b(?:do\s+not|don't)\s+need\s+(?:a\s+)?website\s*(?:right\s+now)?\b",
    r"\bnothing\s+concrete\b",
    r"\bstill\s+figuring\s+out\s+if\b",
    r"\bnot\s+sure\s+(?:if|whether)\s+we\s+(?:even\s+)?need\b",
]

# 2. Barrier language: real need, something is blocking immediate purchase.
BARRIER_PATTERNS = [
    r"\bbudget\s+is\s+(?:not\s+much|limited|tight|small)\b",
    r"\bnot\s+much\s+budget\b",
    r"\b(?:don't|do\s+not)\s+have\s+(?:much\s+)?budget\b",
    r"\bbudget\s+(?:is\s+)?(?:not\s+)?(?:available|there)?\s*right\s+now\b",
    r"\bbudget\s+(?:constraint|issue|problem)\b",
    r"\b(?:my|our)\s+(brother|sister|partner|husband|wife|manager|boss|team|"
    r"board|co-founder|cofounder)\s+(?:handles?|decides?|makes?\s+the\s+"
    r"(?:final\s+)?decision)\b",
    r"\b(?:need\s+to\s+)?(?:discuss|talk\s+to|check\s+with)\s+(?:it\s+)?"
    r"(?:with\s+)?(?:my|our)\s+\w+\b",
    r"\bneed(?:s)?\s+(?:to\s+get\s+)?approval\b",
    r"\bnot\s+ready\s+(?:to\s+start\s+)?yet\b",
    r"\bnot\s+ready\b",
    r"\bmaybe\s+next\s+(?:quarter|month|year)\b",
    r"\bprobably\s+next\s+(?:quarter|month|year)\b",
    r"\bnot\s+until\s+next\s+(?:quarter|month|year)\b",
    r"\bnext\s+quarter\b",
    r"\bcomparing\s+(?:a\s+few|other|some)?\s*(?:companies|vendors|options|"
    r"agencies)\b",
    r"\bstill\s+(?:deciding|evaluating|thinking\s+it\s+over)\b",
    r"\binternal\s+discussion\b",
    r"\brun\s+it\s+by\s+(?:my|our)\s+\w+\b",
    r"\bnot\s+(?:really\s+)?the\s+right\s+time\b",
    r"\babove\s+(?:our\s+|my\s+)?budget\b",
    r"\babove\s+what\s+we\s+can\s+spend\b",
    r"\bmore\s+than\s+(?:we|our)\s+(?:can\s+spend|budget)\b",
    r"\bmaybe\s+(?:next|this)\s+(?:day|week|month|quarter|year)\b",
    r"\bprobably\s+(?:next|this)\s+(?:day|week|month|quarter|year)\b",
]

# 3. Explicit buying / next-step language (HOT).
HOT_PATTERNS = [
    r"(?<!not\s)\bready\s+to\s+(?:start|proceed|go|begin)\b",
    r"\bwant\s+to\s+proceed\b",
    r"\bwant\s+to\s+get\s+started\b",
    r"\bmove\s+forward\b",
    r"\bmove\s+ahead\b",
    r"\blet'?s\s+(?:do\s+it|proceed|move\s+ahead|go\s+ahead|get\s+started)\b",
    r"\bwant\s+to\s+go\s+ahead\b",
    r"\bwhen\s+can\s+(?:you|we)\s+(?:start|begin)\b",
    r"\bwhen\s+could\s+(?:you|we)\s+(?:start|begin)\b",
    r"\bhow\s+soon\s+can\s+you\s+start\b",
    r"\bhow\s+soon\b",
    r"\bhow\s+quickly\s+(?:can|could)\s+you\s+(?:build|deliver|do|start)\b",
    r"\bcan\s+you\s+start\b",
    r"\bcan\s+we\s+(?:start|begin)\b",
    r"\bcould\s+we\s+begin\b",
    r"\bwhat\s+is\s+the\s+price\b",
    r"\bwhat'?s\s+the\s+price\b",
    r"\bwhat'?s\s+the\s+cost\b",
    r"\bwhat\s+is\s+the\s+cost\b",
    r"\bhow\s+much\s+(?:does|will|would)\s+(?:it|this|the\s+\w+(?:\s+\w+)?)\s+"
    r"cost\b",
    r"\bhow\s+much\s+is\s+it\b",
    r"\bhow\s+much\s+would\s+i\s+need\s+to\s+pay\b",
    r"\bwhat\s+would\s+i\s+need\s+to\s+pay\b",
    r"\bwhat\s+would\s+(?:it|this)\s+cost\b",
    r"\b(?:need|just\s+need)\s+to\s+know\s+the\s+price\b",
    r"\bsend\s+me\s+the\s+details\b",
    r"\bsend\s+the\s+details\b",
    r"\bsend\s+me\s+the\s+information\b",
    r"\bplease\s+send\s+(?:me\s+)?the\s+details\b",
    r"\beverything\s+sounds\s+good\b",
    r"\bi\s+want\s+to\s+proceed\b",
    r"\bwe\s+are\s+ready\s+to\s+start\b",
    r"\bi\s+need\s+it\s+urgently\b",
    r"\bi\s+want\s+it\s+asap\b",
    r"\bneed\s+it\s+asap\b",
    r"\b(?:get\s+started|get\s+going|get\s+this\s+rolling|kick\s+this\s+off)\b",
    r"\bwhen\s+could\s+you\s+(?:actually\s+)?get\s+going\b",
    r"\bwhat\s+(?:do\s+we|do\s+i|are\s+the)\s+(?:need\s+to\s+do\s+)?next\s*"
    r"steps?\b",
    r"\bwhat\s+do\s+(?:we|i)\s+need\s+to\s+do\s+next\b",
    r"\bi'?m\s+in\b",
    r"\bsend\s+it\s+over\b",
    r"\bgo\s+ahead\s+and\s+send\b",
    r"\bhow\s+much\s+is\s+(?:it|this|that|the\s+whole\s+thing)\b",
    r"\b(?:just\s+)?tell\s+me\s+the\s+(?:number|price|cost)\b",
    r"\bbasically\s+decided\b",
]

# 3b. Firm / urgent timelines imply "act now", distinct from vague ones.
URGENT_TIMELINE_PATTERNS = [
    r"\bbefore\s+next\s+(?:day|week|month|year)\b",
    r"\bbefore\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
    r"\bby\s+next\s+(?:week|month)\b",
    r"\bwithin\s+\d+\s+(?:days?|weeks?)\b",
    r"\basap\b",
    r"\burgently\b",
    r"\bimmediately\b",
]

# 4. General interest / genuine project language (WARM-leaning on its own).
MEDIUM_INTENT_PATTERNS = [
    r"\binterested\b",
    r"\bneed\s+a\s+website\b",
    r"\bneed\s+an?\s+e-?commerce\b",
    r"\blooking\s+for\s+a\s+website\b",
    r"\blooking\s+for\s+an?\s+e-?commerce\b",
    r"\bplanning\s+to\b",
    r"\bwant\s+to\s+build\b",
    r"\bthinking\s+about\b",
    r"\bwould\s+like\b",
    r"\bneed\s+online\b",
    r"\bwe\s+want\b",
    r"\bwe\s+need\b",
    r"\bi\s+like\s+the\s+idea\b",
    r"\btell\s+me\s+more\b",
    r"\bwhat'?s\s+included\b",
    r"\bwhat\s+does\s+(?:it|the\s+package)\s+include\b",
]

PROJECT_PATTERNS = [
    r"\be-?commerce\b",
    r"\bonline\s+store\b",
    r"\bonline\s+shop\b",
    r"\bwebsite\b",
    r"\bonline\s+business\b",
    r"\bonline\s+ordering\b",
    r"\bthe\s+project\s+is\s+ready\b",
    r"\bbusiness\s+(?:and\s+products?\s+)?(?:is|are)\s+ready\b",
    r"\bproducts?\s+ready\b",
    r"\bboutique\b",
    r"\bonline\s+ordering\b",
]

BUDGET_PATTERNS = [
    r"\bbudget\b",
    r"\b₹\s*[\d,]+\b",
    r"\brs\.?\s*[\d,]+\b",
    r"\binr\s*[\d,]+\b",
]

TIMELINE_PATTERNS = [
    r"\bwithin\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
    r"\bwithin\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:days?|weeks?|months?|years?)\b",
    r"\bwithin\s+a\s+(?:day|week|month|year)\b",
    r"\bin\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
    r"\bin\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:days?|weeks?|months?|years?)\b",
    r"\bin\s+a\s+(?:day|week|month|year)\b",
    r"\bbefore\s+next\s+(?:day|week|month|year)\b",
    r"\bnext\s+(?:day|week|month|year)\b",
    r"\bthis\s+(?:week|month|year)\b",
    r"\btomorrow\b",
    r"\bsoon\b",
    r"\basap\b",
    r"\burgently\b",
    r"\bimmediately\b",
]

FEATURE_PATTERNS = [
    r"\bpayment\b",
    r"\bcheckout\b",
    r"\border\s+tracking\b",
    r"\binventory\b",
    r"\bcart\b",
    r"\banalytics\b",
]


def _matches(text: str, patterns: List[str]) -> List[str]:
    return [p for p in patterns if re.search(p, text, flags=re.IGNORECASE)]


def _has(text: str, patterns: List[str]) -> bool:
    return bool(_matches(text, patterns))


@dataclass
class _Signals:
    negative: List[str]
    barrier: List[str]
    hot: List[str]
    urgent_timeline: bool
    medium: List[str]
    project: bool
    has_budget: bool
    has_timeline: bool
    has_feature: bool


def _collect_signals(text: str) -> _Signals:
    negative = _matches(text, NEGATIVE_PATTERNS)
    barrier = _matches(text, BARRIER_PATTERNS)
    hot = _matches(text, HOT_PATTERNS)
    urgent_timeline = _has(text, URGENT_TIMELINE_PATTERNS)
    medium = _matches(text, MEDIUM_INTENT_PATTERNS)
    has_budget = _has(text, BUDGET_PATTERNS)
    has_timeline = _has(text, TIMELINE_PATTERNS)
    has_feature = _has(text, FEATURE_PATTERNS)
    project = _has(text, PROJECT_PATTERNS) or has_budget or has_feature

    return _Signals(
        negative=negative,
        barrier=barrier,
        hot=hot,
        urgent_timeline=urgent_timeline,
        medium=medium,
        project=project,
        has_budget=has_budget,
        has_timeline=has_timeline,
        has_feature=has_feature,
    )


def _decide(sig: _Signals):
    """
    Returns (temperature_str, base_score, reasons)
    temperature_str in {"hot", "warm", "cold"}
    """
    reasons: List[str] = []
    concrete_count = sum(
        [sig.project, sig.has_budget, sig.has_timeline, sig.has_feature]
    )

    # ---- 1. Explicit negative evidence dominates unless a strong,
    #         explicit buying signal is also present. ----
    if sig.negative and not sig.hot and not sig.urgent_timeline:
        reasons.append("Customer expressed uncertainty or low intent.")
        score = 0.15 - 0.05 * (len(sig.negative) - 1)
        return "cold", max(0.0, score), reasons

    # ---- 2. Barrier + explicit buying language together: the immediate
    #         buying action wins. ----
    if sig.barrier and sig.hot:
        reasons.append("Customer used strong buying-intent language.")
        reasons.append(
            "A barrier was mentioned, but immediate buying language "
            "outweighs it."
        )
        return "hot", 0.80, reasons

    # ---- 2b. Barrier alone (with or without a stated project): genuine
    #          need, something blocking immediate purchase. ----
    if sig.barrier:
        reasons.append("Customer described a genuine need with a barrier "
                        "to immediate purchase.")
        if sig.medium or sig.project:
            reasons.append("Customer expressed a genuine business need.")
        score = 0.45 + 0.05 * min(len(sig.barrier), 2)
        return "warm", min(score, 0.65), reasons

    # ---- 3. Explicit HOT language. ----
    if sig.hot:
        reasons.append("Customer used strong buying-intent language.")
        if sig.project:
            reasons.append("Customer described a concrete project.")
        score = 0.75 + 0.05 * min(len(sig.hot) - 1, 2)
        return "hot", min(score, 0.95), reasons

    # ---- 3b. Urgent/firm timeline plus an established project reads as
    #          ready-to-move, even without an explicit HOT phrase. ----
    if sig.urgent_timeline and sig.project:
        reasons.append("Customer provided timeline information.")
        reasons.append("Customer described a concrete project.")
        return "hot", 0.75, reasons

    # ---- 3c. Fully qualified lead: project + budget + timeline (+
    #          features) accumulated across the conversation is strong
    #          enough evidence on its own. ----
    if concrete_count >= 3:
        reasons.append("Customer provided budget information.")
        reasons.append("Customer provided timeline information.")
        reasons.append("Customer described a concrete project.")
        return "hot", 0.75, reasons

    # ---- 4. Genuine interest / project, no barrier, no HOT trigger yet. ----
    if sig.project or sig.medium:
        if sig.medium:
            reasons.append("Customer expressed a genuine business need.")
        if sig.project:
            reasons.append("Customer described a concrete project.")
        if sig.has_budget:
            reasons.append("Customer provided budget information.")
        if sig.has_timeline:
            reasons.append("Customer provided timeline information.")
        if sig.has_feature:
            reasons.append("Customer described requested functionality.")
        score = 0.35 + 0.1 * concrete_count
        return "warm", min(score, 0.65), reasons

    # ---- 5. Nothing at all. ----
    reasons.append("No clear buying-intent signal detected.")
    return "cold", 0.0, reasons


def calculate_intent_score(text: str) -> float:
    normalized = (text or "").strip()
    if not normalized:
        return 0.0
    sig = _collect_signals(normalized)
    _, score, _ = _decide(sig)
    return max(0.0, min(1.0, score))


def analyze_intent(text: str) -> "IntentResult":
    normalized = (text or "").strip()
    if not normalized:
        return IntentResult(
            score=0.0,
            temperature=LeadTemperature.COLD,
            reasons=["No clear buying-intent signal detected."],
            high_intent=False,
        )

    sig = _collect_signals(normalized)
    temperature_str, score, reasons = _decide(sig)

    temperature = {
        "hot": LeadTemperature.HOT,
        "warm": LeadTemperature.WARM,
        "cold": LeadTemperature.COLD,
    }[temperature_str]

    return IntentResult(
        score=max(0.0, min(1.0, score)),
        temperature=temperature,
        reasons=reasons,
        high_intent=temperature_str == "hot",
    )


def analyze_conversation(messages: List[str]) -> "IntentResult":
    combined_text = " ".join(
        message.strip() for message in messages if message and message.strip()
    )
    return analyze_intent(combined_text)