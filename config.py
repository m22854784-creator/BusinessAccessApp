"""Central configuration. Override anything with environment variables."""
import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _load_secret_key():
    """Use BAMS_SECRET_KEY if set, else create one once and persist it."""
    env = os.environ.get("BAMS_SECRET_KEY")
    if env:
        return env
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    path = os.path.join(INSTANCE_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    with open(path) as fh:
        return fh.read().strip()


class Config:
    APP_NAME = "Business Access Management System"
    COMPANY = "Godrej & Boyce"

    SECRET_KEY = _load_secret_key()
    # If DATABASE_URL is set (Render provides this automatically when you attach a
    # PostgreSQL database), use it - that data survives restarts and redeploys.
    # Otherwise fall back to a local SQLite file, which is fine for your own PC
    # but is NOT persistent on most free hosting (the disk gets wiped on restart).
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    DB_ENGINE = "postgres" if DATABASE_URL else "sqlite"
    DATABASE = os.environ.get("BAMS_DATABASE", os.path.join(INSTANCE_DIR, "bams.db"))
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    # ---- Security ---------------------------------------------------------
    SESSION_IDLE_TIMEOUT = int(os.environ.get("BAMS_IDLE_TIMEOUT", 15 * 60))      # seconds
    SESSION_ABSOLUTE_TIMEOUT = int(os.environ.get("BAMS_ABS_TIMEOUT", 8 * 3600))  # seconds
    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 15
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_MAX_AGE_DAYS = 90
    LOGIN_RATE_LIMIT = (20, 300)  # max attempts per IP within N seconds

    SESSION_COOKIE_NAME = "bams_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("BAMS_HTTPS") == "1"

    # ---- Bootstrap admin (must change password on first login) -------------
    DEFAULT_ADMIN_USER = "admin"
    DEFAULT_ADMIN_PASS = os.environ.get("BAMS_ADMIN_PASSWORD", "Admin@123")

    # ---- Reports: display timezone (minutes east of UTC; IST = 330) --------
    TZ_OFFSET_MIN = int(os.environ.get("BAMS_TZ_OFFSET_MIN", 330))

    # ---- Business modules --------------------------------------------------
    MODULES = [
        {"key": "machine_shop", "name": "Machine Shop", "icon": "tool",
         "description": "Machining jobs, tooling and work orders"},
        {"key": "press_shop", "name": "Press Shop", "icon": "layers",
         "description": "Pressing, stamping and die schedules"},
        {"key": "assembly_shop", "name": "Assembly Shop", "icon": "box",
         "description": "Sub-assembly and final assembly lines"},
        {"key": "winding_shop", "name": "Winding Shop", "icon": "zap",
         "description": "Coil winding and motor build orders"},
    ]
    RECORD_STATUSES = ["Planned", "In Progress", "On Hold", "Completed"]
