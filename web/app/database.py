"""PostgreSQL access layer for ssmtp-server.

A thin wrapper around a psycopg3 connection pool. All timestamps are stored as
timezone-aware values; the UI renders them in America/Chicago to stay
consistent with the other internal apps.
"""

from __future__ import annotations

import os
import secrets
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import bcrypt
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

CENTRAL = ZoneInfo("America/Chicago")


def now_central() -> datetime:
    return datetime.now(CENTRAL)


def _dsn() -> str:
    return (
        f"host={os.environ.get('POSTGRES_HOST', 'db')} "
        f"port={os.environ.get('POSTGRES_PORT', '5432')} "
        f"dbname={os.environ.get('POSTGRES_DB', 'ssmtp')} "
        f"user={os.environ.get('POSTGRES_USER', 'ssmtp')} "
        f"password={os.environ.get('POSTGRES_PASSWORD', '')}"
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id            SERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS apps (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    smtp_username       TEXT NOT NULL UNIQUE,
    smtp_password_hash  TEXT NOT NULL,
    api_key             TEXT NOT NULL UNIQUE,
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    rate_limit_per_hour INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id          SERIAL PRIMARY KEY,
    app_id      INTEGER REFERENCES apps(id) ON DELETE SET NULL,
    queue_id    TEXT UNIQUE,
    message_id  TEXT,
    from_addr   TEXT,
    to_addr     TEXT,
    subject     TEXT,
    size_bytes  INTEGER,
    status      TEXT NOT NULL DEFAULT 'received',
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_received_at ON messages(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);

CREATE TABLE IF NOT EXISTS delivery_events (
    id            SERIAL PRIMARY KEY,
    message_id    INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    event_type    TEXT NOT NULL,
    remote_mx     TEXT,
    smtp_code     TEXT,
    smtp_response TEXT,
    attempt_no    INTEGER,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_message ON delivery_events(message_id);

CREATE TABLE IF NOT EXISTS domains (
    id              SERIAL PRIMARY KEY,
    domain          TEXT NOT NULL UNIQUE,
    dkim_selector   TEXT,
    dkim_public_key TEXT,
    dns_verified_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class PostgresManager:
    def __init__(self) -> None:
        self.pool = ConnectionPool(_dsn(), min_size=1, max_size=10, open=True)

    @contextmanager
    def cursor(self) -> Iterator[psycopg.Cursor]:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                yield cur

    # ----- schema / seed --------------------------------------------------
    def init_db(self) -> None:
        with self.pool.connection() as conn:
            conn.execute(SCHEMA)
            conn.commit()

    def ensure_admin(self, username: str, password: str) -> None:
        """Create the admin user if no admin exists yet (idempotent seed)."""
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM admin_users")
            if cur.fetchone()["n"] == 0:
                cur.execute(
                    "INSERT INTO admin_users (username, password_hash) VALUES (%s, %s)",
                    (username, hash_password(password)),
                )

    def ensure_domain(self, domain: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO domains (domain) VALUES (%s) ON CONFLICT (domain) DO NOTHING",
                (domain,),
            )

    # ----- admin auth -----------------------------------------------------
    def verify_admin(self, username: str, password: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM admin_users WHERE username = %s", (username,)
            )
            row = cur.fetchone()
        return bool(row) and check_password(password, row["password_hash"])

    # ----- apps -----------------------------------------------------------
    def list_apps(self) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.name, a.smtp_username, a.api_key, a.enabled,
                       a.rate_limit_per_hour, a.created_at,
                       COUNT(m.id)                                        AS total,
                       COUNT(m.id) FILTER (WHERE m.status = 'sent')       AS sent,
                       COUNT(m.id) FILTER (WHERE m.status = 'bounced')    AS bounced,
                       COUNT(m.id) FILTER (WHERE m.status = 'deferred')   AS deferred
                FROM apps a
                LEFT JOIN messages m ON m.app_id = a.id
                GROUP BY a.id
                ORDER BY a.created_at DESC
                """
            )
            return cur.fetchall()

    def create_app(self, name: str, smtp_username: str, password: str,
                   rate_limit_per_hour: int = 0) -> dict[str, Any]:
        api_key = "sk_" + secrets.token_urlsafe(32)
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO apps (name, smtp_username, smtp_password_hash,
                                  api_key, rate_limit_per_hour)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, smtp_username, api_key, enabled, rate_limit_per_hour
                """,
                (name, smtp_username, hash_password(password), api_key,
                 rate_limit_per_hour),
            )
            return cur.fetchone()

    def update_app(self, app_id: int, *, enabled: bool | None = None,
                   rate_limit_per_hour: int | None = None,
                   password: str | None = None) -> None:
        sets, params = [], []
        if enabled is not None:
            sets.append("enabled = %s")
            params.append(enabled)
        if rate_limit_per_hour is not None:
            sets.append("rate_limit_per_hour = %s")
            params.append(rate_limit_per_hour)
        if password:
            sets.append("smtp_password_hash = %s")
            params.append(hash_password(password))
        if not sets:
            return
        params.append(app_id)
        with self.cursor() as cur:
            cur.execute(f"UPDATE apps SET {', '.join(sets)} WHERE id = %s", params)

    def delete_app(self, app_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM apps WHERE id = %s", (app_id,))

    # ----- messages / events (written by the internal event API) ----------
    def upsert_message(self, queue_id: str, **fields: Any) -> int:
        """Insert or update a message row keyed by Haraka queue/transaction id."""
        cols = ["queue_id"] + list(fields.keys())
        vals = [queue_id] + list(fields.values())
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(
            f"{c} = COALESCE(EXCLUDED.{c}, messages.{c})" for c in fields
        )
        with self.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO messages ({', '.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (queue_id) DO UPDATE
                SET {updates}, updated_at = now()
                RETURNING id
                """,
                vals,
            )
            return cur.fetchone()["id"]

    def set_message_status(self, queue_id: str, status: str) -> int | None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE messages SET status = %s, updated_at = now() "
                "WHERE queue_id = %s RETURNING id",
                (status, queue_id),
            )
            row = cur.fetchone()
            return row["id"] if row else None

    def add_delivery_event(self, queue_id: str, event_type: str, *,
                           remote_mx: str | None = None, smtp_code: str | None = None,
                           smtp_response: str | None = None,
                           attempt_no: int | None = None) -> None:
        with self.cursor() as cur:
            cur.execute("SELECT id FROM messages WHERE queue_id = %s", (queue_id,))
            row = cur.fetchone()
            if not row:
                return
            cur.execute(
                """
                INSERT INTO delivery_events
                    (message_id, event_type, remote_mx, smtp_code, smtp_response, attempt_no)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (row["id"], event_type, remote_mx, smtp_code, smtp_response, attempt_no),
            )

    def list_messages(self, *, status: str | None = None, search: str | None = None,
                      limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        where, params = [], []
        if status and status != "all":
            where.append("m.status = %s")
            params.append(status)
        if search:
            where.append("(m.to_addr ILIKE %s OR m.from_addr ILIKE %s OR m.subject ILIKE %s)")
            params += [f"%{search}%"] * 3
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params += [limit, offset]
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT m.*, a.name AS app_name
                FROM messages m
                LEFT JOIN apps a ON a.id = m.app_id
                {clause}
                ORDER BY m.received_at DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            return cur.fetchall()

    def get_message(self, message_id: int) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT m.*, a.name AS app_name
                FROM messages m LEFT JOIN apps a ON a.id = m.app_id
                WHERE m.id = %s
                """,
                (message_id,),
            )
            msg = cur.fetchone()
            if not msg:
                return None
            cur.execute(
                "SELECT * FROM delivery_events WHERE message_id = %s ORDER BY occurred_at",
                (message_id,),
            )
            msg["events"] = cur.fetchall()
            return msg

    def dashboard_stats(self) -> dict[str, int]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                                          AS total,
                    COUNT(*) FILTER (WHERE status = 'sent')           AS sent,
                    COUNT(*) FILTER (WHERE status = 'bounced')        AS bounced,
                    COUNT(*) FILTER (WHERE status = 'deferred')       AS deferred,
                    COUNT(*) FILTER (WHERE status IN ('received','queued')) AS pending,
                    COUNT(*) FILTER (WHERE received_at > now() - interval '24 hours') AS last_24h
                FROM messages
                """
            )
            return cur.fetchone()

    # ----- domains --------------------------------------------------------
    def list_domains(self) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM domains ORDER BY domain")
            return cur.fetchall()

    def get_domain(self, domain: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM domains WHERE domain = %s", (domain,))
            return cur.fetchone()

    def set_domain_dkim(self, domain: str, selector: str, public_key: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO domains (domain, dkim_selector, dkim_public_key)
                VALUES (%s, %s, %s)
                ON CONFLICT (domain) DO UPDATE
                SET dkim_selector = EXCLUDED.dkim_selector,
                    dkim_public_key = EXCLUDED.dkim_public_key
                """,
                (domain, selector, public_key),
            )

    def mark_domain_verified(self, domain: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE domains SET dns_verified_at = now() WHERE domain = %s", (domain,)
            )

    # ----- settings -------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )


# ----- password hashing (shared format with Haraka's bcryptjs) ------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False
