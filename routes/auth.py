"""Sign in / sign out, session status and password change."""
import math
import secrets
from datetime import timedelta

from flask import Blueprint, current_app, g, jsonify, request, session, url_for

import audit
import security
import db as db_module
from db import get_db, iso, parse_iso, transaction, utcnow
from realtime import broker

bp = Blueprint("auth", __name__, url_prefix="/api")


def _err(message, status, **extra):
    return jsonify(error=message, **extra), status


@bp.post("/login")
def login():
    cfg = current_app.config
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()[:64]
    password = str(data.get("password", ""))[:256]
    login_type = data.get("login_type")
    if login_type not in ("admin", "user"):
        return _err("Choose Admin Login or User Login.", 400)
    if not username or not password:
        return _err("Enter your username and password.", 400)

    if security.rate_limited(audit.client_ip()):
        audit.log("security", "RATE_LIMITED", username=username, success=False, notify=False,
                  details="Too many login attempts from this address")
        return _err("Too many attempts. Wait a few minutes and try again.", 429)

    db = get_db()
    row = db_module.find_user_by_username(db, username)
    portal = f"{login_type} portal"

    if row is None:
        security.verify_password(security.DUMMY_HASH, password)  # same timing as a real check
        audit.log("auth", "LOGIN_FAILED", username=username, target=portal, success=False,
                  details="Unknown username")
        return _err("Invalid username or password.", 401)

    who = {"id": row["id"], "username": row["username"]}
    now = utcnow()

    if row["locked_until"] and parse_iso(row["locked_until"]) > now:
        mins = max(1, math.ceil((parse_iso(row["locked_until"]) - now).total_seconds() / 60))
        audit.log("auth", "LOGIN_BLOCKED", user=who, target=portal, success=False,
                  details=f"Account locked, {mins} min remaining")
        return _err(f"Account locked after repeated failed logins. Try again in {mins} minute(s) "
                    "or ask an administrator to unlock it.", 423)

    if not security.verify_password(row["password_hash"], password):
        attempts = row["failed_attempts"] + 1
        lock = attempts >= cfg["MAX_FAILED_LOGINS"]
        if lock:
            until = iso(now + timedelta(minutes=cfg["LOCKOUT_MINUTES"]))
            db.execute("UPDATE users SET failed_attempts=0, locked_until=? WHERE id=?", (until, row["id"]))
        else:
            db.execute("UPDATE users SET failed_attempts=? WHERE id=?", (attempts, row["id"]))
        audit.log("auth", "LOGIN_FAILED", user=who, target=portal, success=False,
                  details=f"Wrong password (attempt {attempts} of {cfg['MAX_FAILED_LOGINS']})")
        if lock:
            audit.log("security", "ACCOUNT_LOCKED", user=who, success=False,
                      details=f"Locked for {cfg['LOCKOUT_MINUTES']} minutes after "
                              f"{cfg['MAX_FAILED_LOGINS']} failed attempts")
            return _err(f"Too many failed attempts. Account locked for {cfg['LOCKOUT_MINUTES']} minutes.", 423)
        return _err("Invalid username or password.", 401)

    if not row["is_active"]:
        audit.log("auth", "LOGIN_FAILED", user=who, target=portal, success=False, details="Account disabled")
        return _err("This account is disabled. Contact your administrator.", 403)

    if row["role"] != login_type:
        right = "Admin" if row["role"] == "admin" else "User"
        audit.log("auth", "LOGIN_FAILED", user=who, target=portal, success=False,
                  details=f"Wrong portal: {row['role']} account used the {login_type} login")
        return _err(f"This is {'an' if right == 'Admin' else 'a'} {right} account. "
                    f"Use the {right} Login tab.", 403)

    with transaction(db):
        db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=?, "
                   "login_count=login_count+1 WHERE id=?", (iso(now), row["id"]))
        sid = security.create_session(row["id"])
    session.clear()                       # new session id on login (prevents fixation)
    session["sid"] = sid
    session["csrf"] = secrets.token_urlsafe(32)
    audit.log("auth", "LOGIN", user=who, details=f"Signed in via {portal}")
    broker.publish("presence", {}, admins=True)
    return jsonify(ok=True, csrf=session["csrf"], redirect=url_for("pages.app_shell"))


@bp.post("/logout")
@security.login_required(touch=False, allow_pw_change=True)
def logout():
    security.end_session(g.session_id, "logout")
    audit.log("auth", "LOGOUT", details="Signed out")
    session.clear()
    broker.publish("presence", {}, admins=True)
    return jsonify(ok=True, redirect=url_for("pages.login"))


@bp.get("/me")
@security.login_required(touch=False, allow_pw_change=True)
def me():
    u, cfg = g.user, current_app.config
    unread = 0
    if u["role"] == "admin":
        unread = get_db().execute("SELECT COUNT(*) c FROM notifications WHERE is_read=0").fetchone()["c"]
    return jsonify(
        user={k: u[k] for k in ("id", "username", "full_name", "email", "department", "role",
                                "last_login", "must_change_password")},
        permissions=security.user_permissions(u),
        modules=cfg["MODULES"],
        statuses=cfg["RECORD_STATUSES"],
        idle_timeout=cfg["SESSION_IDLE_TIMEOUT"],
        remaining=max(0, int(cfg["SESSION_IDLE_TIMEOUT"] - u["idle_seconds"])),
        unread=unread,
    )


@bp.get("/session/status")
@security.login_required(touch=False, allow_pw_change=True)
def session_status():
    timeout = current_app.config["SESSION_IDLE_TIMEOUT"]
    return jsonify(remaining=max(0, int(timeout - g.user["idle_seconds"])), idle_timeout=timeout)


@bp.post("/session/ping")
@security.login_required(allow_pw_change=True)
def session_ping():
    return jsonify(remaining=current_app.config["SESSION_IDLE_TIMEOUT"])


@bp.post("/change-password")
@security.login_required(allow_pw_change=True)
def change_password():
    data = request.get_json(silent=True) or {}
    current, new = str(data.get("current_password", "")), str(data.get("new_password", ""))
    db = get_db()
    row = db.execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if not security.verify_password(row["password_hash"], current):
        audit.log("security", "PASSWORD_CHANGE_FAILED", success=False, details="Wrong current password",
                  notify=False)
        return _err("Current password is incorrect.", 400)
    if new == current:
        return _err("Choose a password different from the current one.", 400)
    problem = security.password_error(new, g.user["username"])
    if problem:
        return _err(problem, 400)
    db.execute("UPDATE users SET password_hash=?, must_change_password=0, password_changed_at=? WHERE id=?",
               (security.hash_password(new), iso(), g.user["id"]))
    security.terminate_user_sessions(g.user["id"], "terminated", keep_session_id=g.session_id)
    audit.log("security", "PASSWORD_CHANGED", details="Password changed by user; other sessions ended",
              notify=False)
    return jsonify(ok=True)


@bp.get("/me/activity")
@security.login_required()
def my_activity():
    rows = get_db().execute(
        "SELECT ts, action, target, details, ip, success FROM audit_log WHERE user_id=? "
        "ORDER BY id DESC LIMIT 20", (g.user["id"],)).fetchall()
    return jsonify(items=[dict(r) for r in rows])
