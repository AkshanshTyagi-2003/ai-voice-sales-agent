# intent.py
"""
Buying-intent analysis.
"""
import re
from dataclasses import dataclass
from typing import List

from app.core.models import IntentResult, LeadTemperature


_HI_WANT = r"चाह(?:ता|ती|ते)\s+ह(?:ूँ|ूं|ैं|ो|ूँं)"
_HL_WANT = r"chah(?:ta|ti|te)\s+h(?:oon|un|o|ain)"
_HI_HOW_SOON = r"कितन[ीे]\s+जल्दी"
_HL_HOW_SOON = r"kitn[ie]\s+jaldi"

# --------------------------------------------------------------------
# WAIT / DELAY stems.
#
# The generalized "अभी ... चाहता हूं" / "abhi ... chahta hoon"
# immediacy combinators below detect the SHAPE "right now I want to
# <verb>" without caring what the verb is. That is correct for "अभी
# शुरू करना चाहता हूं" (I want to start now) but WRONG for "अभी थोड़ा
# इंतज़ार करना चाहता हूं" (I want to wait a little right now) -- the
# customer is stating a READINESS BARRIER (wants to wait/delay), not
# buying intent, even though it has the same "अभी X चाहता हूं" shape.
#
# Rather than hardcode the one test sentence, this is a reusable
# NEGATIVE LOOKAHEAD covering the general CATEGORY of "wait / hold
# off / think it over / see how it goes" verbs in Hindi and Hinglish,
# so ANY "अभी ... चाहता हूं" whose object is a waiting/delaying verb
# is excluded from the immediacy patterns -- not just this one
# sentence, and this does not touch any English pattern.
# --------------------------------------------------------------------
_HI_WAIT_STEM = (
    r"इंतज़ार|इंतजार|रुकना|रुक|थोड़ा\s+समय|सोचना|सोच(?:ना|ूंगा|ूँगा)?|"
    r"देख(?:ना|ते\s+हैं)|टालना|टाल"
)
_HL_WAIT_STEM = (
    r"intzar|intezaar|wait|ruk(?:na)?|soch(?:na|unga)?|"
    r"dekhte\s+hain|taal(?:na)?"
)

# --------------------------------------------------------------------
# Devanagari-safe word-boundary helper.
#
# Plain \b is unreliable on Devanagari: Python's regex engine does not
# treat combining vowel signs (matras) or the virama as \w characters
# (only base consonants/independent vowels are), so \b fires a
# spurious boundary between a consonant and its own attached vowel
# sign. That lets a short bare pattern like "कल" incorrectly match as
# a substring inside a longer, unrelated word such as "विकल्प"
# ("option") -- "व" + "ि" already reads as a \b boundary to Python
# even though "वि" is a single, inseparable syllable.
#
# The fix is to bound the pattern against the WHOLE Devanagari
# Unicode block (U+0900-U+097F -- this covers independent letters,
# consonants, all matras, and the virama together) instead of \w, via
# lookaround: the match is only accepted when it is not directly
# touching another Devanagari codepoint on either side. This is a
# general-purpose helper, used everywhere a short/bare Devanagari
# token needs a real (not spurious) token boundary -- not a one-off
# fix for "कल" alone.
# --------------------------------------------------------------------
_DEVANAGARI_RANGE = r"\u0900-\u097F"


def _no_devanagari_neighbor(pattern: str) -> str:
    return (
        rf"(?<![{_DEVANAGARI_RANGE}]){pattern}(?![{_DEVANAGARI_RANGE}])"
    )


