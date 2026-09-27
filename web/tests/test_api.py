"""Web API tests.

The point of these tests is not coverage for its own sake: they pin down the two
things that could quietly break a multi-user deployment (one user seeing another
user's fits, and the engine being shared across users) and the numbers the fitting
view shows.
"""

import pytest

from web.tests.conftest import AUTOCANNON_ID, EMP_S_ID, RIFTER_ID


def test_meta_reports_engine_and_gamedata(client):
    payload = client.get("/api/meta").json()
    assert payload["pyfaVersion"]
    assert payload["gamedata"]["build"]
    assert payload["language"] == "en_US"


def test_anonymous_requests_can_read_game_data(client):
    """Static game data needs no login, so the ship browser can load before sign-in."""
    response = client.get("/api/ships/tree")
    assert response.status_code == 200
    categories = {entry["name"] for entry in response.json()["categories"]}
    assert "Ship" in categories


def test_anonymous_requests_cannot_touch_fits(client):
    assert client.post("/api/fits", json={"shipId": RIFTER_ID}).status_code == 401
    assert client.get("/api/fits").status_code == 200  # read is allowed, guest db is empty


def test_ship_detail(client):
    payload = client.get("/api/ships/{}".format(RIFTER_ID)).json()
    assert payload["ship"]["name"] == "Rifter"
    assert payload["slots"]["high"] == 3
    assert payload["slots"]["low"] == 4
    assert payload["slots"]["rig"] == 3


def test_item_search_finds_module_and_ship(client):
    results = client.get("/api/items/search", params={"q": "200mm AutoCannon II"}).json()["results"]
    assert [item["id"] for item in results] == [AUTOCANNON_ID]

    ships = client.get("/api/items/search", params={"q": "Rifter", "scope": "everything"}).json()["results"]
    assert RIFTER_ID in [item["id"] for item in ships]


