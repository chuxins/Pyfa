"""Game data language: which of eve.db's translated columns the server reads.

The front end's language and the game data's language are independent on purpose
(see docs/web.md, "Interface language"). This file covers the game data half: the
engine binds item names to a language column when it imports its models, so the
language has to be decided from the server config before that happens.
"""

import sqlite3
from pathlib import Path

import pytest

from web.engine import gamedata_language
from web.tests.conftest import RIFTER_ID


@pytest.mark.parametrize("language, expected", [
    ("en_US", "en"),
    ("zh_CN", "zh"),
    ("fr_FR", "fr"),
    ("ja_JP", "ja"),
    ("ko_KR", "ko"),
    ("ru_RU", "ru"),
    ("zh", "zh"),  # short codes are what eos.config.set_lang takes
    # pyfa has a UI translation for these, eve.db has no columns for them
    ("de_DE", "en"),
    ("", "en"),
    (None, "en"),
])
def test_gamedata_language_picks_a_column_language(language, expected):
    assert gamedata_language(language) == expected


@pytest.fixture(scope="module")
def gamedata():
    """A connection to the built eve.db."""
    import db_update

    path = Path(db_update.DB_PATH)
    if not path.is_file():
        pytest.skip("eve.db has not been built")

    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def test_eve_db_has_a_column_for_every_mapped_language(gamedata):
    """The mapping is only worth anything if the database carries those columns."""
    import eos.config

    columns = {row[1] for row in gamedata.execute("PRAGMA table_info(invtypes)")}
    for suffix in eos.config.translation_mapping.values():
        assert "typeName" + suffix in columns


def test_chinese_column_holds_chinese_names(gamedata):
    """The language the UI ships, spot checked on the Rifter."""
    (name,) = gamedata.execute(
        "SELECT typeName_zh FROM invtypes WHERE typeID = ?", (RIFTER_ID,)).fetchone()
    assert name and any("\u4e00" <= char <= "\u9fff" for char in name), name


def test_load_config_hands_the_language_to_eos(monkeypatch):
    """The config is what pins the game data language down.

    It has to happen there rather than in the engine: eos binds gamedata names to a
    language column while it is imported, and the DB layer gets imported on the way to
    ``create_app``. See web.engine.apply_gamedata_language.
    """
    import eos.config

    from web.config import load_config

    monkeypatch.setenv("PYFA_WEB_LANGUAGE", "zh_CN")
    try:
        config = load_config()
        assert config.language == "zh_CN"
        assert eos.config.lang == eos.config.translation_mapping["zh"]
    finally:
        eos.config.set_lang("en")
    assert eos.config.lang == ""
