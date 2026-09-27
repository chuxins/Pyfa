"""Cross-thread work dispatch and server-sent events.

pyfa is written for a GUI: background threads finish by calling ``wx.CallAfter``
to hand work back to the widget thread, and mutations raise ``wx.PostEvent`` so
the UI refreshes. Neither exists in a server process, so both are redirected here:

* :class:`Dispatcher` is the "GUI thread" -- one worker thread that runs
  callbacks *with the context they were submitted from*, so a callback queued by
  a request still sees that user's database session.
* :class:`EventBus` fans "something changed" out to the browser over SSE, which
  is what makes a second tab (or the same fit open twice) stay in sync.
"""

import asyncio
import contextvars
import queue
import threading
from contextlib import contextmanager

from logbook import Logger

pyfalog = Logger(__name__)

#: Which account's browsers a wx.PostEvent should be forwarded to. Set while a
#: request (or a dispatched callback) is running, so that pyfa's own fit commands
#: -- which know nothing about users -- still notify the right one.
_publishingUser = contextvars.ContextVar("pyfa_publishing_user", default=None)


@contextmanager
def publishing_as(user_id):
    token = _publishingUser.set(user_id)
    try:
        yield
    finally:
        _publishingUser.reset(token)


class Dispatcher:
    """Single worker thread that mimics wx's GUI thread."""

    def __init__(self, name="pyfa-dispatch"):
        self._queue = queue.Queue()
        self._thread = None
        self._name = name
        self._running = False

    def start(self):
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._queue.put(None)

    def submit(self, func, args=(), kwargs=None):
        """Queue ``func`` to run on the dispatcher thread, with the caller's context."""
        if not self._running:
            self.start()
        ctx = contextvars.copy_context()
        self._queue.put((ctx, func, args, kwargs or {}))

    def _run(self):
        from logbook import Logger as _Logger

        log = _Logger(__name__)
        while True:
            item = self._queue.get()
            if item is None or not self._running:
                break
            ctx, func, args, kwargs = item
            try:
                ctx.run(func, *args, **kwargs)
            except Exception:
                log.exception("Error running dispatched callback {}", getattr(func, "__qualname__", func))
            finally:
                self._queue.task_done()
        log.debug("Dispatcher thread stopped")


class EventBus:
    """Publishes events to browser subscribers, one queue per connection."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = {}  # user_id -> set of asyncio.Queue
        self._loop = None

    def bind_loop(self, loop):
        self._loop = loop

    def subscribe(self, user_id):
        q = asyncio.Queue(maxsize=128)
        with self._lock:
            self._subscribers.setdefault(user_id, set()).add(q)
        return q

    def unsubscribe(self, user_id, q):
        with self._lock:
            queues = self._subscribers.get(user_id)
            if not queues:
                return
            queues.discard(q)
            if not queues:
                del self._subscribers[user_id]

    def subscriber_count(self, user_id=None):
        with self._lock:
            if user_id is None:
                return sum(len(qs) for qs in self._subscribers.values())
            return len(self._subscribers.get(user_id, ()))

    def publish(self, user_id, event):
        """Thread-safe publish to everyone watching ``user_id``."""
        with self._lock:
            targets = list(self._subscribers.get(user_id, ()))
        loop = self._loop
        for q in targets:
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(self._offer, q, event)
                except RuntimeError:  # loop shutting down
                    pass
            else:  # pragma: no cover - only before startup / in tests
                self._offer(q, event)

    @staticmethod
    def _offer(q, event):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # A slow browser is better off missing an event than blocking a request;
            # it will re-fetch on the next event or on reconnect.
            pyfalog.warning("Dropped event for slow SSE subscriber: {}", event.get("type"))


#: Process-wide singletons
dispatcher = Dispatcher()
bus = EventBus()


def publish(user_id, event_type, **payload):
    """Notify a user's browsers that something changed."""
    event = dict(payload)
    event["type"] = event_type
    bus.publish(user_id, event)


def install_hooks():
    """Redirect wx's thread marshalling into our dispatcher."""
    from pyfa_compat import wx_headless

    dispatcher.start()
    wx_headless.set_call_after_hook(lambda func, args, kwargs: dispatcher.submit(func, args, kwargs))
    wx_headless.set_post_event_hook(_on_post_event)
    pyfalog.debug("Installed headless event hooks")


def _on_post_event(dest, event):
    """Translate a wx event posted by a fit command into an SSE notification."""
    user_id = _publishingUser.get()
    if user_id is None:
        # Nothing is watching: a startup path or a background job without a user
        return True

    name = type(event).__name__
    if name == "FitChanged":
        publish(user_id, "fit.changed",
                fitIds=[f for f in (getattr(event, "fitIDs", None) or [])],
                action=getattr(event, "action", None),
                typeId=getattr(event, "typeID", None))
    elif name == "FitRemoved":
        publish(user_id, "fit.removed", fitIds=[f for f in (getattr(event, "fitIDs", None) or [])])
    elif name == "FitRenamed":
        publish(user_id, "fit.renamed", fitId=getattr(event, "fitID", None))
    elif name in ("CharListUpdated", "CharChanged"):
        publish(user_id, "character.changed")
    else:
        publish(user_id, "event", name=name)
    return True


__all__ = [
    "dispatcher",
    "bus",
    "publish",
    "install_hooks",
    "publishing_as",
    "Dispatcher",
    "EventBus",
]
