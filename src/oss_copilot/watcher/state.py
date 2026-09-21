"""Durable state in Postgres — the dedup + readiness cache for the watcher.

Two jobs:
  1. Cache readiness verdicts (LLM output; issue body is fixed, so never re-judge).
  2. Track which issues have been SURFACED, so a daily run never repeats itself.

Claim status is deliberately NOT cached — it changes, so the pipeline re-checks
it live every run.
"""

from __future__ import annotations

import os
import psycopg

SCHEMA = """
CREATE TABLE IF NOT EXISTS issue_state (
    repo               TEXT        NOT NULL,
    number             INTEGER     NOT NULL,
    readiness_verdict  TEXT,
    readiness_reason   TEXT,
    first_seen_at      TIMESTAMPTZ DEFAULT now(),
    last_evaluated_at  TIMESTAMPTZ DEFAULT now(),
    surfaced_at        TIMESTAMPTZ,
    PRIMARY KEY (repo, number)
);
"""


def _url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set (see .env).")
    return url


def get_conn():
    return psycopg.connect(_url())


def init_schema(conn) -> None:
    with conn.cursor() as c:
        c.execute(SCHEMA)
    conn.commit()


def get_state(conn, repo: str, number: int):
    """Return (verdict, reason, surfaced_at) or None."""
    with conn.cursor() as c:
        c.execute(
            "SELECT readiness_verdict, readiness_reason, surfaced_at "
            "FROM issue_state WHERE repo=%s AND number=%s", (repo, number))
        return c.fetchone()


def record_readiness(conn, repo: str, number: int, verdict: str, reason: str) -> None:
    with conn.cursor() as c:
        c.execute("""
            INSERT INTO issue_state (repo, number, readiness_verdict, readiness_reason)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (repo, number) DO UPDATE SET
                readiness_verdict = EXCLUDED.readiness_verdict,
                readiness_reason  = EXCLUDED.readiness_reason,
                last_evaluated_at = now()
        """, (repo, number, verdict, reason))
    conn.commit()


def mark_surfaced(conn, repo: str, number: int) -> None:
    with conn.cursor() as c:
        c.execute("UPDATE issue_state SET surfaced_at = now() "
                  "WHERE repo=%s AND number=%s", (repo, number))
    conn.commit()