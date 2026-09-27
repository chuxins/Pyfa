"""Operator tooling tests (``python -m web.admin``).

The commands are exercised as functions against the same account store and data
directory the server fixture uses, which is what makes them meaningful: the
accounts and databases are the real ones, not a stand-in.
"""

import pytest

from web import admin
from web.tests.conftest import RIFTER_ID, next_character_id


def test_list_shows_every_account(app_state, capsys):
    app_state.users.upsert_from_sso(
        character_id=next_character_id(), character_name="Listed Pilot")

    assert admin.list_accounts(app_state.config) == 0
    output = capsys.readouterr().out
    assert "Listed Pilot" in output
    assert "active" in output


def test_list_with_fits_counts_the_databases(app_state, make_user, capsys):
    client = make_user("Counted Pilot")
    assert client.post("/api/fits", json={"shipId": RIFTER_ID}).status_code == 201
    capsys.readouterr()

    assert admin.list_accounts(app_state.config, with_fits=True) == 0
    line = next(row for row in capsys.readouterr().out.splitlines()
                if "Counted Pilot" in row)
    assert line.split()[-2] == "1"
    assert line.split()[-1] == "active"


def test_disable_locks_an_account_out_and_enable_lets_it_back_in(app_state, make_user):
    client = make_user("Locked Pilot")
    user_id = client.pyfaUser.id

    assert admin.set_disabled(app_state.config, user_id, True) == 0
    assert client.get("/api/auth/me").json()["authenticated"] is False
    assert client.post("/api/fits", json={"shipId": RIFTER_ID}).status_code == 401

    assert admin.set_disabled(app_state.config, user_id, False) == 0
    assert client.get("/api/auth/me").json()["authenticated"] is True


def test_unknown_accounts_are_reported(app_state):
    with pytest.raises(admin.AdminError):
        admin.set_disabled(app_state.config, 999999, True)
    with pytest.raises(admin.AdminError):
        admin.delete_data(app_state.config, 999999, assume_yes=True)
    with pytest.raises(admin.AdminError):
        admin.import_db(app_state.config, 999999, __file__)


def test_the_command_line_reads_the_server_configuration(app_state, capsys):
    """``main`` has to end up on the same data directory the server uses."""
    assert admin.main(["list"]) == 0
    assert "character" in capsys.readouterr().out
    assert app_state.config.data_dir == admin.load_config().data_dir


def test_the_command_line_reports_bad_input(app_state, capsys):
    assert admin.main(["disable", "999999"]) == 1
    assert "no account" in capsys.readouterr().err


def test_delete_data_removes_the_files_and_keeps_the_account(app_state, make_user):
    client = make_user("Deleted Pilot")
    user_id = client.pyfaUser.id
    assert client.post("/api/fits", json={"shipId": RIFTER_ID}).status_code == 201

    directory = app_state.config.user_dir(user_id)
    assert directory.is_dir()
    # A server holding the database open would stop Windows deleting it, so the
    # cached session goes first (in production: stop the server)
    assert app_state.registry.close_user(user_id)

    assert admin.delete_data(app_state.config, user_id, assume_yes=True) == 0
    assert not directory.exists()
    # The account survives, so signing in again simply starts a fresh database
    assert app_state.users.get(user_id) is not None
    assert client.get("/api/fits").json()["fits"] == []


def test_import_db_adopts_a_desktop_database(app_state, make_user):
    owner = make_user("Source Pilot")
    created = owner.post("/api/fits", json={"shipId": RIFTER_ID, "name": "Imported Rifter"})
    assert created.status_code == 201, created.text
    source = app_state.config.user_db_path(owner.pyfaUser.id)
    # Closing the engine folds the write-ahead log into the database, so a plain
    # file copy is complete -- which is also what makes copying a desktop
    # saveddata.db in work
    assert app_state.registry.close_user(owner.pyfaUser.id)

    imported = make_user("Imported Pilot")
    imported_id = imported.pyfaUser.id
    assert not app_state.config.user_db_path(imported_id).exists()

    assert admin.import_db(app_state.config, imported_id, str(source)) == 0
    payload = imported.get("/api/fits").json()
    assert [fit["name"] for fit in payload["fits"]] == ["Imported Rifter"]


def test_import_db_needs_force_to_replace_an_existing_database(app_state, make_user):
    owner = make_user("Force Source")
    assert owner.post(
        "/api/fits", json={"shipId": RIFTER_ID, "name": "Source Fit"}).status_code == 201
    source = app_state.config.user_db_path(owner.pyfaUser.id)
    assert app_state.registry.close_user(owner.pyfaUser.id)

    target = make_user("Force Target")
    target_id = target.pyfaUser.id
    assert target.post(
        "/api/fits", json={"shipId": RIFTER_ID, "name": "Own Fit"}).status_code == 201

    with pytest.raises(admin.AdminError):
        admin.import_db(app_state.config, target_id, str(source))

    assert app_state.registry.close_user(target_id)
    assert admin.import_db(app_state.config, target_id, str(source), force=True) == 0
    assert [fit["name"] for fit in target.get("/api/fits").json()["fits"]] == ["Source Fit"]