NEGATIVE_PATTERNS = [
    r"\b(?:just|only)\s+(?:looking|checking|curious|browsing)\b",
    r"\bnot\s+sure\b(?!\s+(?:about\s+the\s+)?(?:exact\s+|specific\s+|"
    r"final\s+)?(?:number|budget|timeline|features))",
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
    r"सिर्फ\s+(?:research|रिसर्च|देख)\s+रहा",
    r"अभी\s+सिर्फ",
    r"कोई\s+(?:project|प्रोजेक्ट)\s+(?:तय|फ़ाइनल|फाइनल|final)\s+नहीं",
    r"अभी\s+कुछ\s+(?:तय|फ़ाइनल|फाइनल)\s+नहीं",
    r"अभी\s+इंटरेस्टेड\s+नहीं",
    r"अभी\s+ज़रूरत\s+नहीं",
    r"(?:मुझे|हमें)\s+.*(?:वेबसाइट|ई-?कॉमर्स|ऑनलाइन\s+स्टोर|ऑनलाइन\s+दुकान).*नहीं\s+(?:चाहिए|चाहती|चाहता)",
    r"(?:मैं|हम)\s+.*(?:वेबसाइट|ई-?कॉमर्स|ऑनलाइन\s+स्टोर|ऑनलाइन\s+दुकान).*नहीं\s+(?:बनवाना|बनवानी|बनाना)\s+(?:चाहता|चाहती|चाहते)",
    r"(?:अभी|फिलहाल)\s+(?:मुझे|हमें)?\s*.*(?:वेबसाइट|ई-?कॉमर्स|ऑनलाइन\s+स्टोर|ऑनलाइन\s+दुकान).*नहीं\s+(?:बनवानी|बनवाना|चाहिए)",
    r"बस\s+ऐसे\s+ही\s+देख\s+रहा",
    r"\bsirf\s+.{0,20}?research\s+kar\s+raha\b",
    r"\babhi\s+sirf\b",
    r"\bkoi\s+project\s+(?:final|tay|tय)\s+nahi",
    r"\bkuch\s+(?:tay|final)\s+nahi\b",
    r"\babhi\s+interested\s+nahi\b",
    r"\babhi\s+zaroorat\s+nahi\b",
    r"\bnot\s+interested\s+(?:any\s*more|anymore)\b",
    r"\bdon'?t\s+want\s+(?:a\s+website\s+)?anymore\b",
    r"\b(?:don'?t|do\s+not)\s+need\s+it\s+anymore\b",
    r"\bdon'?t\s+want\s+to\s+build\s+one\b",
    r"\bdecided\s+not\s+to\s+do\s+it\b",
    r"\bdecided\s+against\s+it\b",
    r"\bchanged\s+my\s+mind\b",
    r"\bdon'?t\s+think\s+we\s+need\s+this\b",
    r"\bi'?ll\s+pass\s*(?:for\s+now)?\b",
    r"\bwe\s+don'?t\s+need\s+one\b",
    r"\bhaven'?t\s+decided\s+anything\b",
    r"\bno,?\s*i\s+don'?t\s+need\s+this\b",
    r"\bno\s+thanks\b",
    r"\bnot\s+right\s+now\b(?!.{0,20}(?:but|however))",
    r"मेरा\s+विचार\s+बदल\s+(?:गया|दिया)\s+है",
    r"\bmind\s+change\s+kar\s+liya\b",
    r"इसमें\s+(?:कोई\s+)?रुचि\s+नहीं",
    r"इसकी\s+(?:अभी\s+)?(?:कोई\s+)?ज़?रूरत\s+नहीं",
    r"(?:हमें|मुझे)\s+(?:अभी\s+)?(?:कोई\s+)?ज़?रूरत\s+नहीं",
    r"\bisme\s+interest\s+nahi\b",
    r"\biski\s+zaroorat\s+nahi\b",
    r"\bhumne\s+decide\s+nahi\s+kiya\b",
    r"हमने\s+.*फैसला\s+नहीं\s+किया",
    r"\bnahi\s+thanks\b",
    r"\bnahi\s+chahiye\b",
    r"नहीं\s+चाहिए",
    r"नहीं\s+बनवा",
    r"बनवा\s+रह[ेा]\s+नहीं",
    r"\bnahi\s+banwa",
    r"कोई\s+(?:इरादा|प्लान|योजना|फैसला|निर्णय)\s+नहीं",
    r"\bkoi\s+(?:irada|plan|yojna|faisla|nirnay)\s+nahi\b",
    r"कोई\s+जल्दी\s+नहीं",
    r"\bkoi\s+jaldi\s+nahi\b",
    r"बस\s+जानकारी",
    r"\bbas\s+jaankari\b",
    r"(?:ज़|ज)रूरत\s+नहीं",
    r"\bzaroorat\s+nahi\b",
    r"\b(?:sirf|bas)\s+information\s+le\s+raha\b",
    r"\b(?:bas|sirf|just)\s+.{0,40}?\binformation\b",
    r"\b(?:bas|sirf|just)\s+(?:cost|price)\s+check\s+kar\s+rah(?:a|i|e)\b",
    r"\b(?:bas|sirf|just)\s+.{0,40}?\bdekh\s+rah(?:a|i|e)\b",
    r"\b(?:bas|sirf|just)\s+.{0,40}?\bjaan\s+rah(?:a|i|e)\b",
    r"\b(?:abhi\s+)?kuch\s+(?:bhi\s+)?decide\s+nahi\b",
    r"\b(?:business|company)\s+hasn'?t\s+started\s*(?:yet)?\b",
    r"\bhaven'?t\s+decided\s+(?:the\s+|a\s+)?budget\b",
    r"\bbusiness\s+(?:properly\s+)?start\s+(?:bhi\s+)?nahi\s+hua\b",
    r"\bbas\s+idea\s+lena\s+tha\b",
    r"(?:बिज़नेस|बिजनेस|व्यवसाय)\s+(?:अभी\s+)?(?:प्रॉपर्ली\s+)?"
    r"शुरू\s+नहीं\s+हुआ",
    r"(?:सिर्फ|बस)\s+.{0,30}?देख\s+रह[ाी]",
    r"कोई\s+plan\s+नहीं",
    r"भविष्य\s+में\s+.{0,20}?देखेंगे",
    r"\bfuture\s+mein\s+dekhenge\b",
    r"\bneed\s+nahi\s+hai\b",

    # -- NEW (research-intent generalization): "सिर्फ/बस X जानना/
    # समझना है/चाहता हूं" ("just want to know/understand X") is the
    # same research-only framing as the existing "सिर्फ जानकारी" /
    # "bas jaankari" fragments above, just with "जानना"/"समझना" ("to
    # know"/"to understand") as the verb instead of the noun
    # "जानकारी"/"information". Generalized with a gap so it covers any
    # topic the customer is asking to understand, not one fixed
    # sentence.
    r"(?:सिर्फ|बस)\s+.{0,30}?(?:जानना|समझना)\s+(?:है|चाहता|चाहती)",
    r"\b(?:sirf|bas|just)\s+.{0,30}?\b(?:janna|samajhna)\b",

    # -- NEW (research-intent generalization): "<topic> ka/ki plan
    # nahi hai" / "प्लान नहीं है" -- a no-current-plan statement
    # without requiring the "कोई"/"koi" prefix the existing pattern
    # needed. Kept generic (not tied to "website") so it generalizes
    # to any noun the customer says has no plan yet.
    r"प्लान\s+नहीं\s+है",
    r"\bplan\s+nahi\s+hai\b",
]

