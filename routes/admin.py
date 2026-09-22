"""Administrator API: dashboard, users, permissions, audit, notifications, sessions, reports."""
import re
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify, request

import audit
import reports
import security
import db as db_module
from db import get_db, iso, parse_iso, transaction, utcnow
from realtime import broker
from routes.modules import send_report

bp = Blueprint("admin", __name__, url_prefix="/api/admin")
admin_only = security.login_required(admin=True)

LEVEL_LABEL = {"none": "No Access", "view": "View", "edit": "Edit"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _module_names():
    return {m["key"]: m["name"] for m in current_app.config["MODULES"]}


def _err(message, status=400, **extra):
    return jsonify(error=message, **extra), status


# =============================== dashboard ==================================
def _local_day_start(days_ago=0):
    tz = reports.local_tz()
    local = (utcnow().astimezone(tz) - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


_chain_cache = {}      # database path -> (timestamp, result); re-verified at most every 30 s


def _chain_status(db, force=False):
    key = current_app.config["DATABASE"]
    stamp, value = _chain_cache.get(key, (0.0, None))
    if force or value is None or time.time() - stamp > 30:
        value = audit.verify_chain(db)
        _chain_cache[key] = (time.time(), value)
    return value


def security_health(db):
    cfg, now = current_app.config, utcnow()
    checks = []

    def add(key, label, status, detail, weight):
        checks.append({"key": key, "label": label, "status": status, "detail": detail, "weight": weight})

    n = db.execute("SELECT COUNT(*) c FROM users WHERE role='admin' AND must_change_password=1").fetchone()["c"]
    add("admin_password", "Administrator passwords", "fail" if n else "ok",
        f"{n} administrator(s) still on an initial password" if n else "All administrators set their own password", 25)

    n = db.execute("SELECT COUNT(*) c FROM users WHERE locked_until > ?", (iso(now),)).fetchone()["c"]
    add("lockouts", "Locked accounts", "warn" if n else "ok",
        f"{n} account(s) currently locked" if n else "No accounts are locked", 10)

    since = iso(now - timedelta(hours=24))
    n = db.execute("SELECT COUNT(*) c FROM audit_log WHERE action='LOGIN_FAILED' AND ts >= ?", (since,)).fetchone()["c"]
    add("failed_logins", "Failed logins (24 h)", "ok" if n < 5 else ("warn" if n < 20 else "fail"),
        f"{n} failed login attempt(s) in the last 24 hours", 20)

    idle = cfg["SESSION_IDLE_TIMEOUT"]
    add("timeout", "Session timeout", "ok" if idle <= 900 else ("warn" if idle <= 1800 else "fail"),
        f"Users are signed out after {idle // 60} minute(s) of inactivity", 15)

    cutoff = iso(now - timedelta(days=cfg["PASSWORD_MAX_AGE_DAYS"]))
    n = db.execute("SELECT COUNT(*) c FROM users WHERE is_active=1 AND password_changed_at < ?", (cutoff,)).fetchone()["c"]
    add("password_age", "Password age", "warn" if n else "ok",
        f"{n} password(s) older than {cfg['PASSWORD_MAX_AGE_DAYS']} days" if n
        else f"No password older than {cfg['PASSWORD_MAX_AGE_DAYS']} days", 15)

    chain = _chain_status(db)
    add("audit_chain", "Audit trail integrity", "ok" if chain["ok"] else "fail",
        f"{chain['checked']} entries verified" if chain["ok"] else f"Tampering detected at entry #{chain['broken_at']}", 15)

    score = round(sum(c["weight"] * {"ok": 1, "warn": 0.5, "fail": 0}[c["status"]] for c in checks))
    label = "Excellent" if score >= 90 else "Good" if score >= 75 else "Needs attention" if score >= 50 else "At risk"
    return {"score": score, "label": label, "checks": checks}


@bp.get("/stats")
@admin_only
def stats():
    db, now = get_db(), utcnow()
    security.reap_expired_sessions()
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    today = iso(_local_day_start())
    since24 = iso(now - timedelta(hours=24))

    trend = []
    first = _local_day_start(6)
    buckets = {}
    for r in db.execute("SELECT ts, action FROM audit_log WHERE action IN ('LOGIN','LOGIN_FAILED') AND ts >= ?",
                        (iso(first),)):
        day = parse_iso(r["ts"]).astimezone(reports.local_tz()).date()
        b = buckets.setdefault(day, {"logins": 0, "failed": 0})
        b["logins" if r["action"] == "LOGIN" else "failed"] += 1
    for i in range(6, -1, -1):
        d = (utcnow().astimezone(reports.local_tz()) - timedelta(days=i)).date()
        b = buckets.get(d, {"logins": 0, "failed": 0})
        trend.append({"date": d.isoformat(), "label": d.strftime("%a"), **b})

    return jsonify(
        total_users=one("SELECT COUNT(*) FROM users"),
        active_users=one("SELECT COUNT(*) FROM users WHERE is_active=1"),
        admins=one("SELECT COUNT(*) FROM users WHERE role='admin'"),
        login_count=one("SELECT COUNT(*) FROM audit_log WHERE action='LOGIN'"),
        logins_today=one("SELECT COUNT(*) FROM audit_log WHERE action='LOGIN' AND ts >= ?", today),
        failed_today=one("SELECT COUNT(*) FROM audit_log WHERE action='LOGIN_FAILED' AND ts >= ?", today),
        failed_24h=one("SELECT COUNT(*) FROM audit_log WHERE action='LOGIN_FAILED' AND ts >= ?", since24),
        online_now=one("SELECT COUNT(DISTINCT user_id) FROM sessions WHERE active=1"),
        locked=one("SELECT COUNT(*) FROM users WHERE locked_until > ?", iso(now)),
        live_connections=broker.connected(),
        trend=trend,
        health=security_health(db),
    )


FEED_FILTERS = {
    "all": ("", ()),
    "logins": (" WHERE category='auth'", ()),
    "users": (" WHERE category='user'", ()),
}


@bp.get("/activity")
@admin_only
def activity():
    sql_where, args = FEED_FILTERS.get(request.args.get("type", "all"), FEED_FILTERS["all"])
    limit = min(int(request.args.get("limit", 25) or 25), 100)
    rows = get_db().execute(f"SELECT * FROM audit_log{sql_where} ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    return jsonify(items=[dict(r) for r in rows])


# ============================= notifications ===============================
@bp.get("/notifications")
@admin_only
def notifications():
    db = get_db()
    kind = request.args.get("kind", "")
    sql, args = "SELECT * FROM notifications", []
    if kind in ("failed_login", "user_activity"):
        sql, args = sql + " WHERE kind=?", [kind]
    rows = db.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, min(int(request.args.get("limit", 50) or 50), 200))).fetchall()
    unread = db.execute("SELECT COUNT(*) c FROM notifications WHERE is_read=0").fetchone()["c"]
    return jsonify(items=[dict(r) for r in rows], unread=unread)


@bp.post("/notifications/read")
@admin_only
def notifications_read():
    db = get_db()
    ids = (request.get_json(silent=True) or {}).get("ids")
    if ids:
        db.execute(f"UPDATE notifications SET is_read=1 WHERE id IN ({','.join('?' * len(ids))})",
                   [int(i) for i in ids])
    else:
        db.execute("UPDATE notifications SET is_read=1 WHERE is_read=0")
    unread = db.execute("SELECT COUNT(*) c FROM notifications WHERE is_read=0").fetchone()["c"]
    return jsonify(ok=True, unread=unread)


# ================================= users ===================================
def _user_json(u, perms, online):
    locked = bool(u["locked_until"] and parse_iso(u["locked_until"]) > utcnow())
    keys = [m["key"] for m in current_app.config["MODULES"]]
    return {
        "id": u["id"], "username": u["username"], "full_name": u["full_name"], "email": u["email"],
        "department": u["department"], "role": u["role"], "is_active": bool(u["is_active"]),
        "must_change_password": bool(u["must_change_password"]), "locked": locked,
        "last_login": u["last_login"], "login_count": u["login_count"], "created_at": u["created_at"],
        "online": online > 0,
        "permissions": {k: ("edit" if u["role"] == "admin" else perms.get(k, "none")) for k in keys},
    }


def _all_users(db):
    perms = {}
    for p in db.execute("SELECT user_id, module, level FROM permissions"):
        perms.setdefault(p["user_id"], {})[p["module"]] = p["level"]
    online = {r["user_id"]: r["c"] for r in db.execute(
        "SELECT user_id, COUNT(*) c FROM sessions WHERE active=1 GROUP BY user_id")}
    return [_user_json(u, perms.get(u["id"], {}), online.get(u["id"], 0))
            for u in db.execute("SELECT * FROM users ORDER BY role, LOWER(full_name)")]


def _one_user(db, uid):
    return next((u for u in _all_users(db) if u["id"] == uid), None)


def _clean_permissions(raw):
    keys = {m["key"] for m in current_app.config["MODULES"]}
    raw = raw if isinstance(raw, dict) else {}
    out = {k: raw.get(k, "none") for k in keys}
    if any(v not in LEVEL_LABEL for v in out.values()) or any(k not in keys for k in raw):
        return None
    return out


@bp.get("/users")
@admin_only
def list_users():
    security.reap_expired_sessions()
    return jsonify(items=_all_users(get_db()))


@bp.post("/users")
@admin_only
def create_user():
    data = request.get_json(silent=True) or {}
    db = get_db()
    username = str(data.get("username", "")).strip()
    full_name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "") or "").strip()
    department = str(data.get("department", "") or "").strip()
    role = data.get("role", "user")
    password = str(data.get("password", ""))
    perms = _clean_permissions(data.get("permissions"))

    if not USERNAME_RE.match(username):
        return _err("Username must be 3-32 characters: letters, numbers, dot, dash or underscore.")
    if not full_name or len(full_name) > 80:
        return _err("Enter the user's full name.")
    if email and not EMAIL_RE.match(email):
        return _err("Enter a valid email address.")
    if role not in ("admin", "user"):
        return _err("Role must be Admin or User.")
    if perms is None:
        return _err("Permissions must be View, Edit or No Access.")
    problem = security.password_error(password, username)
    if problem:
        return _err(problem)
    if db_module.username_taken(db, username):
        return _err("That username is already taken.", 409)

    now = iso()
    with transaction(db):
        cur = db.execute(
            "INSERT INTO users (username,full_name,email,department,password_hash,role,must_change_password,"
            "password_changed_at,created_at) VALUES (?,?,?,?,?,?,1,?,?)",
            (username, full_name, email or None, department or None, security.hash_password(password), role, now, now))
        uid = cur.lastrowid
        if role == "user":
            for module, level in perms.items():
                db.execute("INSERT INTO permissions (user_id,module,level) VALUES (?,?,?)", (uid, module, level))
    names = _module_names()
    summary = "all modules (admin)" if role == "admin" else \
        ", ".join(f"{names[k]}: {LEVEL_LABEL[v]}" for k, v in perms.items() if v != "none") or "no module access"
    audit.log("user", "USER_CREATED", target=username, details=f"{role}; {summary}")
    return jsonify(item=_one_user(db, uid)), 201


