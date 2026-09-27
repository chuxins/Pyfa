"""One-time bootstrap that brings pyfa's engine up without a GUI.

The desktop entry point (``pyfa.py``) creates a ``wx.App``, a ``MainFrame`` and
then lets the UI drive the engine. The web server needs the same engine but none
of the widgets, so this module does the equivalent setup explicitly:

1. install the headless wx compatibility layer (never the real one -- the web
   server must not create a GUI event loop, and the shim is what routes
   ``CallAfter``/``PostEvent`` into our dispatcher)
2. make sure ``eve.db`` (EVE static data) exists, building it from
   ``staticdata/`` if needed
3. choose the language eve.db's translated columns are read in (item names and the
   like), which has to happen before anything imports the gamedata models
4. point pyfa's config at the server's data directory
5. configure pyfa's global settings to resolve per user
6. import ``eos.db`` and create the server-wide saveddata tables

Everything here is process-wide and idempotent; per-user state lives in
:mod:`web.userdata`.
"""

import os
import sys
import threading
from pathlib import Path

from logbook import Logger

pyfalog = Logger(__name__)

_lock = threading.Lock()
_initialized = False
_web_config = None

#: eve.db column suffix (``_zh``) that the gamedata models were loaded with, when the
#: language was chosen in time. ``None`` means it was chosen too late.
_gamedata_language = None


class EngineStartupError(RuntimeError):
    pass


def repo_root():
    return Path(__file__).resolve().parent.parent


def _ensure_repo_on_path():
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def _install_headless_wx():
    from pyfa_compat import install

    installed = install(force=True)
    if not installed:
        raise EngineStartupError("failed to install the headless wx compatibility layer")
    return sys.modules["wx"]


def _ensure_gamedata(root):
    """Build ``eve.db`` from the checked-in static data when it is missing or stale."""
    import db_update

    dbPath = Path(db_update.DB_PATH)
    try:
        needsUpdate = db_update.db_needs_update()
    except Exception as ex:  # pragma: no cover - defensive
        pyfalog.warning("Could not check gamedata version: {}", ex)
        needsUpdate = not dbPath.is_file()

    if needsUpdate is True:
        pyfalog.info("Building EVE static data database (eve.db) from staticdata/, this can take a minute")
        db_update.update_db()
        pyfalog.info("EVE static data database ready: {}", dbPath)
    elif needsUpdate is None:
        if not dbPath.is_file():
            raise EngineStartupError(
                "eve.db is missing and staticdata/ is not available, so the engine has no game data. "
                "Provide staticdata/ or drop an eve.db next to pyfa.py."
            )
        pyfalog.warning("Could not verify gamedata version, using existing eve.db")
    return dbPath


def gamedata_language(language):
    """Which of eve.db's translated columns a pyfa language code selects.

    ``eve.db`` keeps one column per language (``typeName`` for English,
    ``typeName_zh`` for Chinese, and so on) and ``eos.config.set_lang`` maps pyfa's
    short codes onto those column suffixes. Languages pyfa has no columns for --
    everything but en, fr, ja, ko, ru and zh -- fall back to English names, which is
    what the desktop client does too.

    Returns the *short* code (``zh``); the suffix (``_zh``) is what lands in
    ``eos.config.lang``.
    """
    import eos.config

    i18n_lang = (language or "").split("_")[0]
    return i18n_lang if i18n_lang in eos.config.translation_mapping else "en"


