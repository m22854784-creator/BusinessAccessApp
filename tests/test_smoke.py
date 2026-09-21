"""End-to-end smoke tests. Run:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app          # noqa: E402
from db import connect, iso, utcnow  # noqa: E402
from realtime import broker         # noqa: E402
from seed import seed_demo          # noqa: E402

ADMIN_PW = "Admin@123"
NEW_ADMIN_PW = "Godrej#Plant2026"


class Client:
    """Test client that always sends a CSRF token and JSON."""

    def __init__(self, app):
        self.c = app.test_client()
        self.c.get("/login")
        self.token()

    def token(self):
        with self.c.session_transaction() as s:
            self.csrf = s.get("csrf")
            if not self.csrf:
                s["csrf"] = self.csrf = "test-token"

    def req(self, method, url, json=None, **kw):
        return getattr(self.c, method)(url, json=json, headers={"X-CSRF-Token": self.csrf}, **kw)

    def get(self, url, **kw): return self.req("get", url, **kw)
    def post(self, url, json=None, **kw): return self.req("post", url, json, **kw)
    def put(self, url, json=None, **kw): return self.req("put", url, json, **kw)
    def patch(self, url, json=None, **kw): return self.req("patch", url, json, **kw)
    def delete(self, url, **kw): return self.req("delete", url, **kw)

    def login(self, user, pw, kind):
        r = self.post("/api/login", {"username": user, "password": pw, "login_type": kind})
        if r.status_code == 200:
            self.csrf = r.get_json()["csrf"]
        return r


class BamsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": os.path.join(self.tmp.name, "t.db"), "TESTING": True,
                               "LOGIN_RATE_LIMIT": (1000, 60)})
        seed_demo(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def admin(self):
        c = Client(self.app)
        self.assertEqual(c.login("admin", ADMIN_PW, "admin").status_code, 200)
        r = c.post("/api/change-password", {"current_password": ADMIN_PW, "new_password": NEW_ADMIN_PW})
        self.assertEqual(r.status_code, 200, r.get_json())
        return c

    def user(self, name="rahul.patil"):
        c = Client(self.app)
        self.assertEqual(c.login(name, "User@1234", "user").status_code, 200)
        return c

    # ---------------------------------------------------------------- auth
    def test_pages_render(self):
        c = self.app.test_client()
        for url in ("/", "/login", "/login?type=admin", "/healthz"):
            self.assertEqual(c.get(url).status_code, 200, url)
        self.assertEqual(c.get("/app").status_code, 302)          # not signed in

    def test_csrf_required(self):
        c = self.app.test_client()
        r = c.post("/api/login", json={"username": "x", "password": "y", "login_type": "user"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "CSRF")

    def test_admin_must_change_password_first(self):
        c = Client(self.app)
        self.assertEqual(c.login("admin", ADMIN_PW, "admin").status_code, 200)
        self.assertEqual(c.get("/api/admin/stats").get_json()["code"], "PASSWORD_CHANGE_REQUIRED")
        self.assertEqual(c.get("/api/me").get_json()["user"]["must_change_password"], 1)
        self.assertEqual(c.post("/api/change-password", {"current_password": ADMIN_PW,
                                                         "new_password": "weak"}).status_code, 400)
        self.assertEqual(c.post("/api/change-password", {"current_password": ADMIN_PW,
                                                         "new_password": NEW_ADMIN_PW}).status_code, 200)
        self.assertEqual(c.get("/api/admin/stats").status_code, 200)

    def test_wrong_portal_and_bad_password(self):
        c = Client(self.app)
        self.assertEqual(c.login("rahul.patil", "User@1234", "admin").status_code, 403)
        self.assertEqual(c.login("rahul.patil", "nope", "user").status_code, 401)
        self.assertEqual(c.login("ghost", "nope", "user").status_code, 401)

    def test_lockout_and_unlock(self):
        adm = self.admin()
        c = Client(self.app)
        for _ in range(4):
            self.assertEqual(c.login("rahul.patil", "bad", "user").status_code, 401)
        self.assertEqual(c.login("rahul.patil", "bad", "user").status_code, 423)
        self.assertEqual(c.login("rahul.patil", "User@1234", "user").status_code, 423)   # still locked
        users = adm.get("/api/admin/users").get_json()["items"]
        uid = next(u["id"] for u in users if u["username"] == "rahul.patil")
        self.assertTrue(next(u for u in users if u["id"] == uid)["locked"])
        adm.post(f"/api/admin/users/{uid}/unlock")
        self.assertEqual(c.login("rahul.patil", "User@1234", "user").status_code, 200)
        notes = adm.get("/api/admin/notifications?kind=failed_login").get_json()["items"]
        self.assertTrue(any(n["title"] == "Account locked" for n in notes))

    def test_idle_timeout(self):
        c = self.user()
        db = connect(self.app.config["DATABASE"])
        db.execute("UPDATE sessions SET last_seen=?", (iso(utcnow() - timedelta(seconds=99999)),))
        r = c.get("/api/me")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["code"], "SESSION_TIMEOUT")
        actions = [x["action"] for x in db.execute("SELECT action FROM audit_log")]
        self.assertIn("SESSION_TIMEOUT", actions)

    def test_logout_ends_session(self):
        c = self.user()
        self.assertEqual(c.post("/api/logout").status_code, 200)
        self.assertEqual(c.get("/api/me").status_code, 401)

    # ------------------------------------------------------ authorization
    def test_admin_area_blocked_for_users(self):
        c = self.user()
        self.assertEqual(c.get("/api/admin/stats").status_code, 403)
        self.assertEqual(c.get("/api/admin/users").status_code, 403)
        self.assertEqual(c.get("/api/admin/export/audit?fmt=pdf").status_code, 403)

    def test_module_permissions(self):
        c = self.user("rahul.patil")     # machine=edit press=view assembly=none winding=none
        mods = {m["key"]: m["level"] for m in c.get("/api/modules").get_json()["modules"]}
        self.assertEqual(mods, {"machine_shop": "edit", "press_shop": "view",
                                "assembly_shop": "none", "winding_shop": "none"})
        self.assertEqual(c.get("/api/modules/machine_shop/records").status_code, 200)
        self.assertEqual(c.get("/api/modules/press_shop/records").status_code, 200)
        self.assertEqual(c.get("/api/modules/assembly_shop/records").status_code, 403)
        new = {"part_no": "MS-9", "description": "Test part", "quantity": 5, "status": "Planned"}
        self.assertEqual(c.post("/api/modules/machine_shop/records", new).status_code, 201)
        self.assertEqual(c.post("/api/modules/press_shop/records", new).status_code, 403)   # view only
        self.assertEqual(c.get("/api/modules/press_shop/export?fmt=pdf").status_code, 200)
        self.assertEqual(c.get("/api/modules/winding_shop/export?fmt=pdf").status_code, 403)

    def test_record_crud_conflict_and_audit(self):
        c = self.user("rahul.patil")
        rec = c.post("/api/modules/machine_shop/records",
                     {"part_no": "MS-77", "description": "Spindle", "quantity": 10, "status": "Planned"}).get_json()["item"]
        upd = {"part_no": "MS-77", "description": "Spindle", "quantity": 20, "status": "In Progress",
               "version": rec["version"]}
        r = c.put(f"/api/modules/machine_shop/records/{rec['id']}", upd)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["item"]["version"], 2)
        stale = c.put(f"/api/modules/machine_shop/records/{rec['id']}", {**upd, "quantity": 99})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["code"], "CONFLICT")
        self.assertEqual(c.delete(f"/api/modules/machine_shop/records/{rec['id']}").status_code, 200)
        db = connect(self.app.config["DATABASE"])
        actions = [x["action"] for x in db.execute("SELECT action FROM audit_log")]
        for a in ("RECORD_CREATED", "RECORD_UPDATED", "RECORD_DELETED"):
            self.assertIn(a, actions)

    # ------------------------------------------------- user management
    def test_user_lifecycle_and_permissions(self):
        adm = self.admin()
        perms = {"machine_shop": "view", "press_shop": "none", "assembly_shop": "edit", "winding_shop": "none"}
        r = adm.post("/api/admin/users", {"username": "new.user", "full_name": "New User", "role": "user",
                                          "password": "Temp#Pass1", "permissions": perms})
        self.assertEqual(r.status_code, 201, r.get_json())
        uid = r.get_json()["item"]["id"]
        self.assertEqual(adm.post("/api/admin/users", {"username": "new.user", "full_name": "X", "role": "user",
                                                       "password": "Temp#Pass1", "permissions": perms}).status_code, 409)
        # new user must change password, then sees exactly the permissions given
        u = Client(self.app)
        self.assertEqual(u.login("new.user", "Temp#Pass1", "user").status_code, 200)
        self.assertEqual(u.get("/api/modules").get_json()["code"], "PASSWORD_CHANGE_REQUIRED")
        u.post("/api/change-password", {"current_password": "Temp#Pass1", "new_password": "Better#Pass22"})
        self.assertEqual(u.get("/api/modules/assembly_shop/records").status_code, 200)
        self.assertEqual(u.get("/api/modules/press_shop/records").status_code, 403)
        # live permission change is pushed to that user's stream
        sub = broker.subscribe(uid, "user", "x")
        perms2 = {**perms, "press_shop": "edit", "assembly_shop": "none"}
        self.assertEqual(adm.put(f"/api/admin/users/{uid}/permissions", {"permissions": perms2}).status_code, 200)
        self.assertEqual(sub.q.get_nowait()["event"], "permissions")
        broker.unsubscribe(sub)
        self.assertEqual(u.get("/api/modules/press_shop/records").status_code, 200)
        self.assertEqual(u.get("/api/modules/assembly_shop/records").status_code, 403)
        # delete signs the user out
        self.assertEqual(adm.delete(f"/api/admin/users/{uid}").status_code, 200)
        self.assertEqual(u.get("/api/me").status_code, 401)

    def test_admin_safety_rules(self):
        adm = self.admin()
        me = adm.get("/api/me").get_json()["user"]["id"]
        self.assertEqual(adm.delete(f"/api/admin/users/{me}").status_code, 400)
        self.assertEqual(adm.patch(f"/api/admin/users/{me}", {"is_active": False}).status_code, 400)
        self.assertEqual(adm.post("/api/admin/users", {"username": "bad", "full_name": "Bad", "role": "user",
                                                       "password": "short", "permissions": {}}).status_code, 400)

    # ------------------------------------------------- dashboard & audit
    def test_dashboard_feed_and_audit_integrity(self):
        adm = self.admin()
        self.user("sneha.kulkarni")
        Client(self.app).login("rahul.patil", "bad", "user")
        s = adm.get("/api/admin/stats").get_json()
        self.assertEqual(s["total_users"], 4)
        self.assertGreaterEqual(s["login_count"], 2)
        self.assertGreaterEqual(s["failed_24h"], 1)
        self.assertEqual(len(s["trend"]), 7)
        self.assertGreaterEqual(s["online_now"], 2)
        self.assertGreaterEqual(s["health"]["score"], 60)
        self.assertTrue(any(c["key"] == "audit_chain" and c["status"] == "ok" for c in s["health"]["checks"]))
        feed = adm.get("/api/admin/activity?type=logins").get_json()["items"]
        self.assertTrue(all(i["category"] == "auth" for i in feed))
        self.assertTrue(adm.get("/api/admin/audit/verify").get_json()["ok"])
        page = adm.get("/api/admin/audit?per_page=5&q=rahul").get_json()
        self.assertTrue(page["total"] >= 1 and len(page["items"]) <= 5)

    def test_audit_is_append_only_and_tamper_evident(self):
        adm = self.admin()
        db = connect(self.app.config["DATABASE"])
        with self.assertRaises(Exception):
            db.execute("DELETE FROM audit_log")
        with self.assertRaises(Exception):
            db.execute("UPDATE audit_log SET username='x'")
        # simulate an attacker bypassing the trigger, then verify detection
        db.execute("DROP TRIGGER audit_no_update")
        db.execute("UPDATE audit_log SET details='forged' WHERE id=2")
        result = adm.get("/api/admin/audit/verify").get_json()
        self.assertFalse(result["ok"])
        self.assertEqual(result["broken_at"], 2)

    def test_notifications_and_sessions(self):
        adm = self.admin()
        self.user()
        n = adm.get("/api/admin/notifications").get_json()
        self.assertGreater(n["unread"], 0)
        self.assertEqual(adm.post("/api/admin/notifications/read", {}).get_json()["unread"], 0)
        sessions = adm.get("/api/admin/sessions").get_json()["items"]
        other = next(s for s in sessions if not s["current"])
        self.assertEqual(adm.delete(f"/api/admin/sessions/{other['id']}").status_code, 200)

    # ------------------------------------------------------------ exports
    def test_exports(self):
        adm = self.admin()
        for name in ("audit", "logins", "users", "records"):
            pdf = adm.get(f"/api/admin/export/{name}?fmt=pdf")
            self.assertEqual(pdf.status_code, 200, name)
            self.assertTrue(pdf.data.startswith(b"%PDF"), name)
            xls = adm.get(f"/api/admin/export/{name}?fmt=xlsx")
            self.assertEqual(xls.status_code, 200, name)
            self.assertTrue(xls.data.startswith(b"PK"), name)
        self.assertEqual(adm.get("/api/admin/export/nope?fmt=pdf").status_code, 404)

    def test_security_headers(self):
        r = self.app.test_client().get("/login")
        self.assertIn("script-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")


if __name__ == "__main__":
    unittest.main()