@bp.patch("/users/<int:uid>")
@admin_only
def update_user(uid):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if target is None:
        return _err("User not found.", 404)
    data = request.get_json(silent=True) or {}
    fields, notes = {}, []

    for key, limit in (("full_name", 80), ("department", 80), ("email", 120)):
        if key in data:
            value = str(data[key] or "").strip()
            if key == "full_name" and not value:
                return _err("Full name cannot be empty.")
            if len(value) > limit or (key == "email" and value and not EMAIL_RE.match(value)):
                return _err(f"Check the {key.replace('_', ' ')}.")
            if value != (target[key] or ""):
                fields[key] = value or None
                notes.append(key.replace("_", " "))

    new_active = None
    if "is_active" in data and bool(data["is_active"]) != bool(target["is_active"]):
        new_active = bool(data["is_active"])
        if not new_active:
            if uid == g.user["id"]:
                return _err("You cannot disable your own account.")
            if target["role"] == "admin" and db.execute(
                    "SELECT COUNT(*) c FROM users WHERE role='admin' AND is_active=1").fetchone()["c"] <= 1:
                return _err("At least one active administrator is required.")
        fields["is_active"] = int(new_active)

    if not fields:
        return jsonify(item=_one_user(db, uid))
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), uid))

    if new_active is False:
        security.terminate_user_sessions(uid, "disabled")
        audit.log("user", "USER_DISABLED", target=target["username"], details="Account disabled; sessions ended")
    elif new_active is True:
        audit.log("user", "USER_ENABLED", target=target["username"], details="Account re-enabled")
    if notes:
        audit.log("user", "USER_UPDATED", target=target["username"], details="Changed " + ", ".join(notes))
    return jsonify(item=_one_user(db, uid))


