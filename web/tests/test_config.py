"""Configuration tests.

``web.yml`` and the environment overlap, so what these pin down is precedence and
the one setting whose *absence* carries meaning: ``cookie_secure`` is inferred
from ``public_url`` unless it is set explicitly. The command line sits above both
(``_cli_overrides``), so the flags are checked here too.
"""

import os

import pytest

from web.config import load_config


@pytest.fixture
def no_env(monkeypatch):
    """Drop the PYFA_WEB_* variables the test session sets, so defaults show."""
    for name in list(os.environ):
        if name.startswith("PYFA_WEB_"):
            monkeypatch.delenv(name)


def write_yaml(tmp_path, text):
    path = tmp_path / "web.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_missing_file_is_fine(tmp_path, no_env):
    config = load_config(tmp_path / "does-not-exist.yml")
    assert config.cookie_secure is None
    assert config.session_cookie_secure is False


def test_the_test_app_ignores_a_deployers_web_yml(app_state):
    """The server tests run with defaults, never with the machine's own ``web.yml``.

    ``load_config()`` without an argument reads ``web.yml`` from the repository root,
    and that file is gitignored precisely because it carries the real SSO client id
    and secret. A suite that picked it up would quietly configure live SSO for a
    client id registered against somebody else's host -- so the session app is built
    from a path that does not exist, which is what a CI checkout looks like. The
    environment still applies, which is how the tests log in at all.
    """
    assert app_state.config.public_url == ""
    assert app_state.config.sso.configured is False
    assert app_state.config.dev_auth_bypass is True


def test_secure_cookie_is_inferred_from_the_public_url(tmp_path, no_env):
    path = write_yaml(tmp_path, "public_url: https://pyfa.example.com\n")
    assert load_config(path).session_cookie_secure is True


def test_plain_http_public_url_leaves_the_cookie_insecure(tmp_path, no_env):
    path = write_yaml(tmp_path, "public_url: http://pyfa.example.com\n")
    assert load_config(path).session_cookie_secure is False


def test_the_file_can_override_the_inference(tmp_path, no_env):
    path = write_yaml(tmp_path, "public_url: https://pyfa.example.com\ncookie_secure: false\n")
    assert load_config(path).session_cookie_secure is False


def test_a_quoted_false_is_still_false(tmp_path, no_env):
    path = write_yaml(tmp_path, 'public_url: https://pyfa.example.com\ncookie_secure: "false"\n')
    assert load_config(path).session_cookie_secure is False


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch, no_env):
    path = write_yaml(tmp_path, "host: 0.0.0.0\ncookie_secure: false\n")
    monkeypatch.setenv("PYFA_WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("PYFA_WEB_COOKIE_SECURE", "true")

    config = load_config(path)
    assert config.host == "127.0.0.1"
    assert config.session_cookie_secure is True


def test_sso_settings_come_from_the_file(tmp_path, no_env):
    path = write_yaml(tmp_path, (
        "sso:\n"
        "  client_id: an-app\n"
        "  client_secret: a-secret\n"
        "  scopes: esi-skills.read_skills.v1 esi-fittings.read_fittings.v1\n"
    ))

    config = load_config(path)
    assert config.sso.configured is True
    assert config.sso.client_secret == "a-secret"
    # A bare string used to be iterated character by character
    assert config.sso.scopes == ("esi-skills.read_skills.v1", "esi-fittings.read_fittings.v1")


def test_sso_scopes_can_be_a_list(tmp_path, no_env):
    path = write_yaml(tmp_path, (
        "sso:\n"
        "  client_id: an-app\n"
        "  scopes:\n"
        "    - esi-skills.read_skills.v1\n"
        "    - esi-fittings.read_fittings.v1\n"
    ))
    assert load_config(path).sso.scopes == (
        "esi-skills.read_skills.v1", "esi-fittings.read_fittings.v1")


def test_the_command_line_only_sets_the_flags_it_was_given(no_env):
    from web.__main__ import _cli_overrides, _parse_args

    overrides = _cli_overrides(_parse_args(["--language", "zh_CN", "--port", "9000"]))

    assert overrides["PYFA_WEB_LANGUAGE"] == "zh_CN"
    assert overrides["PYFA_WEB_PORT"] == "9000"
    # Anything not passed keeps whatever the environment or web.yml says
    assert "PYFA_WEB_HOST" not in overrides
    assert "PYFA_WEB_DEV_AUTH_BYPASS" not in overrides


def test_the_language_flag_beats_the_environment(tmp_path, monkeypatch, no_env):
    """`python -m web --language zh_CN` picks the language of the UI and game data."""
    from web.__main__ import _cli_overrides, _parse_args

    monkeypatch.setenv("PYFA_WEB_LANGUAGE", "en_US")
    for name, value in _cli_overrides(_parse_args(["--language", "zh_CN"])).items():
        monkeypatch.setenv(name, value)

    assert load_config(tmp_path / "missing.yml").language == "zh_CN"


def test_pyfa_log_records_reach_the_console(capsys):
    """logbook throws every record away while no handler is pushed, and the server pushes
    none of its own: without this, a failed login leaves nothing in the log."""
    import logbook

    from web.__main__ import _setup_logging

    handler = _setup_logging("info")
    try:
        logbook.Logger("web.tests").warning("a record nothing would otherwise keep")
    finally:
        handler.pop_application()

    assert "a record nothing would otherwise keep" in capsys.readouterr().err


def test_the_log_level_names_uvicorn_knows_are_understood():
    """`--log-level` (env: PYFA_WEB_LOG_LEVEL) is shared with uvicorn, so a name logbook
    rejects must not stop the server from starting."""
    import logbook

    from web.__main__ import _log_level

    assert _log_level("DEBUG") == logbook.lookup_level("DEBUG")
    assert _log_level("warning") == logbook.lookup_level("WARNING")
    assert _log_level("") == logbook.lookup_level("INFO")
    assert _log_level("not-a-level") == logbook.lookup_level("INFO")
