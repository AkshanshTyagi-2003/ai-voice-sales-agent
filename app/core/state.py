"""
In-memory application state.

This manages active conversations and leads while calls are running.
Persistent storage is handled separately by app.storage.
"""

from threading import Lock
from typing import Dict, Optional

from app.core.models import Conversation, Lead


class ApplicationState:
    """Thread-safe in-memory state for active application data."""

    def __init__(self) -> None:
        self._leads: Dict[str, Lead] = {}
        self._conversations: Dict[str, Conversation] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Leads
    # ------------------------------------------------------------------

    def save_lead(self, lead: Lead) -> Lead:
        """Create or update a lead."""
        with self._lock:
            self._leads[lead.lead_id] = lead

        return lead

    def get_lead(self, lead_id: str) -> Optional[Lead]:
        """Retrieve a lead by ID."""
        with self._lock:
            return self._leads.get(lead_id)

    def delete_lead(self, lead_id: str) -> None:
        """Remove a lead from active memory."""
        with self._lock:
            self._leads.pop(lead_id, None)

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def save_conversation(
        self,
        conversation: Conversation,
    ) -> Conversation:
        """Create or update a conversation."""
        with self._lock:
            self._conversations[
                conversation.conversation_id
            ] = conversation

        return conversation

    def get_conversation(
        self,
        conversation_id: str,
    ) -> Optional[Conversation]:
        """Retrieve a conversation by ID."""
        with self._lock:
            return self._conversations.get(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        """Remove a conversation from active memory."""
        with self._lock:
            self._conversations.pop(conversation_id, None)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all in-memory application state."""
        with self._lock:
            self._leads.clear()
            self._conversations.clear()

    @property
    def lead_count(self) -> int:
        """Return the number of leads currently in memory."""
        with self._lock:
            return len(self._leads)

    @property
    def conversation_count(self) -> int:
        """Return the number of conversations currently in memory."""
        with self._lock:
            return len(self._conversations)


state = ApplicationState()