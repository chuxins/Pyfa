"""Server configuration for the web front end.

Values come from, in increasing order of precedence:

1. built-in defaults
2. ``web.yml`` in the repository root (optional)
3. environment variables prefixed with ``PYFA_WEB_``

The EVE SSO application credentials have to be registered with CCP for the exact
callback URL this server serves; see ``web/docs/web.md``.
"""

import os
import secrets
from dataclasses import dataclass, field, replace
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml is a hard dependency of pyfa itself
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent

# Scopes pyfa itself asks for. Fittings write access is what makes "export fit to
# EVE" work; skills are needed to compute a character's fit accurately.
DEFAULT_SCOPES = (
    "esi-skills.read_skills.v1",
    "esi-fittings.read_fittings.v1",
    "esi-fittings.write_fittings.v1",
)

#: ``web.yml`` keys that map onto :class:`WebConfig` fields, with the
#: ``PYFA_WEB_*`` suffix that overrides each one. ``None`` means the field has no
#: environment variable and can only be set in the file.
SCALAR_FIELDS = {
    "data_dir": "DATA_DIR",
    "host": "HOST",
    "port": "PORT",
    "public_url": "PUBLIC_URL",
    "secret_key": "SECRET_KEY",
    "cookie_name": None,
    "cookie_secure": "COOKIE_SECURE",
    "session_max_age": "SESSION_MAX_AGE",
    "language": "LANGUAGE",
    "log_level": "LOG_LEVEL",
    "dev_auth_bypass": "DEV_AUTH_BYPASS",
}


def _env(name, default=None):
    return os.environ.get("PYFA_WEB_" + name, default)


def _coerce_flag(value):
    """Interpret a ``web.yml``/environment value as a boolean.

    ``bool("false")`` is ``True``, so strings are matched the way ``_env_flag``
    matches them instead of being passed through ``bool()``.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _env_flag(name, default=False):
    raw = _env(name)
    if raw is None:
        return default
    return _coerce_flag(raw)


def _env_int(name, default):
    raw = _env(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class SsoConfig:
    """EVE SSO application settings."""

    server: str = "Tranquility"
    client_id: str = ""
    client_secret: str = ""
    scopes: tuple = DEFAULT_SCOPES
    #: Where the SSO provider sends the user back. Must match the registered app.
    callback_path: str = "/api/auth/callback"

    @property
    def configured(self):
        return bool(self.client_id)


@dataclass
class WebConfig:
    repo_root: Path = REPO_ROOT
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR") or (REPO_ROOT / "webdata")))
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8080))
    #: Base URL the browser reaches this server on; used to build the SSO redirect.
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL", ""))
    #: Signing key for session cookies. Generated on first start and persisted.
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", ""))
    cookie_name: str = "pyfa_session"
    #: Mark the session cookie ``Secure``. ``None`` (the default) means "infer
    #: from ``public_url``"; ``web.yml`` or ``PYFA_WEB_COOKIE_SECURE`` override it.
    cookie_secure: bool | None = field(default_factory=lambda: _env_flag("COOKIE_SECURE", None))
    session_max_age: int = field(default_factory=lambda: _env_int("SESSION_MAX_AGE", 30 * 24 * 3600))
    language: str = field(default_factory=lambda: _env("LANGUAGE", "en_US"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "info"))
    #: Development-only escape hatch: log in as a fixed local user without EVE SSO.
    dev_auth_bypass: bool = field(default_factory=lambda: _env_flag("DEV_AUTH_BYPASS", False))
    #: Set when the frontend is served from a dev server (Vite) rather than the API.
    cors_origins: tuple = field(default_factory=lambda: tuple(
        o.strip() for o in (_env("CORS_ORIGINS", "") or "").split(",") if o.strip()))
    sso: SsoConfig = field(default_factory=SsoConfig)

    # -- derived paths ------------------------------------------------------------------

    @property
    def system_dir(self):
        """Where server-wide state lives (logs, settings for anonymous requests)."""
        return self.data_dir / "system"

    @property
    def users_dir(self):
        return self.data_dir / "users"

    @property
    def app_db_path(self):
        return self.data_dir / "app.db"

    @property
    def imgs_dir(self):
        return self.repo_root / "imgs"

    @property
    def frontend_dist(self):
        return Path(__file__).resolve().parent / "static"

    @property
    def session_cookie_secure(self):
        """Secure flag: explicit configuration wins, otherwise infer from public_url."""
        if self.cookie_secure is not None:
            return bool(self.cookie_secure)
        return self.public_url.startswith("https://")

    def user_dir(self, user_id):
        return self.users_dir / str(user_id)

    def user_db_path(self, user_id):
        return self.user_dir(user_id) / "saveddata.db"

    def callback_url(self):
        base = self.public_url or "http://{}:{}".format(
            "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host, self.port)
        return base.rstrip("/") + self.sso.callback_path

    # -- loading ------------------------------------------------------------------------

    def prepare(self):
        """Create directories and make sure a session signing key exists."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.system_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(parents=True, exist_ok=True)
        if not self.secret_key:
            self.secret_key = self._load_or_create_secret()
        return self

    def _load_or_create_secret(self):
        secret_file = self.data_dir / "session.key"
        if secret_file.is_file():
            return secret_file.read_text(encoding="utf-8").strip()
        value = secrets.token_urlsafe(48)
        secret_file.write_text(value, encoding="utf-8")
        try:
            os.chmod(secret_file, 0o600)
        except OSError:
            pass
        return value


