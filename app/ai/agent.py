# agent.py
"""
AI sales-agent orchestration.

Coordinates conversation context, qualification, intent analysis,
classification, and response generation.

CHANGE (Hindi agent response fix): RuleBasedProvider.generate() used to
ignore language entirely and always return the same hardcoded English
sentence, even when the conversation's detected language was Hindi
("hi"). AIProvider.generate() and RuleBasedProvider.generate() now
accept an optional `language` parameter, and SalesAgent.
process_customer_message() passes its existing `language` argument
through to the provider. RuleBasedProvider returns a Hindi response
when language == "hi"; every other language (including the existing
"en" default and "hinglish") falls through to the exact same English
sentence as before, so English conversations are unchanged.
"""

from typing import List, Optional, Protocol

from app.ai.classification import classify_and_update
from app.ai.context import (
    add_message,
    build_ai_context,
)
from app.ai.intent import analyze_conversation
from app.ai.qualification import (
    extract_qualification,
    merge_qualification,
)
from app.ai.prompts import build_conversation_prompt
from app.core.models import (
    AIResponse,
    Conversation,
    Lead,
    MessageRole,
)


class AIProvider(Protocol):
    """
    Interface required by an external language-model provider.

    A future provider only needs to implement generate().
    """

    def generate(self, prompt: str, language: str = "en") -> str:
        ...


class RuleBasedProvider:
    """
    Safe fallback provider.

    This exists so the application remains executable before a
    specific LLM provider is connected.
    """

    def generate(self, prompt: str, language: str = "en") -> str:
        """Generate a basic conversational response.

        CHANGE: previously this always returned the English sentence
        below regardless of `language`. It now returns a Hindi
        response when language == "hi"; every other value (including
        "en" and "hinglish") keeps the original English sentence
        unchanged.
        """

        if language == "hi":
            return (
                "बिल्कुल, मैं इसमें आपकी मदद कर सकता हूँ। "
                "आप किस तरह की वेबसाइट बनवाना चाहते हैं, "
                "उसके बारे में थोड़ा बताइए।"
            )

        return (
            "Sure, I can help with that. "
            "Could you tell me a little more about "
            "what you are looking to build?"
        )


class SalesAgent:
    """Main AI sales-agent coordinator."""

    def __init__(
        self,
        provider: Optional[AIProvider] = None,
    ) -> None:
        self.provider = provider or RuleBasedProvider()

    def process_customer_message(
        self,
        conversation: Conversation,
        lead: Lead,
        customer_message: str,
        language: str = "en",
    ) -> AIResponse:
        """Process one customer message."""

        customer_message = customer_message.strip()

        if not customer_message:
            raise ValueError(
                "Customer message cannot be empty."
            )

        # --------------------------------------------------------------
        # 1. Store customer's actual words.
        # --------------------------------------------------------------

        add_message(
            conversation,
            MessageRole.CUSTOMER,
            customer_message,
            language=language,
        )

        # --------------------------------------------------------------
        # 2. Extract qualification information.
        # --------------------------------------------------------------

        qualification_update = extract_qualification(
            customer_message,
            existing=lead.qualification,
        )

        lead.qualification = merge_qualification(
            lead.qualification,
            qualification_update,
        )

        # --------------------------------------------------------------
        # 3. Analyze all customer messages.
        # --------------------------------------------------------------

        customer_messages = [
            message.text
            for message in conversation.messages
            if message.role == MessageRole.CUSTOMER
        ]

        intent_result = analyze_conversation(
            customer_messages
        )

        lead.intent_score = max(
            lead.intent_score,
            intent_result.score,
        )

        # --------------------------------------------------------------
        # 4. Classify the lead.
        # --------------------------------------------------------------

        classify_and_update(
            lead,
            recent_customer_messages=customer_messages,
        )

        # --------------------------------------------------------------
        # 5. Build complete AI context.
        # --------------------------------------------------------------

        ai_context = build_ai_context(
            conversation,
            lead,
        )

        prompt = build_conversation_prompt(
            ai_context,
            customer_message,
        )

        # --------------------------------------------------------------
        # 6. Generate agent response.
        # --------------------------------------------------------------

        response_text = self.provider.generate(
            prompt,
            language=language,
        )

        # --------------------------------------------------------------
        # 7. Store agent response.
        # --------------------------------------------------------------

        add_message(
            conversation,
            MessageRole.AGENT,
            response_text,
            language=language,
        )

        # --------------------------------------------------------------
        # 8. Return the structured result used by later layers.
        # --------------------------------------------------------------

        return AIResponse(
            text=response_text,
            language=language,
            intent=intent_result,
            qualification_updates=qualification_update,
        )


def create_sales_agent(
    provider: Optional[AIProvider] = None,
) -> SalesAgent:
    """Create a configured sales agent."""

    return SalesAgent(
        provider=provider,
    )