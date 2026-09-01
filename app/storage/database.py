# database.py
"""
Database connection and initialization.

Uses SQLite for the initial deployment because it is free, requires
no separate database server, and is suitable for the assignment's
initial deployment architecture.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from app.core.config import settings


class Database:
    """SQLite database manager."""

    def __init__(
        self,
        database_path: Optional[str] = None,
    ) -> None:
        configured_path = database_path or settings.database_path

        self.database_path = Path(
            configured_path
        )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.initialize()

    def connect(self) -> sqlite3.Connection:
        """Create a new database connection."""

        connection = sqlite3.connect(
            str(self.database_path)
        )

        connection.row_factory = sqlite3.Row

        return connection

    def initialize(self) -> None:
        """Create all required database tables."""

        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id TEXT PRIMARY KEY,
                    phone_number TEXT NOT NULL,
                    name TEXT,
                    language TEXT,
                    budget TEXT,
                    products TEXT,
                    product_count INTEGER,
                    timeline TEXT,
                    features TEXT,
                    business_description TEXT,
                    decision_maker TEXT,
                    objections TEXT,
                    temperature TEXT,
                    intent_score REAL DEFAULT 0,
                    conversation_summary TEXT,
                    customer_quotes TEXT,
                    status TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    lead_id TEXT NOT NULL,
                    phone_number TEXT NOT NULL,
                    status TEXT NOT NULL,
                    language TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    whatsapp_sent_mid_call INTEGER DEFAULT 0,
                    callback_requested INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (lead_id)
                        REFERENCES leads(lead_id)
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    language TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(conversation_id)
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS callbacks (
                    callback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT NOT NULL,
                    requested_time_text TEXT NOT NULL,
                    scheduled_for TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (lead_id)
                        REFERENCES leads(lead_id)
                )
                """
            )

            connection.commit()


database = Database()