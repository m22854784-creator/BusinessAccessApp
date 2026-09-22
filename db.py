"""Database access layer: connections, schema and a small transaction helper.

Two engines are supported, chosen automatically by config.DB_ENGINE
(set from the DATABASE_URL environment variable in config.py):

- sqlite   - a single file on disk. Simple, but on most free hosting the
             disk is wiped on every restart/redeploy, so data does not
             survive. Fine for running the app on your own PC.
- postgres - a real database server (e.g. Render's free PostgreSQL).
             Data survives restarts and redeploys. Requires DATABASE_URL.

Every route file just calls get_db().execute(sql, params) with SQLite-style
"?" placeholders; the Postgres wrapper below translates that transparently,
so nothing outside this file needs to know which engine is active.
"""
import os
import re
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone

from flask import g, current_app

# ---- schema: SQLite -------------------------------------------------------
SQLITE_SCHEMA = """
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

# ---- schema: PostgreSQL -----------------------------------------------------
# Same shape as SQLITE_SCHEMA, in Postgres syntax: SERIAL instead of
# AUTOINCREMENT, and the append-only audit trail is a function + trigger
# instead of SQLite's inline trigger body. Username case-insensitivity uses
# a functional index (see find_user_by_username below) instead of SQLite's
# COLLATE NOCASE, which Postgres does not have.
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                   SERIAL PRIMARY KEY,
    username             TEXT NOT NULL UNIQUE,
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_ci ON users (LOWER(username));

CREATE TABLE IF NOT EXISTS permissions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module  TEXT    NOT NULL,
    level   TEXT    NOT NULL CHECK (level IN ('none','view','edit')),
    PRIMARY KEY (user_id, module)
);

CREATE TABLE IF NOT EXISTS sessions (
    id           SERIAL PRIMARY KEY,
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
    id          SERIAL PRIMARY KEY,
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
    id         SERIAL PRIMARY KEY,
    ts         TEXT NOT NULL,
    user_id    INTEGER,
    username   TEXT,
    category   TEXT NOT NULL,
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

-- The audit trail is append-only: Postgres itself refuses edits and deletes.
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_no_update ON audit_log;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
DROP TRIGGER IF EXISTS audit_no_delete ON audit_log;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

CREATE TABLE IF NOT EXISTS notifications (
    id       SERIAL PRIMARY KEY,
    ts       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    severity TEXT NOT NULL,
    title    TEXT NOT NULL,
    message  TEXT,
    is_read  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notif_kind ON notifications(kind, is_read);
"""


# ---- time helpers (all timestamps are stored as UTC ISO-8601 text) --------
def utcnow():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---- SQLite connection ------------------------------------------------------
def connect_sqlite(path):
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# ---- PostgreSQL connection ---------------------------------------------------
# A thin wrapper so every route file can keep using db.execute(sql, params)
# with "?" placeholders, cur.lastrowid, and row["col"] / row[0] access -
# exactly like the SQLite path - nothing outside this file needs an
# if/else for which engine is active.
_INSERT_RE = re.compile(r"^\s*INSERT\s", re.IGNORECASE)


class Row(Mapping):
    """Mimics sqlite3.Row: supports row["col"], row[0], dict(row), row.get(...)."""
    __slots__ = ("_idx", "_data")

    def __init__(self, idx, data):
        self._idx = idx    # {column_name: position}, shared across all rows of one query
        self._data = data  # tuple of values for this row

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[key]
        return self._data[self._idx[key]]

    def __iter__(self):
        return iter(self._idx)

    def __len__(self):
        return len(self._data)


class PGCursor:
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None
        self._idx = {d[0]: i for i, d in enumerate(cur.description)} if cur.description else None

    def fetchone(self):
        row = self._cur.fetchone()
        return None if row is None else Row(self._idx, row)

    def fetchall(self):
        return [Row(self._idx, r) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount

    def __iter__(self):
        for r in self._cur:
            yield Row(self._idx, r)


class PGConnection:
    """Mimics the small slice of sqlite3.Connection this app relies on."""

    def __init__(self, raw):
        self._raw = raw
        self._in_txn = False

    @staticmethod
    def _translate(sql):
        return sql.replace("?", "%s")

    def execute(self, sql, params=()):
        upper = sql.strip().upper()
        if upper in ("BEGIN", "BEGIN IMMEDIATE"):
            self._in_txn = True
            cur = self._raw.cursor()
            cur.execute("BEGIN")
            return PGCursor(cur)
        if upper in ("COMMIT", "ROLLBACK"):
            self._in_txn = False
            cur = self._raw.cursor()
            cur.execute(upper)
            return PGCursor(cur)

        cur = self._raw.cursor()
        pg_sql = self._translate(sql)
        returning = bool(_INSERT_RE.match(pg_sql)) and "RETURNING" not in pg_sql.upper()
        if returning:
            pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"
        cur.execute(pg_sql, params)
        wrapped = PGCursor(cur)
        if returning:
            row = wrapped.fetchone()
            wrapped.lastrowid = row["id"] if row else None
        return wrapped

    def executescript(self, script):
        cur = self._raw.cursor()
        cur.execute(script)
        self._raw.commit()
        cur.close()

    @property
    def in_transaction(self):
        return self._in_txn

    def close(self):
        self._raw.close()


def connect_postgres(url):
    import psycopg2
    dsn = url
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]
    raw = psycopg2.connect(dsn, sslmode="require")
    raw.autocommit = True   # matches the SQLite path: transactions are opened explicitly
    return PGConnection(raw)


# ---- engine-agnostic helpers used by route files ----------------------------
def find_user_by_username(db, username):
    """Case-insensitive username lookup that works on both engines."""
    return db.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()


def username_taken(db, username):
    return db.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone() is not None


# ---- engine dispatch ---------------------------------------------------------
def get_db():
    if "db" not in g:
        cfg = current_app.config
        if cfg.get("DB_ENGINE") == "postgres":
            g.db = connect_postgres(cfg["DATABASE_URL"])
        else:
            g.db = connect_sqlite(cfg["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction(db=None):
    """BEGIN ... COMMIT. Joins an outer transaction if one is already open."""
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
    if app.config.get("DB_ENGINE") == "postgres":
        conn = connect_postgres(app.config["DATABASE_URL"])
        conn.executescript(PG_SCHEMA)
        conn.close()
    else:
        os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
        conn = connect_sqlite(app.config["DATABASE"])
        conn.executescript(SQLITE_SCHEMA)
        conn.close()
