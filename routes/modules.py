"""Business modules (shops): permission-checked records with live updates."""
from flask import Blueprint, current_app, g, jsonify, request, send_file

import audit
import reports
import security
from db import get_db, iso
from realtime import broker

bp = Blueprint("modules", __name__, url_prefix="/api/modules")
LEVELS = security.LEVELS


def _guard(key, need):
    """Return (module_dict, None) or (None, error_response)."""
    mod = next((m for m in current_app.config["MODULES"] if m["key"] == key), None)
    if mod is None:
        return None, (jsonify(error="Unknown module."), 404)
    level = security.module_level(g.user, key)
    if LEVELS[level] < LEVELS[need]:
        audit.log("security", "ACCESS_DENIED", target=mod["name"], success=False, notify=False,
                  details=f"Needs {need} access, user has {level}")
        return None, (jsonify(error=f"You do not have {need} access to {mod['name']}.", code="FORBIDDEN"), 403)
    return mod, None


def _clean(data):
    part_no = str(data.get("part_no", "")).strip()
    desc = str(data.get("description", "")).strip()
    notes = str(data.get("notes", "") or "").strip()
    status = data.get("status", "Planned")
    try:
        qty = int(data.get("quantity", 0))
    except (TypeError, ValueError):
        return None, "Quantity must be a whole number."
    if not part_no or len(part_no) > 40:
        return None, "Part number is required (max 40 characters)."
    if not desc or len(desc) > 200:
        return None, "Description is required (max 200 characters)."
    if not 0 <= qty <= 10_000_000:
        return None, "Quantity must be between 0 and 10,000,000."
    if status not in current_app.config["RECORD_STATUSES"]:
        return None, "Choose a valid status."
    if len(notes) > 500:
        return None, "Notes can be up to 500 characters."
    return {"part_no": part_no, "description": desc, "quantity": qty, "status": status, "notes": notes}, None


def _broadcast(module_key, action, record_id, part_no):
    broker.publish("record", {"module": module_key, "action": action, "id": record_id,
                              "part_no": part_no, "by": g.user["username"],
                              "by_id": g.user["id"]},
                   admins=True, user_ids=security.users_who_can_view(module_key))


@bp.get("")
@security.login_required()
def list_modules():
    db = get_db()
    counts = {r["module"]: r["c"] for r in db.execute("SELECT module, COUNT(*) c FROM records GROUP BY module")}
    out = []
    for m in current_app.config["MODULES"]:
        level = security.module_level(g.user, m["key"])
        out.append({**m, "level": level, "count": counts.get(m["key"], 0) if level != "none" else None})
    return jsonify(modules=out)


@bp.get("/<key>/records")
@security.login_required()
def list_records(key):
    mod, err = _guard(key, "view")
    if err:
        return err
    q, status = request.args.get("q", "").strip(), request.args.get("status", "").strip()
    sql, args = "SELECT * FROM records WHERE module=?", [key]
    if q:
        sql += " AND (part_no LIKE ? OR description LIKE ? OR notes LIKE ?)"
        args += [f"%{q}%"] * 3
    if status:
        sql += " AND status=?"
        args.append(status)
    rows = get_db().execute(sql + " ORDER BY id DESC", args).fetchall()
    return jsonify(module=mod, level=security.module_level(g.user, key), items=[dict(r) for r in rows])


