"""Shared fixtures for the web tests.

The server keeps process-wide state (the engine, the account database), so the app
is built once per session against a temporary data directory. Individual accounts
are created per test, which is what makes the isolation tests meaningful.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Must be set before web.config is imported
os.environ["PYFA_WEB_DATA_DIR"] = tempfile.mkdtemp(prefix="pyfa-web-tests-")
os.environ["PYFA_WEB_DEV_AUTH_BYPASS"] = "1"
os.environ["PYFA_WEB_LANGUAGE"] = "en_US"
os.environ.pop("PYFA_WEB_SSO_CLIENT_ID", None)
# Same reasoning: a real secret in the environment must not reach a test process.
os.environ.pop("PYFA_WEB_SSO_CLIENT_SECRET", None)

#: ``load_config()`` without an argument reads ``web.yml`` from the repository root.
#: That file is a *deployment* file: it is gitignored and carries the real SSO client
#: id and secret, so a developer's copy would quietly configure SSO inside the test
#: run (a checked-out CI tree has no such file). Point the session app at a path that
#: does not exist instead, which is what CI sees.
ABSENT_CONFIG = Path(tempfile.mkdtemp(prefix="pyfa-web-tests-config-")) / "web.yml"

RIFTER_ID = 587
AUTOCANNON_ID = 2889
EMP_S_ID = 185

_characterIdCounter = {"value": 1_000_000}


def next_character_id():
    _characterIdCounter["value"] += 1
    return _characterIdCounter["value"]


@pytest.fixture(scope="session")
def app():
    from fastapi.testclient import TestClient

    from web.config import load_config
    from web.main import create_app

    application = create_app(load_config(ABSENT_CONFIG))
    # Entering the client once runs startup (lifespan) exactly once
    with TestClient(application):
        yield application


@pytest.fixture(scope="session")
def app_state(app):
    return app.state.pyfaAppState


@pytest.fixture
def client(app):
    """A fresh anonymous client.

    Function scoped on purpose: a session-scoped client would carry cookies from
    whichever test logged in first, which silently un-anonymises later tests.
    """
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def make_user(app_state):
    """Create an account and return a client authenticated as it."""
    from fastapi.testclient import TestClient

    def factory(name="Test Pilot"):
        character_id = next_character_id()
        user = app_state.users.upsert_from_sso(character_id=character_id, character_name=name)
        client = TestClient(app_state_app(app_state))
        client.cookies.set(app_state.config.cookie_name, app_state.tokens.issue(user.id))
        client.pyfaUser = user
        return client

    return factory


def app_state_app(app_state):
    """The FastAPI app behind an AppState (kept on the state for test helpers)."""
    return app_state.app


@pytest.fixture
def user_client(make_user):
    return make_user("Primary Pilot")


@pytest.fixture
def second_user_client(make_user):
    return make_user("Second Pilot")
