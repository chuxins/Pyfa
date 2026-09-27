"""Per-user state: one SQLite file, one engine, one session, one write lock.

Isolation model
---------------

Every user owns ``<data dir>/users/<user id>/saveddata.db``. That file is exactly
the database the desktop application uses, so all of pyfa's schema, migrations,
damage patterns, characters and fits work untouched -- and a user can copy their
desktop ``saveddata.db`` in to keep their fittings.

A :class:`UserData` bundles the engine, the session and a lock. Requests for the
same user are serialised on that lock, which makes the (thread-unsafe)
SQLAlchemy session safe to reuse. Different users run fully in parallel.

Sessions live for as long as the user is active and are evicted after an idle
period, so an idle server does not hold hundreds of open SQLite files.
"""

import asyncio
import os
import shutil
import threading
import time

from logbook import Logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from eos.db import sessionctx
from web.config import WebConfig

pyfalog = Logger(__name__)


class UserData:
    """Runtime resources for one user."""

    def __init__(self, user_id, director, db_path):
        self.user_id = user_id
        self.directory = director
        self.db_path = db_path
        self.engine = None
        self.session = None
        self.context = None
        #: Guards engine calls from inside a single thread (this is what eos.db's
        #: ``sd_lock`` resolves to). A threading lock cannot be handed between
        #: threads, so request-level serialisation uses ``async_lock`` instead.
        self.lock = threading.RLock()
        #: Serialises this user's requests: one at a time, everyone else queues.
        self.async_lock = asyncio.Lock()
        self.last_used = time.monotonic()
        #: fitID -> CommandProcessor, the undo/redo stack of that fit for this user.
        #: Kept per user because pyfa's own Fit.processors dict is keyed by fit id
        #: alone, and fit ids restart for every user's database.
        self.command_processors = {}

    # -- lifecycle ----------------------------------------------------------------------

    def open(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        url = "sqlite:///" + str(self.db_path).replace("\\", "/")
        self.engine = create_engine(
            url,
            echo=False,
            future=True,
            connect_args={"timeout": 30, "check_same_thread": False},
        )
        _configure_sqlite(self.engine)
        self._create_or_migrate()
        self.session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False)()
        self.context = sessionctx.SessionContext(
            name="user-{}".format(self.user_id),
            session=self.session,
            lock=self.lock,
            engine=self.engine,
            save_path=str(self.directory),
            save_db=str(self.db_path),
        )
        return self

    def _create_or_migrate(self):
        # Imported lazily: eos.db pulls in the whole schema, which only makes sense
        # once the engine layer is up.
        import eos.db
        from eos.db import migration

        isNew = not self.db_path.is_file() or self.db_path.stat().st_size == 0
        eos.db.saveddata_meta.create_all(self.engine)
        if isNew:
            with self.engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA user_version = {}".format(migration.getAppVersion()))
            pyfalog.info("Created saveddata for user {} at {}", self.user_id, self.db_path)
            return

        # Existing database (upgraded from the desktop app, or from an older release)
        with self.engine.connect() as connection:
            version = connection.exec_driver_sql("PRAGMA user_version").scalar()
        if version != migration.getAppVersion():
            pyfalog.info("Migrating saveddata for user {} (version {} -> {})",
                         self.user_id, version, migration.getAppVersion())
            migration.update(self.engine, savePath=str(self.directory), saveDB=str(self.db_path))

    def close(self):
        try:
            if self.session is not None:
                self.session.remove() if hasattr(self.session, "remove") else self.session.close()
        except Exception as ex:  # pragma: no cover - best effort
            pyfalog.warning("Error closing session for user {}: {}", self.user_id, ex)
        try:
            if self.engine is not None:
                self.engine.dispose()
        except Exception as ex:  # pragma: no cover - best effort
            pyfalog.warning("Error disposing engine for user {}: {}", self.user_id, ex)
        self.session = None
        self.engine = None
        self.context = None

    def touch(self):
        self.last_used = time.monotonic()

    def commit(self):
        if self.session is not None:
            self.session.commit()

    def rollback(self):
        if self.session is not None:
            self.session.rollback()

    def __repr__(self):
        return "<UserData {}>".format(self.user_id)


def _configure_sqlite(engine):
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        # WAL keeps a background reader (SSE, stats polling) from blocking writes
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