@bp.post("/<key>/records")
@security.login_required()
def create_record(key):
    mod, err = _guard(key, "edit")
    if err:
        return err
    values, problem = _clean(request.get_json(silent=True) or {})
    if problem:
        return jsonify(error=problem), 400
    now = iso()
    cur = get_db().execute(
        "INSERT INTO records (module,part_no,description,quantity,status,notes,updated_by,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (key, values["part_no"], values["description"], values["quantity"], values["status"],
         values["notes"], g.user["username"], now, now))
    audit.log("record", "RECORD_CREATED", target=f"{mod['name']} / {values['part_no']}",
              details=f"qty {values['quantity']}, status {values['status']}")
    _broadcast(key, "created", cur.lastrowid, values["part_no"])
    row = get_db().execute("SELECT * FROM records WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(item=dict(row)), 201


@bp.put("/<key>/records/<int:rid>")
@security.login_required()
def update_record(key, rid):
    mod, err = _guard(key, "edit")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    values, problem = _clean(data)
    if problem:
        return jsonify(error=problem), 400
    try:
        version = int(data.get("version"))
    except (TypeError, ValueError):
        return jsonify(error="Missing record version. Reload and try again."), 400

    db = get_db()
    old = db.execute("SELECT * FROM records WHERE id=? AND module=?", (rid, key)).fetchone()
    if old is None:
        return jsonify(error="Record no longer exists.", code="GONE"), 404
    changes = [f"{f}: {old[f]} -> {values[f]}" for f in ("part_no", "description", "quantity", "status", "notes")
               if (old[f] or "") != values[f]]
    if not changes and old["version"] == version:
        return jsonify(item=dict(old))

    cur = db.execute(
        "UPDATE records SET part_no=?,description=?,quantity=?,status=?,notes=?,version=version+1,"
        "updated_by=?,updated_at=? WHERE id=? AND module=? AND version=?",
        (values["part_no"], values["description"], values["quantity"], values["status"], values["notes"],
         g.user["username"], iso(), rid, key, version))
    if cur.rowcount == 0:      # optimistic locking: someone saved first
        latest = db.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()
        return jsonify(error=f"{latest['updated_by']} saved changes to this record while you were editing. "
                             "Review the latest values and save again.",
                       code="CONFLICT", item=dict(latest)), 409
    audit.log("record", "RECORD_UPDATED", target=f"{mod['name']} / {values['part_no']}",
              details="; ".join(changes)[:400])
    _broadcast(key, "updated", rid, values["part_no"])
    return jsonify(item=dict(db.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone()))


@bp.delete("/<key>/records/<int:rid>")
@security.login_required()
def delete_record(key, rid):
    mod, err = _guard(key, "edit")
    if err:
        return err
    db = get_db()
    old = db.execute("SELECT * FROM records WHERE id=? AND module=?", (rid, key)).fetchone()
    if old is None:
        return jsonify(error="Record no longer exists.", code="GONE"), 404
    db.execute("DELETE FROM records WHERE id=?", (rid,))
    audit.log("record", "RECORD_DELETED", target=f"{mod['name']} / {old['part_no']}",
              details=old["description"])
    _broadcast(key, "deleted", rid, old["part_no"])
    return jsonify(ok=True)


@bp.get("/<key>/export")
@security.login_required()
def export_records(key):
    mod, err = _guard(key, "view")
    if err:
        return err
    return send_report("records", request.args.get("fmt", "xlsx"), module=key)


def send_report(name, fmt, module=None):
    """Build, audit and send a PDF/Excel report (shared with the admin exports)."""
    if fmt not in ("pdf", "xlsx"):
        return jsonify(error="Format must be pdf or xlsx."), 400
    report = reports.build_report(get_db(), name, module)
    who = f"{g.user['full_name']} ({g.user['username']})"
    buf = reports.to_pdf(report, who) if fmt == "pdf" else reports.to_xlsx(report, who)
    audit.log("export", "REPORT_EXPORTED", target=report["title"], notify=False,
              details=f"{fmt.upper()}, {len(report['rows'])} rows")
    stamp = reports.utcnow().astimezone(reports.local_tz()).strftime("%Y%m%d_%H%M")
    mime = "application/pdf" if fmt == "pdf" else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return send_file(buf, mimetype=mime, as_attachment=True,
                     download_name=f"godrej_bams_{name}{'_' + module if module else ''}_{stamp}.{fmt}")
