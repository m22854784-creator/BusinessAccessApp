"""Tamper-evident audit trail + notification helper.

Each audit row stores the SHA-256 of (previous row hash + its own fields), so
any edit or deletion breaks the chain and is detected by verify_chain().
SQLite triggers (see db.py) additionally refuse UPDATE/DELETE on the table.
"""
import hashlib
import threading

from flask import g, has_request_context, request

from db import get_db, iso, transaction
from realtime import broker

_chain_lock = threading.Lock()

# Actions that raise a notification for administrators.
#   action -> (kind, severity, title)
NOTIFY_ON = {
    "LOGIN": ("user_activity", "info", "User signed in"),
    "LOGIN_FAILED": ("failed_login", "warning", "Failed login attempt"),
    "ACCOUNT_LOCKED": ("failed_login", "danger", "Account locked"),
    "LOGIN_BLOCKED": ("failed_login", "warning", "Login blocked (account locked)"),
    "USER_CREATED": ("user_activity", "info", "User created"),
    "USER_DELETED": ("user_activity", "warning", "User deleted"),
    "PERMISSIONS_CHANGED": ("user_activity", "info", "Permissions changed"),
    "PASSWORD_RESET": ("user_activity", "info", "Password reset by admin"),
    "RECORD_CREATED": ("user_activity", "info", "Record created"),
    "RECORD_UPDATED": ("user_activity", "info", "Record updated"),
    "RECORD_DELETED": ("user_activity", "warning", "Record deleted"),
    "SESSION_TERMINATED": ("user_activity", "info", "Session terminated"),
}


def _hash(prev, ts, user_id, username, category, action, target, details, ip, success):
    fields = (prev, ts, user_id, username, category, action, target, details, ip, int(success))
    payload = "|".join("" if v is None else str(v) for v in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def client_ip():
    return (request.remote_addr or "") if has_request_context() else "system"


def log(category, action, *, target=None, details=None, success=True,
        user=None, username=None, ip=None, notify=True):
    """Append one audit entry, push it to admins live, and raise a notification."""
    db = get_db()
    if user is None and has_request_context():
        user = g.get("user")
    user_id = user["id"] if user else None
    username = (username or (user["username"] if user else None))
    ip = ip if ip is not None else client_ip()
    ts = iso()

    with _chain_lock, transaction(db):
        last = db.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["entry_hash"] if last else "GENESIS"
        digest = _hash(prev, ts, user_id, username, category, action, target, details, ip, success)
        cur = db.execute(
            "INSERT INTO audit_log (ts,user_id,username,category,action,target,details,ip,success,prev_hash,entry_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts, user_id, username, category, action, target, details, ip, int(success), prev, digest),
        )
        entry_id = cur.lastrowid

    entry = {
        "id": entry_id, "ts": ts, "user_id": user_id, "username": username,
        "category": category, "action": action, "target": target,
        "details": details, "ip": ip, "success": int(success),
    }
    broker.publish("audit", entry, admins=True)

    if notify and action in NOTIFY_ON:
        kind, severity, title = NOTIFY_ON[action]
        who = username or "unknown"
        message = f"{who}: {details}" if details else who
        if target and action.startswith(("USER_", "RECORD_", "PERMISSIONS")):
            message = f"{who} - {target}" + (f" ({details})" if details else "")
        add_notification(kind, severity, title, message)
    return entry


def add_notification(kind, severity, title, message=None):
    db = get_db()
    ts = iso()
    cur = db.execute(
        "INSERT INTO notifications (ts,kind,severity,title,message) VALUES (?,?,?,?,?)",
        (ts, kind, severity, title, message),
    )
    note = {"id": cur.lastrowid, "ts": ts, "kind": kind, "severity": severity,
            "title": title, "message": message, "is_read": 0}
    broker.publish("notification", note, admins=True)
    return note


def verify_chain(db=None):
    """Recompute every hash. Returns {ok, checked, broken_at?}."""
    db = db or get_db()
    prev, checked = "GENESIS", 0
    for r in db.execute("SELECT * FROM audit_log ORDER BY id"):
        expected = _hash(r["prev_hash"], r["ts"], r["user_id"], r["username"], r["category"],
                         r["action"], r["target"], r["details"], r["ip"], r["success"])
        if r["prev_hash"] != prev or expected != r["entry_hash"]:
            return {"ok": False, "checked": checked, "broken_at": r["id"]}
        prev, checked = r["entry_hash"], checked + 1
    return {"ok": True, "checked": checked}
