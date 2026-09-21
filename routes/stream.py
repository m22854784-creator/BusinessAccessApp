"""Server-Sent Events endpoint: one long-lived connection per open browser tab."""
import json
import queue

from flask import Blueprint, Response, current_app, g, stream_with_context

import security
from db import get_db
from realtime import broker

bp = Blueprint("stream", __name__, url_prefix="/api")
HEARTBEAT_SECONDS = 15


def _frame(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@bp.get("/stream")
@security.login_required(touch=False, allow_pw_change=True)
def stream():
    user, sid, session_id = g.user, g.sid, g.session_id
    sub = broker.subscribe(user["id"], user["role"], sid)

    def generate():
        try:
            yield "retry: 3000\n\n"
            yield _frame("hello", {"ok": True})
            while True:
                try:
                    msg = sub.q.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    # Heartbeat: keeps proxies open and lets us notice an expired/ended session.
                    security.reap_expired_sessions()
                    row = get_db().execute("SELECT active, ended_reason FROM sessions WHERE id=?",
                                           (session_id,)).fetchone()
                    if row is None or not row["active"]:
                        reason = {"timeout": "timeout", "terminated": "terminated",
                                  "disabled": "terminated"}.get(row["ended_reason"] if row else None, "ended")
                        yield _frame("force_logout", {"reason": reason})
                        return
                    yield ": ping\n\n"
                    continue
                yield _frame(msg["event"], msg["data"])
                if msg["event"] == "force_logout":
                    return
        finally:
            broker.unsubscribe(sub)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
