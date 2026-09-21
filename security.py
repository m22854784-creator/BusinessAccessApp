"""Authentication helpers: password policy, CSRF, sessions, decorators, headers."""
import functools
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from flask import current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import audit
from db import get_db, iso, parse_iso, utcnow
from realtime import broker

HASH_METHOD = "pbkdf2:sha256:600000"
# Used to burn the same CPU time when a username does not exist (timing side-channel).
DUMMY_HASH = generate_password_hash("not-a-real-password", method=HASH_METHOD)
LEVELS = {"none": 0, "view": 1, "edit": 2}

ERRORS = {
    "NO_SESSION": "Please sign in to continue.",
    "SESSION_TIMEOUT": "Your session expired due to inactivity.",
    "SESSION_TERMINATED": "Your session was ended by an administrator.",
}
REASON_PARAM = {"SESSION_TIMEOUT": "timeout", "SESSION_TERMINATED": "terminated"}


# ---- passwords --------------------------------------------------------------
def hash_password(password):
    return generate_password_hash(password, method=HASH_METHOD)


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def password_issues(password, username=""):
    """Return a list of policy problems (empty list = password is acceptable)."""
    minimum = current_app.config["PASSWORD_MIN_LENGTH"]
    issues = []
    if len(password) < minimum:
        issues.append(f"at least {minimum} characters")
    if not re.search(r"[A-Z]", password):
        issues.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        issues.append("a lowercase letter")
    if not re.search(r"\d", password):
        issues.append("a number")
    if not re.search(r"[^A-Za-z0-9]", password):
        issues.append("a special character")
    if username and username.lower() in password.lower():
        issues.append("no part of the username")
    return issues


def password_error(password, username=""):
    issues = password_issues(password, username)
    return ("Password needs " + ", ".join(issues) + ".") if issues else None


# ---- login rate limit (per IP, in memory) --------------------------------
_attempts = defaultdict(deque)
_rl_lock = threading.Lock()


def rate_limited(ip):
    limit, window = current_app.config["LOGIN_RATE_LIMIT"]
    now = time.time()
    with _rl_lock:
        dq = _attempts[ip]
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= limit:
            return True
        dq.append(now)
        return False


# ---- CSRF -------------------------------------------------------------------
def csrf_token():
    token = session.get("csrf")
    if not token:
        token = session["csrf"] = secrets.token_urlsafe(32)
    return token


def csrf_protect():
    """before_request hook: every state-changing request needs the token."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.headers.get("X-CSRF-Token", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            return jsonify(error="Security token missing or expired. Reload the page.", code="CSRF"), 400


# ---- sessions ---------------------------------------------------------------
def create_session(user_id):
    sid = secrets.token_urlsafe(32)
    now = iso()
    get_db().execute(
        "INSERT INTO sessions (sid,user_id,created_at,last_seen,ip,user_agent) VALUES (?,?,?,?,?,?)",
        (sid, user_id, now, now, audit.client_ip(), (request.headers.get("User-Agent") or "")[:200]),
    )
    return sid


def end_session(session_id, reason):
    cur = get_db().execute(
        "UPDATE sessions SET active=0, ended_reason=? WHERE id=? AND active=1", (reason, session_id))
    return cur.rowcount > 0


def expire_session(row, reason="timeout"):
    if end_session(row["session_id"], reason):
        audit.log("auth", "SESSION_TIMEOUT", user=row, details="Signed out after inactivity")
        broker.publish("presence", {}, admins=True)


def reap_expired_sessions():
    """Close every session that is past its idle/absolute limit."""
    cfg = current_app.config
    db, now = get_db(), utcnow()
    idle_cut = iso(now - timedelta(seconds=cfg["SESSION_IDLE_TIMEOUT"]))
    abs_cut = iso(now - timedelta(seconds=cfg["SESSION_ABSOLUTE_TIMEOUT"]))
    rows = db.execute(
        "SELECT s.id AS session_id, s.sid, u.id, u.username FROM sessions s JOIN users u ON u.id=s.user_id"
        " WHERE s.active=1 AND (s.last_seen < ? OR s.created_at < ?)", (idle_cut, abs_cut)).fetchall()
    for r in rows:
        expire_session(dict(r))
        broker.publish("force_logout", {"reason": "timeout"}, sid=r["sid"])


def terminate_user_sessions(user_id, reason, keep_session_id=None):
    """End all of a user's sessions and tell their browsers to sign out."""
    db = get_db()
    rows = db.execute("SELECT id, sid FROM sessions WHERE user_id=? AND active=1", (user_id,)).fetchall()
    for r in rows:
        if r["id"] != keep_session_id:
            end_session(r["id"], reason)
            broker.publish("force_logout", {"reason": reason}, sid=r["sid"])
    broker.publish("presence", {}, admins=True)


