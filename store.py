"""
NetWatch Evidence Store
SQLite-backed persistence for cases, flagged posts, and dashboard stats.
Falls back to in-memory if DB write fails.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.getenv("NETWATCH_DB", "netwatch.db")

# ─────────────────────────────────────────
# SCHEMA INIT
# ─────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT NOT NULL,
            channel_title    TEXT,
            platform         TEXT DEFAULT 'Reddit',
            subscriber_count INTEGER,
            description      TEXT,
            total_posts      INTEGER DEFAULT 0,
            flagged_count    INTEGER DEFAULT 0,
            risk_score       REAL DEFAULT 0.0,
            risk_level       TEXT DEFAULT 'MINIMAL',
            bot_score        INTEGER DEFAULT 0,
            substances       TEXT DEFAULT '[]',   -- JSON array
            flagged_posts    TEXT DEFAULT '[]',   -- JSON array
            is_storefront_bot INTEGER DEFAULT 0,
            created_at       TEXT
        );
    """)
    conn.commit()
    conn.close()


# Run on module import
_init_db()


# ─────────────────────────────────────────
# WRITE OPERATIONS
# ─────────────────────────────────────────

def save_case(case: dict) -> int:
    """
    Upserts a case by channel_username.
    If the subreddit was scanned before, updates the existing record.
    Returns the case ID.
    """
    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM cases WHERE channel_username = ?",
            (case["channel_username"],)
        ).fetchone()

        now = datetime.now(timezone.utc).isoformat()

        if existing:
            case_id = existing["id"]
            conn.execute("""
                UPDATE cases SET
                    channel_title    = ?,
                    platform         = ?,
                    subscriber_count = ?,
                    description      = ?,
                    total_posts      = ?,
                    flagged_count    = ?,
                    risk_score       = ?,
                    risk_level       = ?,
                    bot_score        = ?,
                    substances       = ?,
                    flagged_posts    = ?,
                    is_storefront_bot = ?,
                    created_at       = ?
                WHERE id = ?
            """, (
                case.get("channel_title"),
                case.get("platform", "Reddit"),
                case.get("subscriber_count"),
                case.get("description", ""),
                case.get("total_posts", 0),
                case.get("flagged_count", 0),
                case.get("risk_score", 0.0),
                case.get("risk_level", "MINIMAL"),
                case.get("bot_score", 0),
                json.dumps(case.get("substances", [])),
                json.dumps(case.get("flagged_posts", [])),
                int(case.get("is_storefront_bot", False)),
                now,
                case_id,
            ))
        else:
            cursor = conn.execute("""
                INSERT INTO cases (
                    channel_username, channel_title, platform, subscriber_count,
                    description, total_posts, flagged_count, risk_score, risk_level,
                    bot_score, substances, flagged_posts, is_storefront_bot, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                case["channel_username"],
                case.get("channel_title"),
                case.get("platform", "Reddit"),
                case.get("subscriber_count"),
                case.get("description", ""),
                case.get("total_posts", 0),
                case.get("flagged_count", 0),
                case.get("risk_score", 0.0),
                case.get("risk_level", "MINIMAL"),
                case.get("bot_score", 0),
                json.dumps(case.get("substances", [])),
                json.dumps(case.get("flagged_posts", [])),
                int(case.get("is_storefront_bot", False)),
                now,
            ))
            case_id = cursor.lastrowid

        conn.commit()
        return case_id

    finally:
        conn.close()


# ─────────────────────────────────────────
# READ OPERATIONS
# ─────────────────────────────────────────

def get_case(case_id: int) -> Optional[dict]:
    """Fetch a single case by ID. Returns None if not found."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        return _deserialize(dict(row)) if row else None
    finally:
        conn.close()


def get_all_cases() -> list:
    """Returns all cases ordered by risk score descending."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM cases ORDER BY risk_score DESC"
        ).fetchall()
        return [_deserialize(dict(r)) for r in rows]
    finally:
        conn.close()


def get_stats() -> dict:
    """
    Powers the 4 stat cards on the Command Center dashboard.
    """
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*)                        AS channels_tracked,
                COALESCE(SUM(flagged_count), 0) AS flagged_posts,
                COALESCE(SUM(flagged_count), 0) AS evidence_sealed,
                COUNT(CASE WHEN risk_score >= 7 THEN 1 END) AS suspect_dossiers
            FROM cases
        """).fetchone()

        return {
            "channels_tracked": row["channels_tracked"] or 0,
            "flagged_posts":    row["flagged_posts"] or 0,
            "evidence_sealed":  row["evidence_sealed"] or 0,
            "suspect_dossiers": row["suspect_dossiers"] or 0,
        }
    finally:
        conn.close()


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def _deserialize(row: dict) -> dict:
    """Parse JSON columns back to Python objects."""
    for field in ("substances", "flagged_posts"):
        if isinstance(row.get(field), str):
            try:
                row[field] = json.loads(row[field])
            except (json.JSONDecodeError, TypeError):
                row[field] = []
    row["is_storefront_bot"] = bool(row.get("is_storefront_bot", 0))
    return row