@bp.put("/users/<int:uid>/permissions")
@admin_only
def set_permissions(uid):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if target is None:
        return _err("User not found.", 404)
    if target["role"] == "admin":
        return _err("Administrators always have full access to every module.")
    new = _clean_permissions((request.get_json(silent=True) or {}).get("permissions"))
    if new is None:
        return _err("Permissions must be View, Edit or No Access.")
    old = {r["module"]: r["level"] for r in db.execute("SELECT module, level FROM permissions WHERE user_id=?", (uid,))}
    names = _module_names()
    diffs = [f"{names[k]}: {LEVEL_LABEL[old.get(k, 'none')]} -> {LEVEL_LABEL[v]}"
             for k, v in new.items() if old.get(k, "none") != v]
    if diffs:
        with transaction(db):
            for module, level in new.items():
                db.execute("INSERT INTO permissions (user_id,module,level) VALUES (?,?,?) "
                           "ON CONFLICT(user_id,module) DO UPDATE SET level=excluded.level", (uid, module, level))
        audit.log("user", "PERMISSIONS_CHANGED", target=target["username"], details="; ".join(diffs))
        broker.publish("permissions", {}, user_ids=[uid])
    return jsonify(item=_one_user(db, uid))


@bp.post("/users/<int:uid>/reset-password")
@admin_only
def reset_password(uid):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if target is None:
        return _err("User not found.", 404)
    password = str((request.get_json(silent=True) or {}).get("password", ""))
    problem = security.password_error(password, target["username"])
    if problem:
        return _err(problem)
    db.execute("UPDATE users SET password_hash=?, must_change_password=1, failed_attempts=0, locked_until=NULL,"
               " password_changed_at=? WHERE id=?", (security.hash_password(password), iso(), uid))
    security.terminate_user_sessions(uid, "terminated")
    audit.log("user", "PASSWORD_RESET", target=target["username"],
              details="Temporary password set; user must change it at next login")
    return jsonify(item=_one_user(db, uid))