def resolve_session(touch=True):
    """Validate the cookie's session. Returns (user_dict, None) or (None, error_code)."""
    sid = session.get("sid")
    if not sid:
        return None, "NO_SESSION"
    cfg = current_app.config
    db = get_db()
    row = db.execute(
        "SELECT s.id AS session_id, s.created_at AS session_created, s.last_seen, s.active,"
        " s.ended_reason, u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.sid = ?",
        (sid,)).fetchone()
    if row is None:
        session.pop("sid", None)
        return None, "NO_SESSION"
    if not row["active"]:
        return None, {"terminated": "SESSION_TERMINATED", "disabled": "SESSION_TERMINATED",
                      "timeout": "SESSION_TIMEOUT"}.get(row["ended_reason"], "NO_SESSION")
    now = utcnow()
    idle = (now - parse_iso(row["last_seen"])).total_seconds()
    age = (now - parse_iso(row["session_created"])).total_seconds()
    if not row["is_active"]:
        end_session(row["session_id"], "disabled")
        return None, "SESSION_TERMINATED"
    if idle > cfg["SESSION_IDLE_TIMEOUT"] or age > cfg["SESSION_ABSOLUTE_TIMEOUT"]:
        expire_session(dict(row))
        return None, "SESSION_TIMEOUT"
    # Background refreshes (live updates) send X-Background so they never extend the session.
    if touch and request.headers.get("X-Background") != "1" and idle >= 5:
        db.execute("UPDATE sessions SET last_seen=? WHERE id=?", (iso(now), row["session_id"]))
        idle = 0
    user = dict(row)
    user["idle_seconds"] = idle
    g.user, g.session_id, g.sid = user, row["session_id"], sid
    return user, None


def login_required(touch=True, allow_pw_change=False, admin=False):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            is_api = request.path.startswith("/api/")
            user, err = resolve_session(touch)
            if err:
                if is_api:
                    return jsonify(error=ERRORS[err], code=err), 401
                return redirect(url_for("pages.login", reason=REASON_PARAM.get(err)))
            if user["must_change_password"] and not allow_pw_change:
                return jsonify(error="You must change your password first.",
                               code="PASSWORD_CHANGE_REQUIRED"), 403
            if admin and user["role"] != "admin":
                audit.log("security", "ACCESS_DENIED", target=request.path, success=False,
                          details="Administrator area", notify=False)
                return jsonify(error="Administrator access required.", code="FORBIDDEN"), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---- module permissions ---------------------------------------------------
def module_level(user, module_key):
    if user["role"] == "admin":
        return "edit"
    row = get_db().execute("SELECT level FROM permissions WHERE user_id=? AND module=?",
                           (user["id"], module_key)).fetchone()
    return row["level"] if row else "none"


def user_permissions(user):
    return {m["key"]: module_level(user, m["key"]) for m in current_app.config["MODULES"]}


def users_who_can_view(module_key):
    rows = get_db().execute(
        "SELECT user_id FROM permissions WHERE module=? AND level IN ('view','edit')", (module_key,))
    return {r["user_id"] for r in rows}


# ---- response headers -----------------------------------------------------
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'")
    if request.path.startswith("/api/") or request.path in ("/app", "/login"):
        resp.headers["Cache-Control"] = "no-store"
    if current_app.config["SESSION_COOKIE_SECURE"]:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp
