from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import Settings, get_settings


DEFAULT_TITLE = "New chat"
TITLE_MAX_LENGTH = 56

LANGUAGE_NAMES = {
    "arabic",
    "bengali",
    "chinese",
    "dutch",
    "english",
    "french",
    "german",
    "greek",
    "gujarati",
    "hindi",
    "indonesian",
    "italian",
    "japanese",
    "korean",
    "malay",
    "marathi",
    "pashto",
    "persian",
    "portuguese",
    "punjabi",
    "russian",
    "spanish",
    "tamil",
    "telugu",
    "turkish",
    "urdu",
}

FILLER_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "audio",
    "can",
    "could",
    "create",
    "direct",
    "file",
    "for",
    "from",
    "give",
    "i",
    "in",
    "into",
    "is",
    "it",
    "just",
    "make",
    "me",
    "my",
    "need",
    "of",
    "only",
    "on",
    "please",
    "summary",
    "summarise",
    "summarize",
    "tell",
    "the",
    "this",
    "to",
    "transcript",
    "transcribe",
    "translate",
    "translation",
    "want",
    "what",
    "with",
    "would",
    "you",
}


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
                owner_id TEXT NOT NULL DEFAULT 'legacy',
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

            CREATE TABLE IF NOT EXISTS demo_usage (
                usage_key TEXT PRIMARY KEY,
                prompt_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(chats)").fetchall()
        }
        if "owner_id" not in columns:
            connection.execute(
                "ALTER TABLE chats ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'legacy'"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chats_owner_updated "
            "ON chats(owner_id, updated_at)"
        )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if "metadata" in data:
        data["metadata"] = json.loads(data["metadata"] or "{}")
    return data


def _clean_title(value: str, fallback: str = DEFAULT_TITLE) -> str:
    clean = " ".join(value.replace("\n", " ").split()).strip(" .,:;-")
    if not clean:
        return fallback
    return clean[:TITLE_MAX_LENGTH].rstrip() + ("..." if len(clean) > TITLE_MAX_LENGTH else "")


def _target_language(text: str) -> str:
    tokens = [token.strip(".,:;!?()[]{}\"'").lower() for token in text.split()]
    for index, token in enumerate(tokens):
        if token in {"to", "into", "in"} and index + 1 < len(tokens):
            language = tokens[index + 1]
            if language in LANGUAGE_NAMES:
                return language.title()
    for token in tokens:
        if token in LANGUAGE_NAMES:
            return token.title()
    return ""


def _topic_from_prompt(prompt: str) -> str:
    words = [
        word.strip(".,:;!?()[]{}\"'")
        for word in prompt.split()
        if word.strip(".,:;!?()[]{}\"'")
    ]
    useful = [
        word
        for word in words
        if word.lower() not in FILLER_WORDS and len(word) > 2
    ]
    if not useful:
        return ""
    return " ".join(useful[:6]).title()


def _derive_upload_title(prompt: str) -> str:
    clean = _clean_title(prompt, fallback="")
    lower = clean.lower()
    target_language = _target_language(clean)

    if "translat" in lower:
        if any(term in lower for term in ("summary", "summarize", "summarise", "key points")):
            return f"Audio Summary in {target_language}" if target_language else "Audio Translation Summary"
        return f"Audio to {target_language} Translation" if target_language else "Audio Translation"

    if any(term in lower for term in ("summarize", "summarise", "summary", "key points", "main points")):
        return "Audio Summary"

    if any(term in lower for term in ("notes", "minutes", "action items", "takeaways")):
        return "Audio Notes"

    if any(term in lower for term in ("clean", "polish", "remove filler", "fix grammar")):
        return "Clean Audio Transcript"

    if any(term in lower for term in ("analyze", "analyse", "explain", "what is this about")):
        return "Audio Analysis"

    if any(term in lower for term in ("transcript", "transcribe", "captions", "subtitles", "what was said", "what is said")):
        return "Audio Transcript"

    topic = _topic_from_prompt(clean)
    return f"Audio: {topic}" if topic else "Audio Transcript"