BARRIER_PATTERNS = [
    r"\bbudget\s+is\s+(?:not\s+much|limited|tight|small)\b",
    r"\bnot\s+much\s+budget\b",
    r"\b(?:don't|do\s+not)\s+have\s+(?:much\s+)?budget\b",
    r"\bbudget\s+(?:is\s+)?(?:not\s+)?(?:available|there)?\s*right\s+now\b",
    r"\bbudget\s+(?:constraint|issue|problem)\b",
    r"\b(?:my|our)\s+(brother|sister|partner|husband|wife|manager|boss|team|"
    r"board|co-founder|cofounder)\s+(?:handles?|decides?|makes?\s+the\s+"
    r"(?:final\s+)?(?:decision|call))\b",
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
    r"\b(?:not|isn'?t|is\s+not)\s+(?:really\s+)?the\s+right\s+time\b",
    r"\bright\s+time\s+nahi\b",
    r"\bsahi\s+time\s+nahi\b",
    r"सही\s+समय\s+नहीं",
    r"\babove\s+(?:our\s+|my\s+)?budget\b",
    r"\babove\s+what\s+we\s+can\s+spend\b",
    r"\bmore\s+than\s+(?:we|our)\s+(?:can\s+spend|budget)\b",
    r"\bmaybe\s+(?:next|this)\s+(?:day|week|month|quarter|year)\b",
    r"\bprobably\s+(?:next|this)\s+(?:day|week|month|quarter|year)\b",
    r"\b(?:we'?ll|we\s+will|i'?ll|i\s+will)?\s*start\s+next\s+"
    r"(?:week|month|quarter|year)\b",
    r"\bwant\s+to\s+proceed\s+but\b",
    r"\bready\s+to\s+proceed\s+but\b",
    r"\bi\s+want\s+it\s+but\s+i\s+can'?t\s+start\s+today\b",
    r"\bneed\s+(?:some\s+)?time\s+to\s+(?:think|decide)\b",
    r"\bneed\s+to\s+think\s+about\s+it\b",
    r"\bneed\s+to\s+discuss\s+(?:it\s+)?internally\b",
    r"\bi'?m\s+interested\s+but\s+i\s+need\s+some\s+time\b",
    r"(?:budget|बजट)\s+(?:भी\s+)?(?:तय|decide)\s+नहीं",
    r"\bbudget\s+(?:bhi\s+)?decide\s+nahi\b",
    r"(?:पार्टनर|भाई|मैनेजर|बॉस)\s+(?:ही\s+)?फैसला\s+लेत[ेा]\s+ह[ैे]",
    r"\b(?:partner|bhai|manager|boss)\s+(?:final\s+)?decision\s+"
    r"(?:lega|legi|lete\s+hain|leta\s+hai)\b",
    r"से\s+(?:पहले\s+)?(?:पूछना|बात\s+करनी|डिस्कस\s+करना)\s+होगा",
    r"\b(?:partner|bhai|manager|boss)\s+se\s+(?:pehle\s+)?"
    r"(?:baat\s+karni\s+hogi|discuss\s+karna\s+hai|baat\s+karna\s+hai|"
    r"poochna\s+hoga)\b",
    r"(?:अप्रूवल|अनुमति)\s+लेन[ीा]\s+होगी?",
    r"\bapproval\s+lena\s+hoga\b",
    r"तुलना\s+कर\s+रह[ाी]\s*हूँ?",
    r"\babhi\s+decide\s+nahi\s+kiya\b",
    r"अगले\s+(?:महीने|हफ्ते|क्वार्टर)\s+(?:में\s+)?शुरू\s+करेंगे",
    r"\bagle\s+(?:mahine|hafte|month|week|quarter)\s+start\s+karenge\b",
    r"\bnext\s+(?:month|week|quarter)\s+start\s+karenge\b",
    r"थोड़ा\s+समय\s+चाहिए",
    r"सोचने\s+के\s+लिए\s+समय\s+चाहिए",
    r"\bthoda\s+time\s+chahiye\b",
    r"\bsochne\s+ke\s+liye\s+time\s+chahiye\b",
    r"(?:पार्टनर|partner|भाई|मैनेजर|बॉस)\s+से\s+(?:discuss\s+कर|बात\s+कर)",
    r"(?:budget|बजट)\s+के\s+बारे\s+में\s+बात\s+करनी\s+होगी",
    r"बात\s+करके\s+बताऊंगा",
    r"दूसरी\s+(?:companies|कंपनियों)\s+से\s+(?:भी\s+)?बात\s+कर",
    r"पहले\s+.*\s+से\s+बात\s+करनी\s+होगी",
    r"अभी\s+ready\s+नहीं",
    r"अभी\s+तैयार\s+नहीं",
    r"\bpartner\s+se\s+(?:discuss|baat)\s+kar(?:ke)?\b",
    r"\bbudget\s+ke\s+baare\s+mein\s+baat\s+karni\s+hogi\b",
    r"\bdiscuss\s+karke\s+bataunga\b",
    r"\bdoosri\s+companies\s+se\s+(?:bhi\s+)?baat\s+kar\b",
    r"\bkuch\s+companies\s+compare\s+kar\s+raha\b",
    r"\bcompanies\s+compare\s+kar\s+raha\b",
    r"\babhi\s+ready\s+nahi\b",
    r"\babhi\s+taiyar\s+nahi\b",
    r"बजट\s+.{0,15}?फाइनल\s+नहीं",
    r"\bbudget\s+.{0,15}?final\s+nahi\b",
    r"सोचना\s+पड़ेगा",
    r"\bsochna\s+padega\b",
    r"(?:दोबारा|फिर\s*से)?\s*कॉल\s+कर\s+लेना",
    r"\b(?:dobara|phir\s*se)?\s*call\s+kar(?:o|na)?\s+lena\b",
    r"\bbudget\s+thoda\s+(?:low|kam|kum|tight)\s+hai\b",
    r"\bbudget\s+(?:kam|kum|low)\s+hai\b",
    r"\bzyada\s+budget\s+nahi\b",
    r"\bse\s+(?:pehle\s+)?(?:poochna\s+hoga|baat\s+karni\s+hogi|"
    r"discuss\s+karna\s+hoga)\b",
    r"बजट\s+कम\s+पड़\s*रह[ाी]\s*है",
    r"\bbudget\s+kam\s+pad\s*rah(?:a|i)\s*hai\b",
    r"शुरू\s+नहीं\s+कर\s+पाऊ[ँं]गा",
    r"\bstart\s+nahi\s+kar\s+pa(?:unga|ungi|enge)\b",
    r"\bshuru\s+nahi\s+kar\s+pa(?:unga|ungi|enge)\b",
    r"(?:परिवार|पार्टनर|भाई|बहन|पत्नी|पति|मैनेजर|बॉस|टीम)\s+से\s+"
    r"(?:पहले\s+)?(?:चर्चा|बात|डिस्कस|discuss)\s+(?:करनी|करना)\s+"
    r"(?:है|होगी|होगा)",
    r"\b(?:family|parivar|partner|bhai|manager|boss|team)\s+se\s+"
    r"(?:pehle\s+)?(?:discuss|baat|charcha)\s+kar(?:na|ke|ni)?\s*"
    r"(?:hai|hoga|hogi)?\b",
    r"अप्रूवल\s+लेना\s+बाकी\s+है",
    r"\bapproval\s+lena\s+baaki\s+hai\b",

    # -- NEW (WARM3 root-cause fix): "wants to wait / think it over /
    # hold off" is itself a readiness barrier, in the same family as
    # "not the right time" / "will start next month" already covered
    # above. Split into two shapes since Hindi/Hinglish wait-related
    # words come in two different grammatical forms:
    #   (a) NOUN stems that need "करना"/"karna" ("do") to form a verb
    #       -- "इंतज़ार करना चाहता हूं" ("want to DO waiting").
    #   (b) VERB-INFINITIVE stems that already end in the infinitive
    #       and attach directly to चाहता हूं with no "करना" in between
    #       -- "सोचना चाहता हूं" ("want to think"), never "सोचना करना
    #       चाहता हूं". Treating these the same way (as the single
    #       combined _HI_WAIT_STEM did before) silently failed to
    #       match the very common verb-infinitive phrasing.
    # Both are still reusable CATEGORIES, not fixed sentences.
    r"(?:इंतज़ार|इंतजार|टाल)\s+करना\s+" + _HI_WANT,
    r"(?:रुकना|रुक|सोचना|सोच|देखना|देख|टालना)\s+" + _HI_WANT,
    r"\b(?:intzar|intezaar|wait|taal)\s+karna\s+" + _HL_WANT,
    r"\b(?:ruk(?:na)?|soch(?:na)?|dekh(?:na)?)\s+(?:karna\s+)?" + _HL_WANT,

    # -- NEW (mixed-script decision-maker gap fix): "owner" is called
    # out explicitly (doc1's DECISION_MAKER list: partner/manager/
    # owner/spouse/...) but had no barrier coverage anywhere -- only
    # partner/brother/sister/manager/boss were recognized as a
    # decision-dependency relation noun. Generalized "<relation> se
    # approval/permission lena padega/hoga" and the Devanagari
    # equivalent, covering "owner"/"मालिक" alongside the existing
    # relation nouns, and covering the "padega" ("will have to")
    # verb form the earlier patterns didn't include (only "hoga" was
    # covered).
    r"(?:owner|मालिक|partner|पार्टनर|manager|मैनेजर|boss|बॉस|भाई|bhai)\s+"
    r"(?:से|se)\s+(?:approval|अनुमति|मंज़ूरी|मंजूरी|permission)\s+"
    r"(?:लेना|लेनी|lena)\s+(?:पड़ेगा|पड़ेगी|होगा|होगी|padega|hoga)",
]

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
    r"\bsend\s+me\s+the\s+(?:pricing|price|quote|proposal)\b",
    r"\bplease\s+send\s+(?:me\s+)?the\s+(?:details|information|pricing|"
    r"price|quote)\b",
    r"\bwant\s+to\s+finalize\b",
    r"\bfinalize\s+(?:this|the)\s+deal\b",
    r"\bstart\s+now\b",
    r"\bwant\s+to\s+start\s+now\b",
    r"\bwant\s+to\s+start\b",
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
    r"अभी\s+आगे\s+बढ़ना\s+चाहता",
    r"अभी\s+शुरू\s+करना\s+है",
    r"अभी\s+खरीदना\s+है",
    r"कितन[ीे]\s+जल्दी\s+शुरू\s+कर\s+सकते",
    r"कब\s+से\s+(?:काम\s+)?शुरू\s+कर\s+सकते",
    r"कब\s+शुरू\s+कर\s+सकते",
    r"अभी\s+(?:ready|तैयार)\s+ह[ूं]ं",
    r"आगे\s+बढ़ना\s+चाहता\s+हूं",
    r"proceed\s+करना\s+चाहता",
    r"\bkitne\s+(?:time|din|jaldi)\s+m(?:ei)?n\s+start\s+kar\s+sakte\b",
    r"\bkab\s+se\s+(?:kaam\s+)?start\s+kar\s+sakte\b",
    r"\bkab\s+start\s+kar\s+sakte\b",
    r"\babhi\s+(?:ready|taiyar)\s+h(?:oon|un)\b",
    r"\babhi\s+start\s+karna\s+hai\b",
    r"\babhi\s+khareedna\s+hai\b",
    r"\bready\s+hoon\s+proceed\s+karne\b",
    r"\bstart\s+karna\s+chahta\s+hoon\b",
    r"\bproceed\s+karna\s+chahta\s+hoon\b",
    r"\bmujhe\s+abhi\s+chahiye\b",
    r"\bmove\s+ahead\s+karna\s+chahta\s+hoon\b",
    r"अभी\s+(?!.{0,25}?(?:" + _HI_WAIT_STEM + r")).{0,25}?" + _HI_WANT,
    r"\babhi\s+(?!.{0,30}?(?:" + _HL_WAIT_STEM + r")).{0,30}?" + _HL_WANT,
    _HI_HOW_SOON,
    r"\b" + _HL_HOW_SOON + r"\b",
    r"\b(?:details?|information|price|pricing|documents?)\s+bhej\s+"
    r"d(?:o|ijiye|ena|e\s+dijiye|e\s+do)\b",
    r"\bbhej\s+do\b",
    r"\bbhej\s+dijiye\b",
    r"(?:डिटेल्स|जानकारी|प्राइस|कीमत|दस्तावेज़)\s+भेज\s+"
    r"(?:दीजिए|दो|दे\s+दीजिए|दे\s+दो)",
    r"भेज\s+दीजिए",
    r"भेज\s+दो",
    r"मुझे\s+अभी\s+चाहिए",
    r"फाइनल\s+करना\s+" + _HI_WANT,
    r"चलिए\s+शुरू\s+करते\s+हैं",
    r"चलो\s+शुरू\s+करते\s+हैं",
    r"चलिए\s+आगे\s+बढ़ते\s+हैं",
    r"चलो\s+आगे\s+बढ़ते\s+हैं",
    r"कीमत\s+कितनी\s+है",
    r"कीमत\s+क्या\s+है",
    r"प्राइस\s+क्या\s+है",
    r"शुरू\s+करना\s+" + _HI_WANT,
    r"अगला\s+स्टेप\s+क्या\s+है",
    r"कितने\s+पैसे\s+लगेंगे",
    r"\babhi\s+aage\s+badhna\s+hai\b",
    r"\bprice\s+kya\s+hai\b",
    r"\bkitna\s+.{0,10}?cost\s+aayega\b",
    r"\bnext\s+steps?\s+kya\s+h(?:ain|ai)\b",
    r"\bchalo\s+(?:start|shuru)\s+karte\s+hain\b",
    r"\bmain\s+ready\s+hoon\b",
    r"\bready\s+hoon\b",
    r"\bfinalize\s+karna\s+" + _HL_WANT,
    r"\baage\s+badh(?:na|ne)\s+" + _HL_WANT,
    r"\baage\s+badhna\s+hai\b",
    r"\bstart\s+karna\s+hai\b",
    r"\bproceed\s+karna\s+hai\b",
    r"\bmove\s+ahead\s+karna\s+hai\b",
    r"\bfinalize\s+karna\s+hai\b",
    r"\bprice\s+kitna\s+hai\b",
    r"\bcost\s+kya\s+hai\b",
    r"\bcost\s+kitna\s+aayega\b",
    r"\bkab\s+se\s+start\s+kar\s+sakte\b",
    r"\b(?:cost|price)\s+bata\s+(?:do|dijiye)\b",
    r"\b(?:start|shuru)\s+kar\s+sakte\s+hain\b",
    r"अभी\s+.{0,20}?शुरू\s+कर\s+सकत[ाी]\s+ह(?:ूँ|ूं|ैं)",
    r"\bstart\s+kar\s+sakt(?:a|i|e)\s+h(?:oon|un|ain)\b",
    r"शुरू\s+करने\s+के\s+लिए\s+तैयार\s+ह(?:ूँ|ूं|ैं)",
    r"\bshuru\s+karne\s+ke\s+liye\s+taiyar\s+h(?:oon|un|ain)\b",
    r"बजट\s+तैयार\s+है",
    r"बजट\s+तय\s+है",
    r"\bbudget\s+ready\s+hai\b",
    r"(?:कीमत|प्राइस|डिटेल्स|जानकारी|प्रक्रिया|तरीका)\s+बता\s+"
    r"(?:दीजिए|दीजिये|दो)",
    r"आज\s+ही\s+.{0,25}?(?:शुरू|शुरुआत)(?!\s*नहीं)",
    r"\baaj\s+hi\s+.{0,25}?(?:proceed|shuru|start)\b(?!\s*nahi)",
]

