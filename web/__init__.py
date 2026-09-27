"""Web front end for pyfa.

This package runs pyfa's fitting engine (``eos/``) and the command layer
(``gui/fitCommands/calc/``) behind a FastAPI server, so several users can each
keep their own set of fits in the browser.

Layering:

* :mod:`web.engine` -- one-time headless bootstrap of pyfa's engine
* :mod:`web.config` -- server configuration (env vars and ``web.yml``)
* :mod:`web.userdb` -- the account database (who is allowed in)
* :mod:`web.userdata` -- one SQLite file + SQLAlchemy session per user
* :mod:`web.admin` -- operator commands over those accounts and files
* :mod:`web.events` -- pushes "something changed" to the browser over SSE
* :mod:`web.auth` -- EVE SSO login and session cookies
* :mod:`web.api` -- the JSON API

Importing this package also swaps in the headless wx compatibility layer, because
pyfa's own modules (``config``, ``service.*``) import ``wx`` at module scope and
must never bind to a real wxPython installation on a server. Doing it here means
it happens before any of them can be imported, whatever the entry point.
"""

from pyfa_compat import install as _install_headless_wx

_install_headless_wx(force=True)

# pyfa caches query results in process-wide dictionaries keyed by the arguments
# only. On a server that means ``getFit(1)`` would hand user A's fit to user B, and
# the gamedata cache cannot key on list arguments at all. Both caches are decided
# when eos.db is first imported, so this has to happen before that import -- hence
# here, in the package initialiser, rather than in web.engine.
import eos.config as _eosConfig  # noqa: E402
from sqlalchemy.pool import NullPool as _NullPool  # noqa: E402

_eosConfig.gamedataCache = False
_eosConfig.saveddataCache = False
# Game-data reads keep one session (and so one connection) per worker thread for
# as long as the thread lives. A fixed pool would be exhausted by a busy server,
# and the data is read-only, so let each thread hold its own connection.
_eosConfig.gamedataPoolClass = _NullPool

__version__ = "0.1.0"
