# Godrej & Boyce - Business Access Management System

Flask + SQLite + plain HTML/CSS/JavaScript. No build step, no external CDN.

## Run it

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
python app.py --demo             # first run: also loads 3 demo users + sample records
```
Open http://127.0.0.1:5000 (other PCs on the plant network: `python app.py --host 0.0.0.0`).

| Account | Login tab | Password |
|---|---|---|
| `admin` | Admin login | `Admin@123` (you must change it at first sign-in) |
| `rahul.patil` (Machine: Edit, Press: View) | User login | `User@1234` |
| `sneha.kulkarni` (Assembly: Edit, Winding: View) | User login | `User@1234` |
| `amit.deshmukh` (Press: Edit, Winding: Edit) | User login | `User@1234` |

Without `--demo` only the `admin` account exists. Set `BAMS_ADMIN_PASSWORD` to change the initial admin password.
Try real time: sign in as admin in one browser and as `rahul.patil` in a private window, then edit a record.
The admin dashboard, activity feed and notification bell update instantly.

## Project structure

```
godrej_bams/
├── app.py            Flask app factory + run script (--demo, --host, --port)
├── config.py         All settings (timeouts, lockout, modules, timezone)
├── db.py             SQLite schema, connections, transactions
├── security.py       Password policy, CSRF, sessions, decorators, security headers
├── audit.py          Hash-chained audit trail + notifications
├── realtime.py       In-memory pub/sub broker for live updates (SSE)
├── reports.py        PDF (reportlab) and Excel (openpyxl) generation
├── seed.py           Bootstrap admin + demo data
├── routes/
│   ├── pages.py      Welcome, login, app shell
│   ├── auth.py       Login, logout, session status, change password
│   ├── admin.py      Stats, users, permissions, audit, notifications, sessions, exports
│   ├── modules.py    Shop records (View/Edit/No Access enforced on the server)
│   └── stream.py     Server-Sent Events endpoint
├── templates/        base, welcome, login, app
├── static/
│   ├── css/style.css Godrej-style theme, light + dark
│   └── js/           theme, login, core, views-admin, views-user, app
├── tests/test_smoke.py   17 end-to-end tests
├── requirements.txt
└── instance/         bams.db and secret.key are created here on first run
```

## How each requirement is met

| Requirement | Where |
|---|---|
| Admin / User login, roles | `routes/auth.py` - the login tab must match the account role |
| Machine, Press, Assembly, Winding shops; View / Edit / No Access | `routes/modules.py`, `security.module_level` (admins always have Edit) |
| Admin dashboard: total users, login count, recent activity, notification center, security health | `routes/admin.py` `/stats`, `static/js/views-admin.js` |
| Audit logging (login, logout, record updates, user actions) | `audit.py`: append-only SQLite triggers + SHA-256 hash chain, "Verify integrity" button |
| Create / delete user, change permissions | `routes/admin.py`, Users page |
| Multi-user + real-time | Per-user DB sessions, live events via SSE, optimistic locking on records |
| SQLite | `db.py` (WAL mode) |
| Godrej look, welcome page, login page, dark mode | `templates/`, `static/css/style.css` |
| Activity feed, notification center | Dashboard + Notifications page |
| PDF / Excel export | `reports.py`; Reports page, Audit page, every shop page |
| Security | 15 min idle timeout (warning at 60 s), 8 h absolute limit, PBKDF2-SHA256 hashes, password policy, lockout after 5 failures, CSRF tokens, CSP headers, login rate limit |

## Configuration (`config.py` or environment)

`BAMS_IDLE_TIMEOUT` (seconds, default 900), `BAMS_SECRET_KEY`, `BAMS_DATABASE`, `BAMS_ADMIN_PASSWORD`,
`BAMS_TZ_OFFSET_MIN` (default 330 = IST, used in reports), `BAMS_HTTPS=1` (secure cookies + HSTS).

## Branding

Colours are CSS variables at the top of `static/css/style.css`. The `godrej` wordmark is plain text so the
project ships without the trademarked logo. To use the official logo, add the SVG to `static/img/` and
replace the `.wordmark` elements in `templates/*.html` and `static/js/app.js`.

## Production notes

- Run ONE process with many threads: `waitress-serve --host=0.0.0.0 --port=5000 --threads=32 --call app:create_app`.
  The live-update broker is in memory; for several processes replace `realtime.py` with Redis pub/sub.
- Put it behind HTTPS and set `BAMS_HTTPS=1`.
- Back up `instance/bams.db` and `instance/secret.key`.
- Run tests: `python -m unittest discover -s tests -v`
