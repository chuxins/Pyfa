# ===============================================================================
# Copyright (C) 2010 Diego Duclos
#
# This file is part of eos.
#
# eos is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# eos is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with eos.  If not, see <http://www.gnu.org/licenses/>.
# ===============================================================================

import re
import threading

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.orm import registry, sessionmaker, scoped_session

from . import migration
from . import sessionctx
from eos import config
from logbook import Logger


pyfalog = Logger(__name__)
pyfalog.info("Initializing database")
pyfalog.info("Gamedata connection: {0}", config.gamedata_connectionstring)
pyfalog.info("Saveddata connection: {0}", config.saveddata_connectionstring)


class ReadOnlyException(Exception):
    pass


def re_fn(expr, item):
    try:
        reg = re.compile(expr, re.IGNORECASE)
    except (SystemExit, KeyboardInterrupt):
        raise
    except:
        return False
    return reg.search(item) is not None


pyfalog.debug('Initializing gamedata')
gamedata_connectionstring = config.gamedata_connectionstring
# The web server sets a pool class: its worker threads come and go, and a session
# holds its connection until it is closed, so a fixed-size pool would run dry.
# This is read-only data, so one connection per thread is all that is needed.
gamedata_engine_kwargs = {}
gamedata_pool_class = getattr(config, 'gamedataPoolClass', None)
if gamedata_pool_class is not None:
    gamedata_engine_kwargs['poolclass'] = gamedata_pool_class

if callable(gamedata_connectionstring):
    gamedata_engine = create_engine(
        "sqlite://", creator=gamedata_connectionstring, echo=config.debug, **gamedata_engine_kwargs)
else:
    gamedata_engine = create_engine(gamedata_connectionstring, echo=config.debug, **gamedata_engine_kwargs)


@event.listens_for(gamedata_engine, 'connect')
def create_functions(dbapi_connection, connection_record):
    dbapi_connection.create_function('regexp', 2, re_fn)


gamedata_meta = MetaData()
GamedataSessionMaker = sessionmaker(bind=gamedata_engine, autoflush=False, expire_on_commit=False)
GamedataSession = scoped_session(GamedataSessionMaker)
gamedata_session = GamedataSession()

gamedata_sessions = {threading.get_ident(): gamedata_session}


def get_gamedata_session():
    """One game-data session per thread.

    Deliberately not per request: services cache the objects they load (the market
    browser keeps every item it has looked up), and closing a session detaches
    them, so a per-request session would hand detached objects to the next
    request. The server makes this safe by using an uncapped pool -- see
    ``gamedataPoolClass`` above.
    """
    thread_id = threading.get_ident()
    if thread_id not in gamedata_sessions:
        gamedata_sessions[thread_id] = GamedataSession()
    return gamedata_sessions[thread_id]


pyfalog.debug('Getting gamedata version')
# This should be moved elsewhere, maybe as an actual query. Current, without try-except, it breaks when making a new
# game db because we haven't reached gamedata_meta.create_all()
try:
    config.gamedata_version = gamedata_session.execute(
            text("SELECT `field_value` FROM `metadata` WHERE `field_name` LIKE 'client_build'")
    ).fetchone()[0]
    config.gamedata_date = gamedata_session.execute(
        text("SELECT `field_value` FROM `metadata` WHERE `field_name` LIKE 'dump_time'")
    ).fetchone()[0]
except (KeyboardInterrupt, SystemExit):
    raise
except Exception as e:
    pyfalog.warning("Missing gamedata version.")
    pyfalog.critical(e)
    config.gamedata_version = None
    config.gamedata_date = None

pyfalog.debug('Initializing saveddata')
saveddata_connectionstring = config.saveddata_connectionstring
if saveddata_connectionstring is not None:
    if callable(saveddata_connectionstring):
        saveddata_engine = create_engine(creator=saveddata_connectionstring, echo=config.debug)
    else:
        saveddata_engine = create_engine(saveddata_connectionstring, echo=config.debug)

    saveddata_meta = MetaData()
    # The default session serves the desktop application, which has a single user.
    # The web application binds a per-user session instead; see eos/db/sessionctx.py
    saveddata_session_default = sessionmaker(bind=saveddata_engine, autoflush=False, expire_on_commit=False)()
else:
    saveddata_meta = None

# a "hack" to use legacy schema declaration - now need to go explicitly through registry
mapper_registry = registry()
mapper = mapper_registry.map_imperatively

# Default lock controlling changes introduced to the default (desktop) session.
# Web mode resolves to a per-user lock instead; see eos/db/sessionctx.py
sd_lock_default = threading.RLock()

from eos.db.sessionctx import SessionLockProxy, SessionContext, SaveddataSessionProxy, set_default_context  # noqa: E402

if saveddata_meta is not None:
    set_default_context(SessionContext(
        name='default',
        session=saveddata_session_default,
        lock=sd_lock_default,
        engine=saveddata_engine,
    ))
    saveddata_session = SaveddataSessionProxy()
else:
    saveddata_session = None

sd_lock = SessionLockProxy(fallback=sd_lock_default)

pyfalog.debug('Importing gamedata DB scheme')
# Import all the definitions for all our database stuff
# noinspection PyPep8
from eos.db.gamedata import alphaClones, attribute, category, effect, group, item, marketGroup, metaData, metaGroup, queries, traits, unit, dynamicAttributes, implantSet
pyfalog.debug('Importing saveddata DB scheme')
# noinspection PyPep8
from eos.db.saveddata import booster, cargo, character, damagePattern, databaseRepair, drone, fighter, fit, implant, implantSet, \
    miscData, mutatorMod, mutatorDrone, module, override, price, queries, skill, targetProfile, user

pyfalog.debug('Importing gamedata queries')
# noinspection PyPep8
from eos.db.gamedata.queries import *
pyfalog.debug('Importing saveddata queries')
# noinspection PyPep8
from eos.db.saveddata.queries import *

# If using in memory saveddata, you'll want to reflect it so the data structure is good.
if config.saveddata_connectionstring == "sqlite:///:memory:":
    saveddata_meta.create_all(saveddata_engine)
    pyfalog.info("Running database out of memory.")


def rollback():
    with sd_lock:
        pyfalog.warning("Session rollback triggered.")
        saveddata_session.rollback()
