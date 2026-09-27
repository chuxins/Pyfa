"""Importing the fittings a pilot has saved in game.

ESI cannot be reached from a test run, so the call out to it is the only thing stubbed:
the ``SsoCharacter`` row, the data EVE would answer with and pyfa's own ESI import are
all real, which is where the interesting mistakes live -- a fit landing on the wrong
ship, a second import doubling everything, one account fetching with another's tokens.
"""

import pytest
import requests

from web.tests.conftest import AUTOCANNON_ID, EMP_S_ID, RIFTER_ID

#: A ship id no game data has, for the "EVE knows a hull this pyfa does not" case
UNKNOWN_SHIP_ID = 99_999_999

#: Hammerhead II -- a drone, so a fitting's drone bay has something in it
DRONE_ID = 2185


def esi_fitting(name="Imported Rifter", shipId=RIFTER_ID, fittingId=4001, esi_flags=True):
    """One entry of the array ``/characters/{id}/fittings/`` answers with.

    ``esi_flags`` decides how the item flags are spelled: ESI names them (``HiSlot0``,
    ``DroneBay``), pyfa's own export uses EVE's inventory ids. A fitting from either
    source has to import completely, drones and cargo included.
    """
    high0, high1, cargo, drone = (
        ("HiSlot0", "HiSlot1", "Cargo", "DroneBay") if esi_flags else (27, 28, 5, 87)
    )
    return {
        "fitting_id": fittingId,
        "name": name,
        "description": "saved in the EVE client",
        "ship_type_id": shipId,
        "items": [
            {"flag": high0, "quantity": 1, "type_id": AUTOCANNON_ID},
            {"flag": high1, "quantity": 1, "type_id": AUTOCANNON_ID},
            {"flag": cargo, "quantity": 40, "type_id": EMP_S_ID},
            {"flag": drone, "quantity": 3, "type_id": DRONE_ID},
        ],
    }


class FakeEsi:
    """Stands in for ``service.esi.Esi``: records the row id it is asked about."""

    def __init__(self, fittings):
        self.fittings = fittings
        self.requested = []

    def getFittings(self, characterId):
        self.requested.append(characterId)
        if isinstance(self.fittings, Exception):
            raise self.fittings
        return self.fittings


@pytest.fixture
def esi(monkeypatch):
    """Hand the test the fake ESI, so it can decide what EVE answers."""
    from web.services import esiFittings

    fake = FakeEsi([esi_fitting()])
    monkeypatch.setattr(esiFittings, "_esi", lambda: fake)
    return fake


@pytest.fixture
def pilot_client(make_user, app_state):
    """A signed-in account whose database holds what a login leaves behind."""
    from web.auth import store_sso_character

    client = make_user("Imported Pilot")
    user = client.pyfaUser
    with app_state.registry.acquire(user.id) as data:
        store_sso_character(
            data, user.character_id, user.character_name, app_state.config.sso.server,
            {
                "access_token": "an-access-token",
                "expires_in": 3600,
                "refresh_token": "a-refresh-token",
            },
        )
    return client


def tree_ships(client):
    """Every ship row of the browser tree, where each one's fits are counted."""
    tree = client.get("/api/ships/tree").json()
    return [
        ship
        for category in tree["categories"]
        for group in category["groups"]
        for ship in group["ships"]
    ]


def tree_ship(client, shipId):
    return next(ship for ship in tree_ships(client) if ship["id"] == shipId)


def fits_for(client, shipId):
    return client.get("/api/fits", params={"shipId": shipId}).json()["fits"]


def test_imported_fittings_land_under_their_ship(pilot_client, esi):
    esi.fittings = [esi_fitting("Imported Rifter", fittingId=4001), esi_fitting("Spare Rifter", fittingId=4002)]

    response = pilot_client.post("/api/esi/fittings/import")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["total"] == 2
    assert [fit["name"] for fit in payload["imported"]] == ["Imported Rifter", "Spare Rifter"]
    assert payload["skipped"] == []
    assert payload["character"]["name"] == "Imported Pilot"

    # Under the ship, which is what the browser tree reads its count from
    assert {fit["name"] for fit in fits_for(pilot_client, RIFTER_ID)} == {"Imported Rifter", "Spare Rifter"}
    assert {fit["shipId"] for fit in fits_for(pilot_client, RIFTER_ID)} == {RIFTER_ID}
    assert tree_ship(pilot_client, RIFTER_ID)["fitCount"] == 2
    # ... and under no other ship
    assert sum(ship.get("fitCount", 0) for ship in tree_ships(pilot_client)) == 2

    # The fitting itself, not just its name: modules and cargo arrived too
    fit_id = payload["imported"][0]["id"]
    detail = pilot_client.get("/api/fits/{}".format(fit_id)).json()
    assert detail["ship"]["id"] == RIFTER_ID
    fitted = [module for module in detail["racks"]["high"] if not module["isEmpty"]]
    assert [module["item"]["id"] for module in fitted] == [AUTOCANNON_ID, AUTOCANNON_ID]
    assert [(cargo["item"]["id"], cargo["amount"]) for cargo in detail["cargo"]] == [(EMP_S_ID, 40)]
    assert [(drone["item"]["id"], drone["amount"]) for drone in detail["drones"]] == [(DRONE_ID, 3)]
    assert detail["notes"] == "saved in the EVE client"


