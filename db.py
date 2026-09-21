"""SQLite access layer: connections, schema and a small transaction helper."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from flask import g, current_app

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name            TEXT NOT NULL,
    email                TEXT,
    department           TEXT,
    password_hash        TEXT NOT NULL,
    role                 TEXT NOT NULL CHECK (role IN ('admin','user')),
    is_active            INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    password_changed_at  TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    last_login           TEXT,
    login_count          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS permissions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module  TEXT    NOT NULL,
    level   TEXT    NOT NULL CHECK (level IN ('none','view','edit')),
    PRIMARY KEY (user_id, module)
);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sid          TEXT NOT NULL UNIQUE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    ip           TEXT,
    user_agent   TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    ended_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, active);

CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    module      TEXT NOT NULL,
    part_no     TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'Planned',
    notes       TEXT,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_by  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_module ON records(module);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    user_id    INTEGER,
    username   TEXT,
    category   TEXT NOT NULL,          -- auth | record | user | security | export
    action     TEXT NOT NULL,
    target     TEXT,
    details    TEXT,
    ip         TEXT,
    success    INTEGER NOT NULL DEFAULT 1,
    prev_hash  TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

-- The audit trail is append-only: SQLite itself refuses edits and deletes.
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TABLE IF NOT EXISTS notifications (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    kind     TEXT NOT NULL,            -- failed_login | user_activity
    severity TEXT NOT NULL,            -- info | warning | danger
    title    TEXT NOT NULL,
    message  TEXT,
    is_read  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notif_kind ON notifications(kind, is_read);
"""


# ---- time helpers (all timestamps are stored as UTC ISO-8601) --------------
def utcnow():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---- connections ------------------------------------------------------------
def connect(path):
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction(db=None):
    """BEGIN IMMEDIATE ... COMMIT. Joins an outer transaction if one is open."""
    db = db or get_db()
    if db.in_transaction:
        yield db
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def init_db(app):
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    conn = connect(app.config["DATABASE"])
    conn.executescript(SCHEMA)
    conn.close()
