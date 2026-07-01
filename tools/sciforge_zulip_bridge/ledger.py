import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    project_id: str
    kind: str
    actor_kind: str
    payload: dict[str, Any]
    task_id: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class DeliveryRecord:
    delivery_id: str
    idempotency_key: str
    status: str
    target: str
    ledger_event_id: str | None = None
    zulip_message_id: int | None = None
    error: str | None = None
    next_retry_at: str | None = None


@dataclass(frozen=True)
class ThreadLink:
    link_key: str
    project_id: str
    runtime_id: str
    runtime_thread_id: str
    zulip_stream_id: int
    zulip_topic_name: str
    zulip_root_message_id: int | None = None


@dataclass(frozen=True)
class CardLink:
    card_id: str
    card_type: str
    project_id: str
    runtime_thread_id: str | None
    runtime_turn_id: str | None
    runtime_request_id: str | None
    zulip_message_id: int
    required_role: str | None = None


class ResearchLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        self._connection.close()

    def initialize(self) -> None:
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS ledger_events (
                event_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                task_id TEXT,
                kind TEXT NOT NULL,
                actor_kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                idempotency_key TEXT PRIMARY KEY,
                ledger_event_id TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (ledger_event_id) REFERENCES ledger_events(event_id)
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                delivery_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL,
                ledger_event_id TEXT,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                zulip_message_id INTEGER,
                error TEXT,
                next_retry_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                FOREIGN KEY (ledger_event_id) REFERENCES ledger_events(event_id)
            );
            CREATE TABLE IF NOT EXISTS runtime_thread_links (
                link_key TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                runtime_id TEXT NOT NULL,
                runtime_thread_id TEXT NOT NULL,
                zulip_stream_id INTEGER NOT NULL,
                zulip_topic_name TEXT NOT NULL,
                zulip_root_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );
            CREATE TABLE IF NOT EXISTS card_links (
                card_id TEXT PRIMARY KEY,
                card_type TEXT NOT NULL,
                project_id TEXT NOT NULL,
                runtime_thread_id TEXT,
                runtime_turn_id TEXT,
                runtime_request_id TEXT,
                zulip_message_id INTEGER NOT NULL UNIQUE,
                required_role TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );
            """,
        )
        self._connection.commit()

    def append_event(self, event: LedgerEvent) -> None:
        self._connection.execute(
            """
            INSERT INTO ledger_events (
                event_id, project_id, task_id, kind, actor_kind, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))
            """,
            (
                event.event_id,
                event.project_id,
                event.task_id,
                event.kind,
                event.actor_kind,
                _canonical_json(event.payload),
                event.created_at,
            ),
        )
        self._connection.commit()

    def append_event_once(self, idempotency_key: str, event: LedgerEvent) -> bool:
        with self._connection:
            inserted = self._connection.execute(
                """
                INSERT OR IGNORE INTO idempotency_keys (idempotency_key, ledger_event_id)
                VALUES (?, ?)
                """,
                (idempotency_key, event.event_id),
            ).rowcount
            if inserted == 0:
                return False
            self._connection.execute(
                """
                INSERT INTO ledger_events (
                    event_id, project_id, task_id, kind, actor_kind, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))
                """,
                (
                    event.event_id,
                    event.project_id,
                    event.task_id,
                    event.kind,
                    event.actor_kind,
                    _canonical_json(event.payload),
                    event.created_at,
                ),
            )
        return True

    def check_idempotency(self, idempotency_key: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM idempotency_keys WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return row is not None

    def record_idempotency(self, idempotency_key: str, ledger_event_id: str | None = None) -> bool:
        with self._connection:
            inserted = self._connection.execute(
                """
                INSERT OR IGNORE INTO idempotency_keys (idempotency_key, ledger_event_id)
                VALUES (?, ?)
                """,
                (idempotency_key, ledger_event_id),
            ).rowcount
        return inserted == 1

    def list_events(
        self,
        *,
        project_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if project_id is not None and kind is not None:
            rows = self._connection.execute(
                """
                SELECT event_id, project_id, task_id, kind, actor_kind, payload_json, created_at
                FROM ledger_events
                WHERE project_id = ? AND kind = ?
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (project_id, kind, limit),
            ).fetchall()
            return [_event_row_to_dict(row) for row in rows]
        if project_id is not None:
            rows = self._connection.execute(
                """
                SELECT event_id, project_id, task_id, kind, actor_kind, payload_json, created_at
                FROM ledger_events
                WHERE project_id = ?
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
            return [_event_row_to_dict(row) for row in rows]
        if kind is not None:
            rows = self._connection.execute(
                """
                SELECT event_id, project_id, task_id, kind, actor_kind, payload_json, created_at
                FROM ledger_events
                WHERE kind = ?
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (kind, limit),
            ).fetchall()
            return [_event_row_to_dict(row) for row in rows]
        rows = self._connection.execute(
            """
            SELECT event_id, project_id, task_id, kind, actor_kind, payload_json, created_at
            FROM ledger_events
            ORDER BY created_at ASC, event_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_event_row_to_dict(row) for row in rows]

    def mark_delivery(self, record: DeliveryRecord) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO deliveries (
                    delivery_id, idempotency_key, ledger_event_id, target, status,
                    zulip_message_id, error, next_retry_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(delivery_id) DO UPDATE SET
                    idempotency_key = excluded.idempotency_key,
                    ledger_event_id = excluded.ledger_event_id,
                    target = excluded.target,
                    status = excluded.status,
                    zulip_message_id = excluded.zulip_message_id,
                    error = excluded.error,
                    next_retry_at = excluded.next_retry_at,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    record.delivery_id,
                    record.idempotency_key,
                    record.ledger_event_id,
                    record.target,
                    record.status,
                    record.zulip_message_id,
                    record.error,
                    record.next_retry_at,
                ),
            )

    def list_deliveries(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT delivery_id, idempotency_key, ledger_event_id, target, status,
                   zulip_message_id, error, next_retry_at, updated_at
            FROM deliveries
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_recent_failures(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT delivery_id, idempotency_key, ledger_event_id, target, status,
                   zulip_message_id, error, next_retry_at, updated_at
            FROM deliveries
            WHERE status = 'delivery_failed'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def health_summary(self) -> dict[str, int]:
        total_events = self._connection.execute("SELECT COUNT(*) FROM ledger_events").fetchone()[0]
        pending = self._connection.execute(
            "SELECT COUNT(*) FROM deliveries WHERE status = 'pending'",
        ).fetchone()[0]
        failed = self._connection.execute(
            "SELECT COUNT(*) FROM deliveries WHERE status = 'delivery_failed'",
        ).fetchone()[0]
        delivered = self._connection.execute(
            "SELECT COUNT(*) FROM deliveries WHERE status = 'delivered'",
        ).fetchone()[0]
        return {
            "ledger_events": int(total_events),
            "pending_deliveries": int(pending),
            "failed_deliveries": int(failed),
            "delivered": int(delivered),
        }

    def record_thread_link(self, link: ThreadLink) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO runtime_thread_links (
                    link_key, project_id, runtime_id, runtime_thread_id, zulip_stream_id,
                    zulip_topic_name, zulip_root_message_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(link_key) DO UPDATE SET
                    runtime_id = excluded.runtime_id,
                    runtime_thread_id = excluded.runtime_thread_id,
                    zulip_stream_id = excluded.zulip_stream_id,
                    zulip_topic_name = excluded.zulip_topic_name,
                    zulip_root_message_id = excluded.zulip_root_message_id
                """,
                (
                    link.link_key,
                    link.project_id,
                    link.runtime_id,
                    link.runtime_thread_id,
                    link.zulip_stream_id,
                    link.zulip_topic_name,
                    link.zulip_root_message_id,
                ),
            )

    def get_thread_link(self, link_key: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT link_key, project_id, runtime_id, runtime_thread_id, zulip_stream_id,
                   zulip_topic_name, zulip_root_message_id, created_at
            FROM runtime_thread_links
            WHERE link_key = ?
            """,
            (link_key,),
        ).fetchone()
        return dict(row) if row is not None else None

    def record_card_link(self, link: CardLink) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO card_links (
                    card_id, card_type, project_id, runtime_thread_id, runtime_turn_id,
                    runtime_request_id, zulip_message_id, required_role
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    runtime_thread_id = excluded.runtime_thread_id,
                    runtime_turn_id = excluded.runtime_turn_id,
                    runtime_request_id = excluded.runtime_request_id,
                    zulip_message_id = excluded.zulip_message_id,
                    required_role = excluded.required_role
                """,
                (
                    link.card_id,
                    link.card_type,
                    link.project_id,
                    link.runtime_thread_id,
                    link.runtime_turn_id,
                    link.runtime_request_id,
                    link.zulip_message_id,
                    link.required_role,
                ),
            )

    def get_card_link_by_message_id(self, zulip_message_id: int) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT card_id, card_type, project_id, runtime_thread_id, runtime_turn_id,
                   runtime_request_id, zulip_message_id, required_role, created_at
            FROM card_links
            WHERE zulip_message_id = ?
            """,
            (zulip_message_id,),
        ).fetchone()
        return dict(row) if row is not None else None


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "project_id": row["project_id"],
        "task_id": row["task_id"],
        "kind": row["kind"],
        "actor_kind": row["actor_kind"],
        "payload": json.loads(row["payload_json"]),
        "created_at": row["created_at"],
    }