URGENT_TIMELINE_PATTERNS = [
    r"\bbefore\s+next\s+(?:day|week|month|year)\b",
    r"\bbefore\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
    r"\bby\s+next\s+(?:week|month)\b",
    r"\bwithin\s+\d+\s+(?:days?|weeks?)\b",
    r"\basap\b",
    r"\burgently\b",
    r"\bimmediately\b",
    r"जल्द\s+से\s+जल्द",
    r"जल्दी\s+से\s+जल्दी",
    r"\bjaldi\s+se\s+jaldi\b",
    r"\bturant\b",
]

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
    r"वेबसाइट\s+(?:बनवानी|चाहिए)",
    r"ई-?कॉमर्स\s+(?:वेबसाइट)?\s*चाहिए",
    r"मुझे\s+.*\s+बनवानी\s+है",
    r"(?:और|अधिक|थोड़ी\s+और)\s+जानकारी\s+चाहिए",
    r"(?:इस\s+बारे\s+में\s+)?और\s+बताइए",
    r"बताइए\s+और",
    r"\bwebsite\s+banwani\s+hai\b",
    r"\becommerce\s+website\s+banwani\s+hai\b",
    r"\bwebsite\s+chahiye\b",
    r"\becommerce\s+chahiye\b",
    r"\bmujhe\s+.*\s+chahiye\b",
    r"\baur\s+batao\b",
    r"\btell\s+me\s+more\s+chahiye\b",
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
    r"वेबसाइट",
    r"ऑनलाइन\s+स्टोर",
    r"ऑनलाइन\s+दुकान",
    r"ई-?कॉमर्स",
    r"दुकान\s+के\s+लिए",
    r"बनवानी\s+है",
    r"\bbanwani\s+hai\b",
    r"\bdukan\s+ke\s+liye\b",

    # -- NEW (mixed-script project gap fix): a Devanagari "ऑनलाइन"
    # ("online") followed directly by a LATIN business noun
    # ("store"/"shop") is extremely common in real mixed Hindi-English
    # speech (see app/ai/prompts.py's note that customers freely mix
    # scripts for business/technical nouns), but neither the pure-
    # English r"\bonline\s+store\b" pattern (needs Latin "online") nor
    # the pure-Devanagari r"ऑनलाइन\s+स्टोर" pattern (needs Devanagari
    # "स्टोर") matches it -- "ऑनलाइन store" fell through both. This is
    # a CATEGORY fix (Devanagari "online" + any of the common Latin
    # business nouns), not a fix tied to this one sentence.
    r"ऑनलाइन\s+(?:store|shop|स्टोर|दुकान)\b",
]