@bp.post("/users/<int:uid>/unlock")
@admin_only
def unlock_user(uid):
    db = get_db()
    target = db.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    if target is None:
        return _err("User not found.", 404)
    db.execute("UPDATE users SET locked_until=NULL, failed_attempts=0 WHERE id=?", (uid,))
    audit.log("security", "ACCOUNT_UNLOCKED", target=target["username"], details="Unlocked by administrator",
              notify=False)
    return jsonify(item=_one_user(db, uid))


@bp.delete("/users/<int:uid>")
@admin_only
def delete_user(uid):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if target is None:
        return _err("User not found.", 404)
    if uid == g.user["id"]:
        return _err("You cannot delete your own account.")
    if target["role"] == "admin" and db.execute(
            "SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"] <= 1:
        return _err("At least one administrator is required.")
    security.terminate_user_sessions(uid, "terminated")
    db.execute("DELETE FROM users WHERE id=?", (uid,))       # permissions + sessions cascade
    audit.log("user", "USER_DELETED", target=target["username"], details=f"{target['role']} account removed")
    return jsonify(ok=True)


# ============================== audit trail =================================
def _day_bound(value, end=False):
    try:
        y, m, d = (int(x) for x in value.split("-"))
        local = datetime(y, m, d, tzinfo=reports.local_tz())
    except (ValueError, AttributeError):
        return None
    if end:
        local += timedelta(days=1)
    return iso(local.astimezone(timezone.utc))


