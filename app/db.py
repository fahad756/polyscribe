from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import Settings, get_settings


DEFAULT_TITLE = "New chat"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(settings: Settings | None = None) -> None:
    with _connect(settings) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                kind TEXT NOT NULL DEFAULT 'text',
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_chat_created
                ON messages(chat_id, created_at);
            """
        )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if "metadata" in data:
        data["metadata"] = json.loads(data["metadata"] or "{}")
    return data


def _derive_title(content: str) -> str:
    clean = " ".join(content.replace("\n", " ").split())
    if clean.lower().startswith("uploaded "):
        clean = clean.removeprefix("Uploaded ").strip()
    if not clean:
        return DEFAULT_TITLE
    return clean[:56].rstrip() + ("..." if len(clean) > 56 else "")


def create_chat(title: str = DEFAULT_TITLE) -> dict[str, Any]:
    chat_id = uuid.uuid4().hex
    now = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (chat_id, title, now, now),
        )
    chat = get_chat(chat_id)
    if chat is None:
        raise RuntimeError("Chat creation failed")
    return chat


def list_chats(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM chats
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_chat(chat_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
    return _row_to_dict(row)


def delete_chat(chat_id: str) -> bool:
    with _connect() as connection:
        result = connection.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return result.rowcount > 0


def list_messages(chat_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, chat_id, role, kind, content, metadata, created_at
            FROM messages
            WHERE chat_id = ?
            ORDER BY created_at ASC
            """,
            (chat_id,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows if row is not None]


def add_message(
    chat_id: str,
    role: str,
    content: str,
    kind: str = "text",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message_id = uuid.uuid4().hex
    now = _now()
    metadata_json = json.dumps(metadata or {}, separators=(",", ":"))

    with _connect() as connection:
        chat = connection.execute(
            "SELECT title FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        if chat is None:
            raise ValueError("Chat not found")

        connection.execute(
            """
            INSERT INTO messages (id, chat_id, role, kind, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, chat_id, role, kind, content, metadata_json, now),
        )

        if role == "user" and chat["title"] == DEFAULT_TITLE:
            connection.execute(
                "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
                (_derive_title(content), now, chat_id),
            )
        else:
            connection.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (now, chat_id),
            )

        row = connection.execute(
            """
            SELECT id, chat_id, role, kind, content, metadata, created_at
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()

    message = _row_to_dict(row)
    if message is None:
        raise RuntimeError("Message creation failed")
    return message