def test_dev_login_roundtrip(client):
    response = client.get("/api/auth/login", follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/api/auth/me").json()["authenticated"] is True


def test_create_fit_and_read_back(user_client):
    created = user_client.post("/api/fits", json={"shipId": RIFTER_ID, "name": "Test Rifter"})
    assert created.status_code == 201, created.text
    fit_id = created.json()["id"]

    detail = user_client.get("/api/fits/{}".format(fit_id)).json()
    assert detail["name"] == "Test Rifter"
    assert detail["ship"]["item"]["name"] == "Rifter"
    # A fresh Rifter: three high slots, all empty
    assert len(detail["racks"]["high"]) == 3
    assert all(module["isEmpty"] for module in detail["racks"]["high"])
    assert detail["stats"]["errors"] == {}


def test_empty_fit_stats_are_ship_baseline(user_client):
    fit_id = user_client.post("/api/fits", json={"shipId": RIFTER_ID}).json()["id"]
    stats = user_client.get("/api/fits/{}/stats".format(fit_id)).json()["stats"]

    # Rifter with all-5 skills and no modules
    hardpoints = stats["resources"]["hardpoints"]
    assert hardpoints["turret"]["total"] == 3
    assert hardpoints["turret"]["used"] == 0
    assert stats["resistances"]["hp"]["shield"] > 0
    assert stats["resistances"]["ehp"]["total"] > stats["resistances"]["hp"]["total"]
    assert stats["firepower"]["dps"]["value"]["total"] == 0
    assert stats["capacitor"]["stable"] is True
    assert stats["targeting"]["maxTargetRange"] > 0


def test_fit_rename_and_delete(user_client):
    fit_id = user_client.post("/api/fits", json={"shipId": RIFTER_ID}).json()["id"]

    renamed = user_client.patch("/api/fits/{}".format(fit_id), json={"name": "Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed"

    assert user_client.patch("/api/fits/{}".format(fit_id), json={"name": "  "}).status_code == 400

    assert user_client.delete("/api/fits/{}".format(fit_id)).status_code == 204
    assert user_client.get("/api/fits/{}".format(fit_id)).status_code == 404


def test_fits_are_isolated_between_users(user_client, second_user_client):
    """The whole point of the per-user database."""
    fit_id = user_client.post("/api/fits", json={"shipId": RIFTER_ID, "name": "Mine"}).json()["id"]

    assert [f["name"] for f in user_client.get("/api/fits").json()["fits"]] == ["Mine"]
    assert second_user_client.get("/api/fits").json()["fits"] == []

    # Fit IDs restart per user, so the second user's fit 1 is not the first user's
    second_fit = second_user_client.post("/api/fits", json={"shipId": RIFTER_ID, "name": "Theirs"}).json()["id"]
    assert second_fit == fit_id  # same numbering, different database
    assert second_user_client.get("/api/fits/{}".format(second_fit)).json()["name"] == "Theirs"
    assert user_client.get("/api/fits/{}".format(fit_id)).json()["name"] == "Mine"

    # And the second user cannot reach into the first user's data
    second_user_client.patch("/api/fits/{}".format(fit_id), json={"name": "Hijacked"})
    assert user_client.get("/api/fits/{}".format(fit_id)).json()["name"] == "Mine"


def test_service_singletons_are_scoped_per_user(app_state, user_client, second_user_client):
    """Fit caches ORM objects, so one instance per process would mix users up."""
    from service.fit import Fit

    first = user_client.pyfaUser
    second = second_user_client.pyfaUser

    with app_state.registry.acquire(first.id):
        first_instance = Fit.getInstance()
        first_instance_again = Fit.getInstance()
    with app_state.registry.acquire(second.id):
        second_instance = Fit.getInstance()

    assert first_instance is first_instance_again, "the same user must get the same instance"
    assert first_instance is not second_instance, "different users must not share engine state"


def test_saveddata_without_a_user_fails_loudly():
    """A background thread that forgot to bind must not write to the wrong database."""
    import pytest

    from eos.db import sessionctx

    with pytest.raises(sessionctx.NoSessionContextError):
        sessionctx.get_context().session.query("anything")


def test_item_attributes_and_requirements(client):
    attributes = client.get("/api/items/{}/attributes".format(AUTOCANNON_ID)).json()
    assert attributes["modified"] is False
    assert any(row["name"] == "damageMultiplier" for row in attributes["rows"])

    requirements = client.get("/api/items/{}/requirements".format(AUTOCANNON_ID)).json()
    assert any(row["name"] == "Small Projectile Turret" for row in requirements["skills"])


def test_valid_charges_for_module(client):
    charges = client.get("/api/items/{}/charges".format(AUTOCANNON_ID)).json()["charges"]
    names = {charge["item"]["name"] for charge in charges}
    assert "EMP S" in names


@pytest.mark.parametrize("kind,image_id", [("icons", 387), ("renders", 46)])
def test_images_are_served(client, kind, image_id):
    response = client.get("/img/{}/{}".format(kind, image_id))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "max-age" in response.headers["cache-control"]


def test_unknown_image_is_404(client):
    assert client.get("/img/icons/999999999").status_code == 404
    assert client.get("/img/bogus/1").status_code == 404


def test_meta_only_tells_a_signed_in_client_about_the_dev_bypass(client, user_client):
    """The flag is an invitation on a deployment that left it on by mistake."""
    assert client.get("/api/meta").json()["sso"]["devBypass"] is False
    assert user_client.get("/api/meta").json()["sso"]["devBypass"] is True


def test_dispatched_callbacks_keep_the_context_they_were_queued_from(app_state, user_client):
    """wx.CallAfter carries the caller's context, so the callback sees the user."""
    import threading

    from eos.db import sessionctx
    from web.events import dispatcher

    user = user_client.pyfaUser
    result = {}
    done = threading.Event()

    with app_state.registry.acquire(user.id) as data:
        def callback():
            try:
                result["context"] = sessionctx.current_context()
            except Exception as ex:  # pragma: no cover - a failure is the point
                result["error"] = ex
            finally:
                done.set()

        dispatcher.submit(callback)
        assert done.wait(30), "the dispatcher never ran the callback"

    assert result.get("error") is None
    assert result["context"] is data.context


def test_dispatched_callbacks_from_a_foreign_thread_cannot_touch_saveddata(app_state):
    """Threads do not inherit contextvars, so such a callback has to fail loudly."""
    import threading

    from eos.db import sessionctx
    from web.events import dispatcher

    result = {}
    done = threading.Event()

    def foreign_thread():
        def callback():
            try:
                sessionctx.get_context().session.query("anything")
            except Exception as ex:
                result["error"] = ex
            finally:
                done.set()

        dispatcher.submit(callback)

    threading.Thread(target=foreign_thread, daemon=True).start()
    assert done.wait(30), "the dispatcher never ran the callback"
    assert isinstance(result["error"], sessionctx.NoSessionContextError)