@bp.get("/audit")
@admin_only
def audit_list():
    a = request.args
    where, args = [], []
    if a.get("category"):
        where.append("category=?"); args.append(a["category"])
    if a.get("action"):
        where.append("action=?"); args.append(a["action"])
    if a.get("result") in ("0", "1"):
        where.append("success=?"); args.append(int(a["result"]))
    if a.get("q"):
        where.append("(username LIKE ? OR target LIKE ? OR details LIKE ? OR ip LIKE ?)")
        args += [f"%{a['q'].strip()}%"] * 4
    if _day_bound(a.get("from")):
        where.append("ts >= ?"); args.append(_day_bound(a["from"]))
    if _day_bound(a.get("to")):
        where.append("ts < ?"); args.append(_day_bound(a["to"], end=True))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    per_page = min(max(int(a.get("per_page", 25) or 25), 5), 100)
    page = max(int(a.get("page", 1) or 1), 1)
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM audit_log{clause}", args).fetchone()[0]
    rows = db.execute(f"SELECT * FROM audit_log{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                      (*args, per_page, (page - 1) * per_page)).fetchall()
    return jsonify(items=[dict(r) for r in rows], total=total, page=page,
                   pages=max(1, -(-total // per_page)))


@bp.get("/audit/verify")
@admin_only
def audit_verify():
    result = _chain_status(get_db(), force=True)
    audit.log("security", "AUDIT_VERIFIED", notify=False,
              details=f"{result['checked']} entries checked - " + ("intact" if result["ok"] else "TAMPERING DETECTED"))
    return jsonify(result)


# ================================ sessions ==================================
@bp.get("/sessions")
@admin_only
def sessions():
    security.reap_expired_sessions()
    rows = get_db().execute(
        "SELECT s.id, s.created_at, s.last_seen, s.ip, s.user_agent, u.username, u.full_name, u.role"
        " FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.active=1 ORDER BY s.last_seen DESC").fetchall()
    return jsonify(items=[{**dict(r), "current": r["id"] == g.session_id} for r in rows])


@bp.delete("/sessions/<int:sid>")
@admin_only
def terminate_session(sid):
    db = get_db()
    row = db.execute("SELECT s.id, s.sid, s.user_id, u.username FROM sessions s JOIN users u ON u.id=s.user_id"
                     " WHERE s.id=? AND s.active=1", (sid,)).fetchone()
    if row is None:
        return _err("Session already ended.", 404)
    if row["id"] == g.session_id:
        return _err("Use Sign out to end your own session.")
    security.end_session(row["id"], "terminated")
    broker.publish("force_logout", {"reason": "terminated"}, sid=row["sid"])
    broker.publish("presence", {}, admins=True)
    audit.log("user", "SESSION_TERMINATED", target=row["username"], details="Session ended by administrator")
    return jsonify(ok=True)


# ================================ exports ===================================
@bp.get("/export/<name>")
@admin_only
def export(name):
    if name not in ("audit", "logins", "users", "records"):
        return _err("Unknown report.", 404)
    return send_report(name, request.args.get("fmt", "xlsx"))