def _yaml_overrides(path):
    if yaml is None or not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_scalar(key, value):
    """Convert one ``web.yml`` value to the type of the field it sets."""
    if key in ("port", "session_max_age"):
        return int(value)
    if key in ("cookie_secure", "dev_auth_bypass"):
        return _coerce_flag(value)
    if key == "data_dir":
        return Path(value)
    return value


def _scope_tuple(value):
    """SSO scopes as a tuple; accepts a YAML list or a whitespace separated string.

    A bare string used to be iterated character by character, which turned a
    perfectly reasonable ``scopes: esi-skills.read_skills.v1`` into a tuple of
    single letters.
    """
    if isinstance(value, str):
        return tuple(value.split())
    return tuple(str(scope).strip() for scope in value if str(scope).strip())


def load_config(path=None):
    """Build a :class:`WebConfig` from defaults, ``web.yml`` and the environment.

    Precedence, lowest first: built-in defaults, ``web.yml``, and ``PYFA_WEB_*``
    environment variables -- so a deployment can override whatever a checked-in
    file happens to say.
    """
    config = WebConfig()
    overrides = _yaml_overrides(Path(path) if path else REPO_ROOT / "web.yml")

    sso_data = overrides.pop("sso", None) or {}
    for key, value in overrides.items():
        if key not in SCALAR_FIELDS:
            continue
        env_name = SCALAR_FIELDS[key]
        if env_name and _env(env_name) is not None:
            continue  # the environment wins over the file
        setattr(config, key, _coerce_scalar(key, value))

    sso_kwargs = {}
    for key in ("server", "client_id", "client_secret", "callback_path"):
        if key in sso_data:
            sso_kwargs[key] = sso_data[key]
    if "scopes" in sso_data:
        sso_kwargs["scopes"] = _scope_tuple(sso_data["scopes"])
    # Environment always wins over the file, so deployments can inject credentials
    for key, env_name in (
        ("server", "SSO_SERVER"),
        ("client_id", "SSO_CLIENT_ID"),
        ("client_secret", "SSO_CLIENT_SECRET"),
        ("callback_path", "SSO_CALLBACK_PATH"),
    ):
        value = _env(env_name)
        if value:
            sso_kwargs[key] = value
    scopes = _env("SSO_SCOPES")
    if scopes:
        sso_kwargs["scopes"] = tuple(s.strip() for s in scopes.split() if s.strip())

    config.sso = replace(SsoConfig(), **sso_kwargs)

    # The language has to be handed to eos now: it binds item names to one of eve.db's
    # language columns when its gamedata models are first imported, and the next import
    # that reaches into eos.db (web.main, web.deps, service.market, ...) is one of those
    # moments. This is why the entry point loads the config before importing web.main.
    # See web.engine.apply_gamedata_language.
    from web import engine

    engine.apply_gamedata_language(config.language)

    return config
