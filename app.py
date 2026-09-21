"""Godrej & Boyce - Business Access Management System (Flask application).

Run:   python app.py --demo          (first run with sample users and records)
       python app.py                 (normal run)
"""
import argparse

from flask import Flask, jsonify, request

import security
from config import Config
from db import close_db, init_db
from seed import seed_admin, seed_demo


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    app.teardown_appcontext(close_db)
    app.before_request(security.csrf_protect)
    app.after_request(security.security_headers)

    @app.context_processor
    def inject():
        return {"csrf_token": security.csrf_token(), "app_name": app.config["APP_NAME"],
                "company": app.config["COMPANY"]}

    from routes import admin, auth, modules, pages, stream
    for module in (pages, auth, modules, admin, stream):
        app.register_blueprint(module.bp)

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found."), 404
        return "Page not found.", 404

    @app.errorhandler(405)
    def bad_method(_e):
        return jsonify(error="Method not allowed."), 405

    @app.errorhandler(413)
    def too_large(_e):
        return jsonify(error="Request is too large."), 413

    @app.errorhandler(500)
    def server_error(_e):
        return jsonify(error="Something went wrong on the server."), 500

    init_db(app)
    seed_admin(app)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Godrej BAMS server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--demo", action="store_true", help="load demo users and sample records (first run)")
    args = parser.parse_args()

    application = create_app()
    if args.demo and seed_demo(application):
        print("Demo data loaded. Users: rahul.patil / sneha.kulkarni / amit.deshmukh  (password: User@1234)")
    print(f"Admin login: {application.config['DEFAULT_ADMIN_USER']} / (see README) -> http://{args.host}:{args.port}")
    # threaded=True lets many users (and their live SSE connections) be served at once.
    application.run(host=args.host, port=args.port, threaded=True, debug=False)
