"""
Conversation context management.

This module converts the application's conversation model into
structured context that can be consumed by the AI layer.
"""

from typing import List

from app.core.models import (
    Conversation,
    ConversationMessage,
    Lead,
    MessageRole,
)


def add_message(
    conversation: Conversation,
    role: MessageRole,
    text: str,
    language: str = None,
) -> Conversation:
    """Add a message to the active conversation."""

    message = ConversationMessage(
        role=role,
        text=text.strip(),
        language=language,
    )

    conversation.messages.append(message)

    return conversation


def get_recent_messages(
    conversation: Conversation,
    limit: int = 12,
) -> List[ConversationMessage]:
    """Return the most recent conversation messages."""

    if limit <= 0:
        return []

    return conversation.messages[-limit:]


def format_conversation(
    conversation: Conversation,
    limit: int = 12,
) -> str:
    """
    Convert conversation messages into readable AI context.
    """

    messages = get_recent_messages(conversation, limit)

    if not messages:
        return "No conversation has taken place yet."

    lines = []

    for message in messages:
        role = {
            MessageRole.SYSTEM: "System",
            MessageRole.AGENT: "Agent",
            MessageRole.CUSTOMER: "Customer",
        }.get(message.role, "Unknown")

        lines.append(f"{role}: {message.text}")

    return "\n".join(lines)


def format_lead_context(lead: Lead) -> str:
    """Convert known lead information into concise AI context."""

    qualification = lead.qualification

    lines = []

    if lead.name:
        lines.append(f"Name: {lead.name}")

    if lead.language:
        lines.append(f"Language: {lead.language}")

    if qualification.business_description:
        lines.append(
            f"Business: {qualification.business_description}"
        )

    if qualification.products:
        lines.append(f"Products: {qualification.products}")

    if qualification.product_count is not None:
        lines.append(
            f"Product count: {qualification.product_count}"
        )

    if qualification.budget:
        lines.append(f"Budget: {qualification.budget}")

    if qualification.timeline:
        lines.append(f"Timeline: {qualification.timeline}")

    if qualification.features:
        lines.append(
            "Features: " + ", ".join(qualification.features)
        )

    if qualification.decision_maker:
        lines.append(
            f"Decision maker: {qualification.decision_maker}"
        )

    if qualification.objections:
        lines.append(
            "Objections: " + ", ".join(qualification.objections)
        )

    if lead.temperature:
        lines.append(
            f"Lead temperature: {lead.temperature.value}"
        )

    if lead.conversation_summary:
        lines.append(
            f"Summary: {lead.conversation_summary}"
        )

    if not lines:
        return "No qualification information is known yet."

    return "\n".join(lines)


def build_ai_context(
    conversation: Conversation,
    lead: Lead,
    message_limit: int = 12,
) -> str:
    """Build the complete context supplied to the AI layer."""

    conversation_context = format_conversation(
        conversation,
        limit=message_limit,
    )

    lead_context = format_lead_context(lead)

    return (
        "KNOWN LEAD INFORMATION:\n"
        f"{lead_context}\n\n"
        "CONVERSATION:\n"
        f"{conversation_context}"
    )