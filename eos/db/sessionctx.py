"""Session resolution for ``eos.db``.

The desktop application has exactly one user, and a single long-lived
``saveddata_session`` bound to one SQLite file. The web application serves many
users, each with their own ``saveddata.db``, and requests for different users can
land on the same worker thread.

Rather than rewriting the ~130 call sites that use ``eos.db.saveddata_session``,
the session is exposed through :class:`SaveddataSessionProxy`. It resolves to the
session of the *current* user via a :mod:`contextvars` variable, falling back to
the process-wide default session (desktop behaviour) when no user is bound.

``sd_lock`` gets the same treatment so that write serialisation is per user
instead of one global bottleneck.
"""

import contextvars
import threading

__all__ = [
    "SessionContext",
    "SaveddataSessionProxy",
    "SessionLockProxy",
    "UnboundSession",
    "NoSessionContextError",
    "get_context",
    "set_default_context",
    "bind_context",
    "current_context",
    "scoped_instance",
]


class NoSessionContextError(RuntimeError):
    """Raised when saveddata is touched without a bound user in web mode."""


class SessionContext:
    """Everything needed to talk to one user's saveddata database."""

    def __init__(self, name, session, lock, engine=None, save_path=None, save_db=None):
        self.name = name
        self.session = session
        self.lock = lock
        self.engine = engine
        # Kept so database migrations can find the file to back up
        self.save_path = save_path
        self.save_db = save_db
        # Singletons that hold per-user engine state (see scoped_instance) live
        # here, so they are released together with the context.
        self.scoped_instances = {}

    def __repr__(self):
        return "<SessionContext {}>".format(self.name)


def scoped_instance(cls, factory):
    """A singleton that is one-per-session-context instead of one-per-process.

    Services such as ``service.fit.Fit`` cache ORM objects belonging to the
    session that created them, so a single shared instance would hand one user's
    character and damage pattern to another. Scoping by context makes that
    impossible; with a single context (the desktop application) this behaves
    exactly like a plain class-level singleton.
    """
    ctx = current_context()
    if ctx is None:
        instance = getattr(cls, "_unscopedInstance", None)
        if instance is None:
            instance = cls._unscopedInstance = factory()
        return instance

    instance = ctx.scoped_instances.get(cls)
    if instance is None:
        instance = ctx.scoped_instances[cls] = factory()
    return instance


_default_context = None
_current_context = contextvars.ContextVar("pyfa_saveddata_context", default=None)


def set_default_context(context):
    """Set the process-wide fallback context (desktop mode, or web startup)."""
    global _default_context
    _default_context = context


def get_default_context():
    return _default_context


def current_context():
    """The context bound to the current execution context, or None."""
    ctx = _current_context.get()
    if ctx is None:
        return _default_context
    return ctx


def get_context():
    ctx = current_context()
    if ctx is None:
        raise NoSessionContextError(
            "No saveddata session is bound to this execution context. "
            "In web mode wrap the work in eos.db.sessionctx.bind_context(user_context)."
        )
    return ctx


class UnboundSession:
    """A session stand-in that fails instead of using the wrong database.

    The web server installs this as the default context. Any code that reaches
    saveddata without a user bound -- typically a legacy background thread, since
    threads do not inherit contextvars -- then raises a clear error rather than
    quietly writing one user's fit into another database.
    """

    def _fail(self):
        raise NoSessionContextError(
            "Saveddata was accessed without a bound user. Background threads do not "
            "inherit the request context: wrap the work in "
            "eos.db.sessionctx.bind_context() or use the dispatcher in web/events.py."
        )

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        self._fail()

    def __contains__(self, instance):
        self._fail()

    def __repr__(self):
        return "<UnboundSession>"


class _ContextScope:
    def __init__(self, context):
        self.context = context
        self.token = None

    def __enter__(self):
        self.token = _current_context.set(self.context)
        return self.context

    def __exit__(self, *exc_info):
        _current_context.reset(self.token)
        self.token = None
        return False


def bind_context(context):
    """Bind ``context`` for the duration of a ``with`` block."""
    return _ContextScope(context)


class SaveddataSessionProxy:
    """Resolves attribute access to the current user's SQLAlchemy session."""

    def _session(self):
        return get_context().session

    def __getattr__(self, name):
        if name.startswith("_") and name.endswith("_"):
            raise AttributeError(name)
        return getattr(self._session(), name)

    def __contains__(self, instance):
        return instance in self._session()

    def __repr__(self):
        try:
            ctx = get_context()
        except NoSessionContextError:
            return "<SaveddataSessionProxy unbound>"
        return "<SaveddataSessionProxy for {}>".format(ctx.name)


class SessionLockProxy:
    """Resolves ``with sd_lock:`` to the current user's re-entrant lock."""

    def __init__(self, fallback=None):
        self._fallback = fallback if fallback is not None else threading.RLock()

    def _lock(self):
        ctx = current_context()
        if ctx is None:
            return self._fallback
        return ctx.lock

    def acquire(self, *args, **kwargs):
        return self._lock().acquire(*args, **kwargs)

    def release(self):
        return self._lock().release()

    def __enter__(self):
        self._lock().acquire()
        return self

    def __exit__(self, *exc_info):
        self._lock().release()
        return False