BUDGET_PATTERNS = [
    r"\bbudget\b",
    r"\b₹\s*[\d,]+\b",
    r"\brs\.?\s*[\d,]+\b",
    r"\binr\s*[\d,]+\b",
    r"बजट",
    r"[\d,]+\s*(?:हज़ार|हजार|लाख)",
    r"[\d,]+\s*(?:lakh|lac|hazar|hazaar)\b",
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
    r"\bnext\s+(?:one|two|three|four|five|\d+)\s+weeks?\b",
    r"\bnext\s+(?:one|two|three|four|five|\d+)\s+(?:days?|months?)\b",
    r"(?:\d+|एक|दो|तीन|चार|पांच|छह|सात|आठ|नौ|दस)\s+"
    r"(?:दिन|हफ्त[ेों]+|महीन[ोे]+|साल)\s+में",
    # NEW (COLD-4 substring false-positive fix): these bare two/three-
    # character Devanagari time words previously had NO boundary at
    # all, so "कल" ("tomorrow/yesterday") matched as a raw substring
    # inside completely unrelated words like "विकल्प" ("option") --
    # exactly the reported bug where a COLD conversation containing
    # "विकल्प" ("I'm just looking at options") got misread as
    # containing a "कल" (tomorrow) timeline.
    #
    # IMPORTANT: plain \b does NOT fix this for Devanagari. Python's
    # regex engine does not classify combining vowel signs (matras)
    # or the virama as \w characters, only base consonants/
    # independent vowels are \w -- so \b creates a spurious boundary
    # between every base letter and its own combining vowel sign
    # (e.g. "वि" = "व" + combining "ि", and \b fires between them),
    # meaning \bकल\b still matches inside "वि|कल्|प". The correct,
    # general fix is a lookaround against the whole Devanagari
    # Unicode block (U+0900-U+097F, covering letters, matras, and the
    # virama together) instead of \w, so a match is only accepted
    # when it is NOT touching another Devanagari character on either
    # side -- i.e. it really is its own token, not a fragment of a
    # longer word. See _no_devanagari_neighbor() below.
    _no_devanagari_neighbor(r"कल"),
    _no_devanagari_neighbor(r"आज"),
    _no_devanagari_neighbor(r"आज\s+रात"),
    _no_devanagari_neighbor(r"परसों"),
    _no_devanagari_neighbor(r"जल्द(?:ी)?"),
    r"इस\s+हफ्ते",
    r"अगले\s+हफ्ते",
    r"अगले\s+महीने",
    r"\bkal\b",
    r"\baaj\b",
    r"\bparso\b",
    r"\bjaldi\b",
    r"\bis\s+hafte\b",
    r"\bagle\s+hafte\b",
    r"\bagle\s+mahine\b",
    r"\b(?:\d+|do|teen|char|paanch)\s+hafto?n?\s+m(?:ei)?n\b",
    r"\b(?:\d+|do|teen|char|paanch)\s+din\s+m(?:ei)?n\b",
    r"\b\d+\s+months?\s+m(?:ei)?n\b",
    r"\b\d+\s+(?:din|hafte|mahino?n?|saal)\s+m(?:ei)?n\b",
    r"\b\d+\s+(?:din|hafte|mahine|mahino|saal|days?|weeks?|months?|years?)"
    r"\s+ke\s+andar\b",
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
    reasons: List[str] = []
    concrete_count = sum(
        [sig.project, sig.has_budget, sig.has_timeline, sig.has_feature]
    )

    if sig.negative and not sig.hot and not sig.urgent_timeline:
        reasons.append("Customer expressed uncertainty or low intent.")
        score = 0.15 - 0.05 * (len(sig.negative) - 1)
        return "cold", max(0.0, score), reasons

    if sig.barrier and sig.hot:
        reasons.append("Customer used strong buying-intent language.")
        reasons.append(
            "A barrier was mentioned, but immediate buying language "
            "outweighs it."
        )
        return "hot", 0.80, reasons

    if sig.barrier:
        reasons.append("Customer described a genuine need with a barrier "
                        "to immediate purchase.")
        if sig.medium or sig.project:
            reasons.append("Customer expressed a genuine business need.")
        score = 0.45 + 0.05 * min(len(sig.barrier), 2)
        return "warm", min(score, 0.65), reasons

    if sig.hot:
        reasons.append("Customer used strong buying-intent language.")
        if sig.project:
            reasons.append("Customer described a concrete project.")
        score = 0.75 + 0.05 * min(len(sig.hot) - 1, 2)
        return "hot", min(score, 0.95), reasons

    if sig.urgent_timeline and sig.project:
        reasons.append("Customer provided timeline information.")
        reasons.append("Customer described a concrete project.")
        return "hot", 0.75, reasons

    if concrete_count >= 3:
        reasons.append("Customer provided budget information.")
        reasons.append("Customer provided timeline information.")
        reasons.append("Customer described a concrete project.")
        return "hot", 0.75, reasons

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