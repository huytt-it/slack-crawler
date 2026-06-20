"""Postgres storage backend with idempotent upserts."""

from __future__ import annotations

import json
import logging
from typing import Any

from slack_sync.storage import StorageBackend

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS slack_messages (
    channel_id   TEXT NOT NULL,
    ts           TEXT NOT NULL,
    channel_name TEXT,
    user_id      TEXT,
    datetime_utc TIMESTAMPTZ,
    thread_ts    TEXT,
    text         TEXT,
    type         TEXT,
    subtype      TEXT,
    reactions    JSONB,
    reply_count  INTEGER DEFAULT 0,
    raw          JSONB,
    PRIMARY KEY (channel_id, ts)
);

CREATE TABLE IF NOT EXISTS slack_users (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT,
    real_name    TEXT,
    email        TEXT
);

CREATE TABLE IF NOT EXISTS slack_watermarks (
    channel_id TEXT PRIMARY KEY,
    watermark  TEXT NOT NULL
);
"""

UPSERT_MESSAGE = """
INSERT INTO slack_messages (channel_id, ts, channel_name, user_id, datetime_utc,
                            thread_ts, text, type, subtype, reactions, reply_count, raw)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (channel_id, ts) DO UPDATE SET
    channel_name = EXCLUDED.channel_name,
    user_id      = EXCLUDED.user_id,
    datetime_utc = EXCLUDED.datetime_utc,
    thread_ts    = EXCLUDED.thread_ts,
    text         = EXCLUDED.text,
    type         = EXCLUDED.type,
    subtype      = EXCLUDED.subtype,
    reactions    = EXCLUDED.reactions,
    reply_count  = EXCLUDED.reply_count,
    raw          = EXCLUDED.raw;
"""

UPSERT_USER = """
INSERT INTO slack_users (user_id, display_name, real_name, email)
VALUES (%s, %s, %s, %s)
ON CONFLICT (user_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    real_name    = EXCLUDED.real_name,
    email        = EXCLUDED.email;
"""


class PostgresBackend(StorageBackend):
    def __init__(self, connection_string: str) -> None:
        try:
            import psycopg2
        except ImportError as exc:
            raise ImportError("Install psycopg2-binary for Postgres support: pip install psycopg2-binary") from exc

        self._conn = psycopg2.connect(connection_string)
        self._conn.autocommit = False
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(DDL)
        self._conn.commit()
        logger.info("Postgres schema ensured.")

    def store_messages(self, channel_id: str, channel_name: str, messages: list[dict[str, Any]]) -> int:
        if not messages:
            return 0

        with self._conn.cursor() as cur:
            for msg in messages:
                cur.execute(UPSERT_MESSAGE, (
                    msg["channel_id"],
                    msg["ts"],
                    msg["channel_name"],
                    msg["user_id"],
                    msg["datetime_utc"],
                    msg.get("thread_ts"),
                    msg["text"],
                    msg["type"],
                    msg.get("subtype"),
                    json.dumps(msg.get("reactions"), default=str) if msg.get("reactions") else None,
                    msg.get("reply_count", 0),
                    json.dumps(msg["raw"], default=str),
                ))
        self._conn.commit()
        logger.info("Upserted %d messages for channel %s into Postgres.", len(messages), channel_name)
        return len(messages)

    def store_users(self, users: dict[str, dict[str, Any]]) -> None:
        with self._conn.cursor() as cur:
            for uid, info in users.items():
                cur.execute(UPSERT_USER, (
                    uid,
                    info.get("display_name", ""),
                    info.get("real_name", ""),
                    info.get("email"),
                ))
        self._conn.commit()
        logger.info("Upserted %d users into Postgres.", len(users))

    def close(self) -> None:
        self._conn.close()