class Session:
    """A bound user context: ``with registry.acquire(user) as user_data:``.

    Binding does three things: it serialises the user's requests on their lock, it
    points ``eos.db`` at their session, and it exposes the path for their settings
    files. Everything the engine touches while the block runs belongs to that user.
    """

    def __init__(self, registry, user_id):
        self.registry = registry
        self.user_id = user_id
        self.data = None

    def __enter__(self):
        self.data = self.registry.get(self.user_id)
        self.data.lock.acquire()
        self._context_scope = sessionctx.bind_context(self.data.context)
        self._context_scope.__enter__()
        return self.data

    def __exit__(self, *exc_info):
        self._context_scope.__exit__(*exc_info)
        self.data.touch()
        self.data.lock.release()
        return False


class UserDataRegistry:
    """Lazily opens, caches and evicts per-user databases."""

    def __init__(self, config: WebConfig, idle_timeout=1800):
        self.config = config
        self.idle_timeout = idle_timeout
        self._lock = threading.RLock()
        self._users = {}
        #: Bound for requests that are not authenticated (see web/deps.py)
        self.guest = None

    def acquire(self, user_id):
        return Session(self, user_id)

    def get(self, user_id):
        with self._lock:
            data = self._users.get(user_id)
            if data is None:
                data = UserData(user_id, self.config.user_dir(user_id), self.config.user_db_path(user_id))
                data.open()
                self._users[user_id] = data
            data.touch()
            return data

    def get_guest(self):
        """The context used for unauthenticated requests.

        Reads of static game data do not need a user, but parts of the service
        layer still touch saveddata (cached item lookups, recently-used lists), so
        they get a scratch database of their own instead of failing.
        """
        with self._lock:
            if self.guest is None:
                directory = self.config.system_dir / "guest"
                self.guest = UserData("guest", directory, directory / "saveddata.db").open()
            return self.guest

    def evict_idle(self, now=None):
        now = now or time.monotonic()
        evicted = []
        with self._lock:
            for user_id, data in list(self._users.items()):
                if now - data.last_used < self.idle_timeout:
                    continue
                if data.async_lock.locked():
                    continue  # someone is still working
                data.close()
                del self._users[user_id]
                evicted.append(user_id)
        if evicted:
            pyfalog.info("Closed idle user databases: {}", evicted)
        return evicted

    def close_all(self):
        with self._lock:
            for data in self._users.values():
                data.close()
            self._users.clear()
            if self.guest is not None:
                self.guest.close()
                self.guest = None

    def user_ids(self):
        with self._lock:
            return list(self._users)

    def close_user(self, user_id):
        """Close one user's cached session, if it is open. True when it was."""
        with self._lock:
            data = self._users.pop(user_id, None)
        if data is None:
            return False
        data.close()
        return True

    def delete_user_data(self, user_id):
        """Remove a user's database and settings from the server.

        Close first, delete after: SQLite -- and Windows in particular -- will not
        remove a database file that is still open, so leaving the session open
        would silently keep the data around.
        """
        self.close_user(user_id)
        directory = self.config.user_dir(user_id)
        if not directory.exists():
            return
        try:
            shutil.rmtree(str(directory))
        except OSError as ex:
            pyfalog.warning("Could not fully delete {}: {}", directory, ex)


def migrate_desktop_database(source_db, user_id, config: WebConfig):
    """Adopt an existing desktop ``saveddata.db`` as a web user's database.

    Called from ``python -m web.admin import-db``. The copy is opened here, which
    also migrates it if the desktop ran an older pyfa, so a damaged file fails on
    the operator's terminal instead of on the user's next request. The caller owns
    the returned :class:`UserData` and has to ``close()`` it.
    """
    target_dir = config.user_dir(user_id)
    target = config.user_db_path(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError("user {} already has a saveddata.db".format(user_id))
    shutil.copyfile(str(source_db), str(target))
    data = UserData(user_id, target_dir, target).open()
    return data


def database_files(directory):
    """The SQLite files of a user directory: the database plus its WAL sidecars."""
    if not directory.exists():
        return []
    return [directory / name for name in os.listdir(directory)
            if name.endswith((".db", ".db-wal", ".db-shm"))]


def count_fits(user_data):
    """Number of fits in a user's database (``python -m web.admin list --fits``)."""
    if user_data.session is None:
        return 0
    return user_data.session.execute(text("SELECT COUNT(*) FROM fits")).scalar()
