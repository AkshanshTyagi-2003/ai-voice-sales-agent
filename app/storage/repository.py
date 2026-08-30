"""
Persistent repository layer.

Handles saving and retrieving leads, conversations, messages, and
callbacks from the SQLite database.
"""

import json
from datetime import datetime
from typing import List, Optional

from app.core.models import (
    CallbackRequest,
    Conversation,
    ConversationMessage,
    Lead,
)
from app.storage.database import database


def _datetime_to_string(
    value: Optional[datetime],
) -> Optional[str]:
    """Convert datetime to an ISO string."""

    if value is None:
        return None

    return value.isoformat()


def _string_to_datetime(
    value: Optional[str],
) -> Optional[datetime]:
    """Convert an ISO string back into datetime."""

    if not value:
        return None

    return datetime.fromisoformat(value)


class LeadRepository:
    """Persistent operations for leads."""

    def save(self, lead: Lead) -> Lead:
        """Create or update a lead."""

        qualification = lead.qualification

        with database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO leads (
                    lead_id,
                    phone_number,
                    name,
                    language,
                    budget,
                    products,
                    product_count,
                    timeline,
                    features,
                    business_description,
                    decision_maker,
                    objections,
                    temperature,
                    intent_score,
                    conversation_summary,
                    customer_quotes,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead.lead_id,
                    lead.phone_number,
                    lead.name,
                    lead.language,
                    qualification.budget,
                    qualification.products,
                    qualification.product_count,
                    qualification.timeline,
                    json.dumps(qualification.features),
                    qualification.business_description,
                    qualification.decision_maker,
                    json.dumps(qualification.objections),
                    (
                        lead.temperature.value
                        if lead.temperature
                        else None
                    ),
                    lead.intent_score,
                    lead.conversation_summary,
                    json.dumps(lead.customer_quotes),
                    lead.status.value,
                    _datetime_to_string(lead.created_at),
                    _datetime_to_string(lead.updated_at),
                ),
            )

            connection.commit()

        return lead

    def get(
        self,
        lead_id: str,
    ) -> Optional[Lead]:
        """Retrieve a lead by ID."""

        with database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM leads
                WHERE lead_id = ?
                """,
                (lead_id,),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_lead(row)

    def get_by_phone(
        self,
        phone_number: str,
    ) -> Optional[Lead]:
        """Retrieve the most recently created lead for a phone number."""

        with database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM leads
                WHERE phone_number = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (phone_number,),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_lead(row)

    def list_all(self) -> List[Lead]:
        """Return all leads."""

        with database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM leads
                ORDER BY created_at DESC
                """
            ).fetchall()

        return [
            self._row_to_lead(row)
            for row in rows
        ]

    def delete(
        self,
        lead_id: str,
    ) -> bool:
        """Delete a lead."""

        with database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM leads
                WHERE lead_id = ?
                """,
                (lead_id,),
            )

            connection.commit()

        return cursor.rowcount > 0

    @staticmethod
    def _row_to_lead(row) -> Lead:
        """Convert a database row into a Lead model."""

        from app.core.models import (
            LeadTemperature,
            ConversationStatus,
            QualificationData,
        )

        qualification = QualificationData(
            budget=row["budget"],
            products=row["products"],
            product_count=row["product_count"],
            timeline=row["timeline"],
            features=json.loads(
                row["features"] or "[]"
            ),
            business_description=row[
                "business_description"
            ],
            decision_maker=row["decision_maker"],
            objections=json.loads(
                row["objections"] or "[]"
            ),
        )

        return Lead(
            lead_id=row["lead_id"],
            phone_number=row["phone_number"],
            name=row["name"],
            language=row["language"],
            qualification=qualification,
            temperature=(
                LeadTemperature(row["temperature"])
                if row["temperature"]
                else None
            ),
            intent_score=row["intent_score"] or 0.0,
            conversation_summary=(
                row["conversation_summary"] or ""
            ),
            customer_quotes=json.loads(
                row["customer_quotes"] or "[]"
            ),
            status=ConversationStatus(row["status"]),
            created_at=_string_to_datetime(
                row["created_at"]
            ),
            updated_at=_string_to_datetime(
                row["updated_at"]
            ),
        )


class ConversationRepository:
    """Persistent operations for conversations."""

    def save(
        self,
        conversation: Conversation,
    ) -> Conversation:
        """Create or update a conversation."""

        with database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO conversations (
                    conversation_id,
                    lead_id,
                    phone_number,
                    status,
                    language,
                    started_at,
                    ended_at,
                    whatsapp_sent_mid_call,
                    callback_requested,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation.conversation_id,
                    conversation.lead_id,
                    conversation.phone_number,
                    conversation.status.value,
                    conversation.language,
                    _datetime_to_string(
                        conversation.started_at
                    ),
                    _datetime_to_string(
                        conversation.ended_at
                    ),
                    int(
                        conversation.whatsapp_sent_mid_call
                    ),
                    int(
                        conversation.callback_requested
                    ),
                    _datetime_to_string(
                        conversation.started_at
                    )
                    or datetime.utcnow().isoformat(),
                ),
            )

            connection.execute(
                """
                DELETE FROM messages
                WHERE conversation_id = ?
                """,
                (conversation.conversation_id,),
            )

            for message in conversation.messages:
                connection.execute(
                    """
                    INSERT INTO messages (
                        conversation_id,
                        role,
                        text,
                        language,
                        timestamp
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        conversation.conversation_id,
                        message.role.value,
                        message.text,
                        message.language,
                        _datetime_to_string(
                            message.timestamp
                        ),
                    ),
                )

            connection.commit()

        return conversation

    def get(
        self,
        conversation_id: str,
    ) -> Optional[Conversation]:
        """Retrieve a conversation by ID."""

        with database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM conversations
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()

            if row is None:
                return None

            message_rows = connection.execute(
                """
                SELECT *
                FROM messages
                WHERE conversation_id = ?
                ORDER BY timestamp ASC, message_id ASC
                """,
                (conversation_id,),
            ).fetchall()

        return self._row_to_conversation(
            row,
            message_rows,
        )

    def get_by_lead(
        self,
        lead_id: str,
    ) -> List[Conversation]:
        """Retrieve all conversations belonging to a lead."""

        with database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM conversations
                WHERE lead_id = ?
                ORDER BY started_at DESC
                """,
                (lead_id,),
            ).fetchall()

        conversations = []

        for row in rows:
            with database.connect() as message_connection:
                message_rows = message_connection.execute(
                    """
                    SELECT *
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY timestamp ASC, message_id ASC
                    """,
                    (row["conversation_id"],),
                ).fetchall()

            conversations.append(
                self._row_to_conversation(
                    row,
                    message_rows,
                )
            )

        return conversations

    @staticmethod
    def _row_to_conversation(
        row,
        message_rows,
    ) -> Conversation:
        """Convert database rows into a Conversation model."""

        from app.core.models import (
            ConversationStatus,
            MessageRole,
        )

        messages = [
            ConversationMessage(
                role=MessageRole(
                    message_row["role"]
                ),
                text=message_row["text"],
                language=message_row["language"],
                timestamp=_string_to_datetime(
                    message_row["timestamp"]
                ),
            )
            for message_row in message_rows
        ]

        return Conversation(
            conversation_id=row["conversation_id"],
            lead_id=row["lead_id"],
            phone_number=row["phone_number"],
            status=ConversationStatus(row["status"]),
            language=row["language"],
            messages=messages,
            started_at=_string_to_datetime(
                row["started_at"]
            ),
            ended_at=_string_to_datetime(
                row["ended_at"]
            ),
            whatsapp_sent_mid_call=bool(
                row["whatsapp_sent_mid_call"]
            ),
            callback_requested=bool(
                row["callback_requested"]
            ),
        )


class CallbackRepository:
    """Persistent operations for callbacks."""

    def save(
        self,
        callback: CallbackRequest,
    ) -> CallbackRequest:
        """Save a callback request."""

        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO callbacks (
                    lead_id,
                    requested_time_text,
                    scheduled_for,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    callback.lead_id,
                    callback.requested_time_text,
                    _datetime_to_string(
                        callback.scheduled_for
                    ),
                    callback.status.value,
                    _datetime_to_string(
                        callback.created_at
                    ),
                ),
            )

            connection.commit()

        return callback

    def list_for_lead(
        self,
        lead_id: str,
    ) -> List[CallbackRequest]:
        """Retrieve callback requests for a lead."""

        with database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM callbacks
                WHERE lead_id = ?
                ORDER BY created_at DESC
                """,
                (lead_id,),
            ).fetchall()

        return [
            self._row_to_callback(row)
            for row in rows
        ]

    @staticmethod
    def _row_to_callback(row) -> CallbackRequest:
        """Convert a database row into a callback model."""

        from app.core.models import CallbackStatus

        return CallbackRequest(
            lead_id=row["lead_id"],
            requested_time_text=row[
                "requested_time_text"
            ],
            scheduled_for=_string_to_datetime(
                row["scheduled_for"]
            ),
            status=CallbackStatus(row["status"]),
            created_at=_string_to_datetime(
                row["created_at"]
            ),
        )


lead_repository = LeadRepository()
conversation_repository = ConversationRepository()
callback_repository = CallbackRepository()