def _derive_text_title(content: str) -> str:
    clean = _clean_title(content, fallback="")
    lower = clean.lower()
    target_language = _target_language(clean)

    if "translat" in lower:
        return f"{target_language} Translation" if target_language else "Translation"

    if any(term in lower for term in ("summarize", "summarise", "summary", "key points", "main points")):
        topic = _topic_from_prompt(clean)
        return f"Summary: {topic}" if topic else "Summary"

    topic = _topic_from_prompt(clean)
    return _clean_title(topic or clean)


def _derive_title(content: str, kind: str = "text", metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    if kind == "upload":
        return _derive_upload_title(str(metadata.get("prompt") or ""))
    return _derive_text_title(content)


def create_chat(owner_id: str, title: str = DEFAULT_TITLE) -> dict[str, Any]:
    chat_id = uuid.uuid4().hex
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO chats (id, owner_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, owner_id, title, now, now),
        )
    chat = get_chat(chat_id, owner_id)
    if chat is None:
        raise RuntimeError("Chat creation failed")
    return chat


def list_chats(owner_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at
            FROM chats c
            WHERE c.owner_id = ?
            AND EXISTS (
                SELECT 1
                FROM messages m
                WHERE m.chat_id = c.id
            )
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (owner_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_chat(chat_id: str, owner_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM chats
            WHERE id = ? AND owner_id = ?
            """,
            (chat_id, owner_id),
        ).fetchone()
    return _row_to_dict(row)


def delete_chat(chat_id: str, owner_id: str) -> bool:
    with _connect() as connection:
        result = connection.execute(
            "DELETE FROM chats WHERE id = ? AND owner_id = ?",
            (chat_id, owner_id),
        )
    return result.rowcount > 0


def list_messages(chat_id: str, owner_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT m.id, m.chat_id, m.role, m.kind, m.content, m.metadata, m.created_at
            FROM messages m
            INNER JOIN chats c ON c.id = m.chat_id
            WHERE m.chat_id = ? AND c.owner_id = ?
            ORDER BY m.created_at ASC
            """,
            (chat_id, owner_id),
        ).fetchall()
    return [_row_to_dict(row) for row in rows if row is not None]


def add_message(
    chat_id: str,
    owner_id: str,
    role: str,
    content: str,
    kind: str = "text",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message_id = uuid.uuid4().hex
    now = _now()
    metadata = metadata or {}
    metadata_json = json.dumps(metadata, separators=(",", ":"))

    with _connect() as connection:
        chat = connection.execute(
            "SELECT title FROM chats WHERE id = ? AND owner_id = ?",
            (chat_id, owner_id),
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
                (_derive_title(content, kind, metadata), now, chat_id),
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


def demo_usage(usage_key: str) -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT prompt_count FROM demo_usage WHERE usage_key = ?",
            (usage_key,),
        ).fetchone()
    if row is None:
        return 0
    return int(row["prompt_count"])


def consume_demo_prompt(usage_key: str, limit: int) -> dict[str, int | bool]:
    now = _now()
    limit = max(limit, 0)
    with _connect() as connection:
        row = connection.execute(
            "SELECT prompt_count FROM demo_usage WHERE usage_key = ?",
            (usage_key,),
        ).fetchone()
        current = int(row["prompt_count"]) if row is not None else 0
        if current >= limit:
            return {
                "allowed": False,
                "used": current,
                "remaining": 0,
                "limit": limit,
            }

        next_count = current + 1
        if row is None:
            connection.execute(
                """
                INSERT INTO demo_usage (usage_key, prompt_count, updated_at)
                VALUES (?, ?, ?)
                """,
                (usage_key, next_count, now),
            )
        else:
            connection.execute(
                """
                UPDATE demo_usage
                SET prompt_count = ?, updated_at = ?
                WHERE usage_key = ?
                """,
                (next_count, now, usage_key),
            )

    return {
        "allowed": True,
        "used": next_count,
        "remaining": max(limit - next_count, 0),
        "limit": limit,
    }
