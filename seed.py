"""First-run data: bootstrap administrator and optional demo users/records."""
import audit
from db import get_db, iso, transaction
from security import hash_password

DEMO_PASSWORD = "User@1234"

DEMO_USERS = [
    # username, full name, department, {module: level}
    ("rahul.patil", "Rahul Patil", "Machine Shop",
     {"machine_shop": "edit", "press_shop": "view", "assembly_shop": "none", "winding_shop": "none"}),
    ("sneha.kulkarni", "Sneha Kulkarni", "Assembly",
     {"machine_shop": "none", "press_shop": "none", "assembly_shop": "edit", "winding_shop": "view"}),
    ("amit.deshmukh", "Amit Deshmukh", "Winding",
     {"machine_shop": "none", "press_shop": "edit", "assembly_shop": "none", "winding_shop": "edit"}),
]

DEMO_RECORDS = {
    "machine_shop": [
        ("MS-1001", "Crankshaft journal turning", 120, "In Progress"),
        ("MS-1002", "Gear blank facing", 250, "Planned"),
        ("MS-1003", "Valve body boring (CNC)", 60, "Completed"),
        ("MS-1004", "Shaft keyway milling", 90, "On Hold"),
    ],
    "press_shop": [
        ("PS-2001", "Refrigerator door panel - 350T press", 800, "In Progress"),
        ("PS-2002", "Cabinet side panel blanking", 1200, "Planned"),
        ("PS-2003", "Steel almirah shelf forming", 450, "Completed"),
    ],
    "assembly_shop": [
        ("AS-3001", "Vacuum pump sub-assembly", 75, "In Progress"),
        ("AS-3002", "Compressor final assembly", 40, "Planned"),
        ("AS-3003", "Control panel wiring harness", 110, "Completed"),
    ],
    "winding_shop": [
        ("WS-4001", "Stator coil winding - 5 HP motor", 60, "In Progress"),
        ("WS-4002", "Transformer LV winding", 25, "Planned"),
        ("WS-4003", "Rotor re-winding (repair)", 12, "On Hold"),
    ],
}


def seed_admin(app):
    """Create the bootstrap admin once. It must change its password at first login."""
    with app.app_context():
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
            return
        now = iso()
        db.execute(
            "INSERT INTO users (username,full_name,email,department,password_hash,role,"
            "must_change_password,password_changed_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (app.config["DEFAULT_ADMIN_USER"], "System Administrator", None, "IT",
             hash_password(app.config["DEFAULT_ADMIN_PASS"]), "admin", 1, now, now))
        audit.log("security", "SYSTEM_INIT", username="system", ip="system", notify=False,
                  details="Bootstrap administrator created")


def seed_demo(app):
    """Three sample shop-floor users and a few records per module (skips if users exist)."""
    with app.app_context():
        db = get_db()
        if db.execute("SELECT COUNT(*) c FROM users WHERE role='user'").fetchone()["c"]:
            return False
        now = iso()
        with transaction(db):
            for username, name, dept, perms in DEMO_USERS:
                cur = db.execute(
                    "INSERT INTO users (username,full_name,email,department,password_hash,role,"
                    "must_change_password,password_changed_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (username, name, f"{username}@example.com", dept,
                     hash_password(DEMO_PASSWORD), "user", 0, now, now))
                for module, level in perms.items():
                    db.execute("INSERT INTO permissions (user_id,module,level) VALUES (?,?,?)",
                               (cur.lastrowid, module, level))
            for module, rows in DEMO_RECORDS.items():
                for part_no, desc, qty, status in rows:
                    db.execute(
                        "INSERT INTO records (module,part_no,description,quantity,status,updated_by,"
                        "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                        (module, part_no, desc, qty, status, "system", now, now))
        audit.log("security", "DEMO_DATA_LOADED", username="system", ip="system", notify=False,
                  details="Demo users and sample records created")
        return True
