"""HTML pages: welcome, login and the authenticated application shell."""
from flask import Blueprint, redirect, render_template, request, url_for

from security import login_required, resolve_session

bp = Blueprint("pages", __name__)


@bp.get("/")
def welcome():
    user, _ = resolve_session(touch=False)
    return render_template("welcome.html", signed_in=bool(user), user=user)


@bp.get("/login")
def login():
    user, _ = resolve_session(touch=False)
    if user:
        return redirect(url_for("pages.app_shell"))
    login_type = request.args.get("type", "user")
    return render_template("login.html",
                           login_type="admin" if login_type == "admin" else "user",
                           reason=request.args.get("reason", ""))


@bp.get("/app")
@login_required(allow_pw_change=True)
def app_shell():
    return render_template("app.html")


@bp.get("/healthz")
def healthz():
    return {"status": "ok"}
