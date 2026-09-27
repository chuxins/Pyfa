"""The account database: who is allowed in, and who they are in EVE.

This is deliberately separate from pyfa's ``saveddata.db``. ``app.db`` holds
identities and is shared by the server; every user's fits, skills and characters
live in their own ``saveddata.db`` (see :mod:`web.userdata`).

With EVE SSO as the only login method, a user *is* an EVE character. The account
row exists so that we can (a) find the user's data directory and (b) keep the
profile fresh on each login.
"""

import datetime
import threading

from sqlalchemy import DateTime, Integer, String, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from logbook import Logger

pyfalog = Logger(__name__)


def utcnow():
    """Naive UTC timestamp, matching what the datetime columns store."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: EVE character ID from the SSO ``sub`` claim
    character_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    character_name: Mapped[str] = mapped_column(String(255))
    #: ``owner`` claim; changes when the character is transferred to another account
    owner_hash: Mapped[str] = mapped_column(String(255), default="")
    corporation_id: Mapped[int] = mapped_column(Integer, default=0)
    scopes: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    #: Set when an admin wants to lock the account out without deleting its fits
    disabled: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def is_disabled(self):
        return bool(self.disabled)

    def __repr__(self):
        return "<User {} {}>".format(self.id, self.character_name)


class UserStore:
    """Short-lived sessions over ``app.db``.

    Every request opens its own session: the engine is used from FastAPI's
    thread pool, and long-lived sessions shared across threads are a classic
    source of corruption. WAL plus a busy timeout keeps concurrent writes cheap.
    """

    def __init__(self, db_path):
        self.db_path = db_path
        url = "sqlite:///" + str(db_path).replace("\\", "/")
        self.engine = create_engine(url, echo=False, future=True, connect_args={"timeout": 30})
        self._sessionmaker = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self._lock = threading.Lock()
        self._register_pragmas()
        self.create_all()

    def _register_pragmas(self):
        @event.listens_for(self.engine, "connect")
        def _set_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA busy_timeout = 30000")
            cursor.close()

    def create_all(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)

    def session(self):
        return self._sessionmaker()

    def get(self, user_id):
        with self.session() as session:
            return session.get(User, user_id)

    def get_by_character_id(self, character_id):
        with self.session() as session:
            return session.scalars(
                select(User).where(User.character_id == int(character_id))).first()

    def list_users(self):
        """Every account, ordered by name (used by ``python -m web.admin list``)."""
        with self.session() as session:
            return list(session.scalars(select(User).order_by(User.character_name)))

    def upsert_from_sso(self, character_id, character_name, owner_hash="", scopes="", corporation_id=0):
        """Create or refresh the account row for an EVE character."""
        character_id = int(character_id)
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        with self._lock, self.session() as session:
            user = session.scalars(select(User).where(User.character_id == character_id)).first()
            if user is None:
                user = User(
                    character_id=character_id,
                    character_name=character_name,
                    owner_hash=owner_hash,
                    scopes=scopes,
                    corporation_id=corporation_id,
                    created_at=now,
                    last_login_at=now,
                )
                session.add(user)
                pyfalog.info("Registered new user {} ({})", character_name, character_id)
            else:
                user.character_name = character_name
                if owner_hash:
                    user.owner_hash = owner_hash
                user.scopes = scopes or user.scopes
                user.corporation_id = corporation_id or user.corporation_id
                user.last_login_at = now
            session.commit()
            session.refresh(user)
            session.expunge(user)
            return user

    def set_disabled(self, user_id, disabled):
        """Lock an account out without deleting its fits (``python -m web.admin``).

        The account row is checked on every request, so this takes effect at once;
        the user's own database and fits are left alone.
        """
        with self._lock, self.session() as session:
            user = session.get(User, user_id)
            if user is None:
                return False
            user.disabled = 1 if disabled else 0
            session.commit()
            return True