def apply_gamedata_language(language):
    """Pick the language item names are read in. Safe to call more than once.

    ``Item.name`` and, say, ``Group.displayName`` are synonyms that are bound to one of
    eve.db's language columns *when the gamedata models are imported*, so the choice has
    to be in place before that import. Two things make the timing fiddly: pyfa's
    settings layer pulls those models in from inside ``config.defPaths()``, and
    ``defPaths`` ends by setting ``eos.config.lang`` from pyfa's *desktop* locale
    setting, which a server never has.

    So this runs as soon as the config exists -- from :func:`web.config.load_config`,
    which the entry point imports before ``web.main`` precisely because importing
    ``web.main`` reaches into ``eos.db`` -- and again from :func:`initialize`, both
    before and after ``defPaths``. Once the models are loaded the columns are set in
    stone, so the late case says so rather than pretending it worked.
    """
    global _gamedata_language

    import eos.config

    i18n_lang = gamedata_language(language)
    suffix = eos.config.translation_mapping[i18n_lang]
    modelsLoaded = "eos.db.gamedata.item" in sys.modules

    if _gamedata_language is None and modelsLoaded and eos.config.lang != suffix:
        pyfalog.warning(
            "Game data language {!r} was chosen after eos loaded its gamedata models, so "
            "item names stay in whatever language those were loaded with", language)

    _gamedata_language = suffix
    eos.config.set_lang(i18n_lang)
    pyfalog.debug("Game data language {!r} (eve.db column suffix {!r})", language, eos.config.lang)
    return eos.config.lang


def _bootstrap_config(web_config):
    """Load pyfa's own configuration, with per-user settings resolution enabled."""
    import config as pyfaConfig
    from service.settings import SettingsProvider

    pyfaConfig.debug = False
    pyfaConfig.loggingLevel = pyfaConfig.LOGLEVEL_MAP.get(
        (web_config.log_level or "info").lower(), pyfaConfig.LOGLEVEL_MAP["info"])
    pyfaConfig.language = web_config.language

    # Settings must resolve per requesting user. This has to be in place *before*
    # config.defPaths(), because defPaths instantiates the settings singletons
    # (EOSSettings, LocaleSettings) and they would otherwise cache a single
    # process-wide settings object.
    SettingsProvider.basePathResolver = _settings_base_path

    pyfaConfig.defPaths(customSavePath=str(web_config.system_dir))
    pyfaConfig.defLogging()

    # defPaths just derived the gamedata language from pyfa's *desktop* locale
    # setting (which the web server never sets); the server's language wins.
    apply_gamedata_language(web_config.language)

    wx = sys.modules["wx"]
    configure = getattr(wx, "configure_i18n", None)
    if configure is not None:
        configure(locale_dir=os.path.join(pyfaConfig.pyfaPath, "locale"), language=web_config.language)

    return pyfaConfig


def _settings_base_path():
    """Where the settings file of the current user lives."""
    from eos.db import sessionctx

    ctx = sessionctx.current_context()
    if ctx is not None and ctx.save_path:
        return os.path.join(ctx.save_path, "settings")
    return os.path.join(str(_web_config.system_dir), "settings")


def _init_saveddata(web_config):
    """Bring up ``eos.db`` and neutralise its process-wide default session.

    ``eos.db`` insists on one default saveddata session. The web server never uses
    it: requests bind their own user's context. Replacing it with a guard means a
    code path that forgot to bind fails loudly instead of writing into a shared
    database.
    """
    import threading

    import eos.db
    from eos.db import sessionctx

    sessionctx.set_default_context(sessionctx.SessionContext(
        name="unbound",
        session=sessionctx.UnboundSession(),
        lock=threading.RLock(),
        engine=None,
        save_path=str(web_config.system_dir),
    ))
    return eos.db


def initialize(web_config):
    """Bring the engine up. Safe to call more than once."""
    global _initialized, _web_config

    with _lock:
        if _initialized:
            return _web_config

        _web_config = web_config
        root = _ensure_repo_on_path()
        _install_headless_wx()
        web_config.prepare()
        apply_gamedata_language(web_config.language)
        _ensure_gamedata(root)
        _bootstrap_config(web_config)
        _init_saveddata(web_config)

        from web import events

        events.install_hooks()

        _initialized = True
        pyfalog.info("pyfa web engine initialised (data dir: {})", web_config.data_dir)
        return web_config


def is_initialized():
    return _initialized


def get_config():
    return _web_config
