"""In-process publish/subscribe broker that feeds Server-Sent Events (SSE).

Every logged-in browser tab holds one open /api/stream connection. Route code
calls broker.publish(...) and the matching subscribers receive the event
instantly - this is what makes the dashboard, activity feed, notification bell
and module tables update live for all users at once.

Note: the broker lives in process memory. Run ONE server process with many
threads (the default for `python app.py` and `waitress`). For multi-process
deployments swap this class for Redis pub/sub.
"""
import itertools
import queue
import threading


class Subscriber:
    __slots__ = ("id", "user_id", "role", "sid", "q")

    def __init__(self, sub_id, user_id, role, sid):
        self.id, self.user_id, self.role, self.sid = sub_id, user_id, role, sid
        self.q = queue.Queue(maxsize=200)


class Broker:
    def __init__(self):
        self._subs = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def subscribe(self, user_id, role, sid):
        sub = Subscriber(next(self._ids), user_id, role, sid)
        with self._lock:
            self._subs[sub.id] = sub
        return sub

    def unsubscribe(self, sub):
        with self._lock:
            self._subs.pop(sub.id, None)

    def publish(self, event, data, *, admins=False, user_ids=None, sid=None):
        """Deliver to admins and/or specific user ids and/or one session id."""
        user_ids = set(user_ids or [])
        with self._lock:
            targets = list(self._subs.values())
        for sub in targets:
            hit = (
                (admins and sub.role == "admin")
                or (sub.user_id in user_ids)
                or (sid is not None and sub.sid == sid)
            )
            if hit:
                try:
                    sub.q.put_nowait({"event": event, "data": data})
                except queue.Full:
                    pass  # slow client: drop rather than block writers

    def connected(self):
        with self._lock:
            return len(self._subs)


broker = Broker()