def test_pyfas_own_flag_spelling_still_imports(pilot_client, esi):
    """The desktop's export uses the inventory ids; a fitting from it arrives the same way."""
    esi.fittings = [esi_fitting("Exported Rifter", esi_flags=False)]
    payload = pilot_client.post("/api/esi/fittings/import").json()

    assert [fit["name"] for fit in payload["imported"]] == ["Exported Rifter"]
    detail = pilot_client.get("/api/fits/{}".format(payload["imported"][0]["id"])).json()
    assert [cargo["item"]["id"] for cargo in detail["cargo"]] == [EMP_S_ID]
    assert [drone["item"]["id"] for drone in detail["drones"]] == [DRONE_ID]


def test_importing_twice_does_not_double_the_fits(pilot_client, esi):
    esi.fittings = [esi_fitting("Imported Rifter")]
    assert pilot_client.post("/api/esi/fittings/import").json()["imported"]

    second = pilot_client.post("/api/esi/fittings/import").json()
    assert second["imported"] == []
    assert [entry["reason"] for entry in second["skipped"]] == ["alreadyImported"]
    assert len(fits_for(pilot_client, RIFTER_ID)) == 1


def test_a_second_copy_in_eve_is_still_imported(pilot_client, esi):
    """The pilot's own fit matches one of EVE's; the other one is new and belongs in pyfa."""
    esi.fittings = [esi_fitting("Imported Rifter", fittingId=4001)]
    pilot_client.post("/api/esi/fittings/import")

    esi.fittings = [esi_fitting("Imported Rifter", fittingId=4001), esi_fitting("Imported Rifter", fittingId=4002)]
    payload = pilot_client.post("/api/esi/fittings/import").json()
    assert [entry["reason"] for entry in payload["skipped"]] == ["alreadyImported"]
    assert len(payload["imported"]) == 1
    assert len(fits_for(pilot_client, RIFTER_ID)) == 2


def test_import_without_stored_tokens_asks_for_a_new_login(user_client):
    """No ``SsoCharacter`` row means no tokens, and that is decided before ESI is called."""
    response = user_client.post("/api/esi/fittings/import")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "noCharacter"


def test_one_account_cannot_import_with_another_accounts_tokens(pilot_client, second_user_client, esi):
    esi.fittings = [esi_fitting()]
    assert pilot_client.post("/api/esi/fittings/import").status_code == 200

    assert second_user_client.get("/api/fits").json()["fits"] == []
    assert second_user_client.post("/api/esi/fittings/import").status_code == 409
    assert esi.requested  # the first account used its own tokens, the second had none
    assert second_user_client.get("/api/fits").json()["fits"] == []


def test_a_ship_this_game_data_does_not_know_is_reported_not_fatal(pilot_client, esi):
    esi.fittings = [
        esi_fitting("Ghost hull", shipId=UNKNOWN_SHIP_ID, fittingId=1),
        esi_fitting("Imported Rifter", fittingId=2),
    ]
    payload = pilot_client.post("/api/esi/fittings/import").json()

    assert [entry["reason"] for entry in payload["skipped"]] == ["unknownShip"]
    assert payload["skipped"][0]["name"] == "Ghost hull"
    assert [fit["name"] for fit in payload["imported"]] == ["Imported Rifter"]


@pytest.mark.parametrize("answer", [
    requests.exceptions.ConnectionError("no route to host"),
    requests.exceptions.Timeout("too slow"),
])
def test_an_unreachable_esi_is_reported_as_such(pilot_client, esi, answer):
    esi.fittings = answer
    response = pilot_client.post("/api/esi/fittings/import")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "esiUnreachable"
    assert "EVE could not be reached" in response.json()["detail"]["message"]


def test_esi_refusing_is_reported_with_eves_own_words(pilot_client, esi):
    from service.esiAccess import APIException

    esi.fittings = APIException("https://esi.evetech.net/fittings", 403, {"error": "forbidden"})
    response = pilot_client.post("/api/esi/fittings/import")
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "esiRefused"
    assert "403" in detail["message"] and "403" in detail["params"]["reason"]


def test_the_import_hands_esi_the_row_the_login_stored(pilot_client, app_state, esi):
    """``Esi.getFittings`` resolves the ``SsoCharacter`` row itself, so the row id is what
    has to be handed over -- and the row has to still be there afterwards, since the next
    import refreshes the access token with its refresh token."""
    import eos.db
    from eos.saveddata.ssocharacter import SsoCharacter

    assert pilot_client.post("/api/esi/fittings/import").status_code == 200

    with app_state.registry.acquire(pilot_client.pyfaUser.id):
        row = eos.db.saveddata_session.query(SsoCharacter).one()
    assert esi.requested == [row.ID]
    assert row.characterName == "Imported Pilot"
    assert row.refreshToken
