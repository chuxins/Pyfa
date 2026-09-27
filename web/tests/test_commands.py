"""Editing tests.

These go through the same ``Gui*Command`` classes the desktop application uses, so
they double as a parity check: if the numbers here drift from what the desktop
shows for the same fit, something broke in the reuse path (context binding, the
undo stack, or the event stubs).
"""

import pytest

from web.tests.conftest import AUTOCANNON_ID, EMP_S_ID, RIFTER_ID

#: Light Missile Launcher II. A Rifter has three high slots but only two launcher
#: hardpoints, so the third one is refused for the hardpoints and not for the slots.
LAUNCHER_ID = 2404

#: Damage Control II. ``maxGroupFitted`` is 1, a reason the refusal does not spell out.
DAMAGE_CONTROL_ID = 2048

#: Hornet EC-300. A Rifter has no fighter tubes, so this is always refused
FIGHTER_ID = 23707

#: Nothing in the game data
UNKNOWN_ITEM_ID = 999999999


def run_command(client, fit_id, command, **args):
    response = client.post("/api/fits/{}/commands".format(fit_id), json={"command": command, "args": args})
    return response


def refusal(response):
    """The explained refusal a refused edit answers with."""
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"], detail
    assert detail["params"] is not None
    return detail


def make_fit(client, name="Edit Test"):
    response = client.post("/api/fits", json={"shipId": RIFTER_ID, "name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_command_registry_is_exposed(user_client):
    payload = user_client.get("/api/commands").json()
    names = {entry["name"] for entry in payload["commands"]}
    # undo/redo are endpoints of their own, not commands to submit
    assert "undo" not in names and "redo" not in names
    assert {"addLocalModule", "removeLocalModules", "toggleLocalDroneStates"} <= names
    spec = next(entry for entry in payload["commands"] if entry["name"] == "addLocalModule")
    assert spec["requires"] == ["itemId"]
    assert spec["summary"]


def test_unknown_command_is_rejected(user_client):
    fit_id = make_fit(user_client)
    response = run_command(user_client, fit_id, "dropDatabase")
    assert response.status_code == 400
    assert "unknown command" in response.json()["detail"]


def test_missing_argument_is_rejected(user_client):
    fit_id = make_fit(user_client)
    response = run_command(user_client, fit_id, "addLocalModule")
    assert response.status_code == 400
    assert "requires" in response.json()["detail"]


def test_add_module_with_ammo_matches_engine_numbers(user_client):
    """The reference fit from the engine probe: 200mm AC II + EMP S on a Rifter."""
    fit_id = make_fit(user_client)

    added = run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID)
    assert added.status_code == 200, added.text
    detail = added.json()

    loaded = None
    for module in detail["racks"]["high"]:
        if module["itemId"] == AUTOCANNON_ID:
            loaded = run_command(user_client, fit_id, "changeLocalModuleCharges",
                                 positions=[module["position"]], chargeItemId=EMP_S_ID)
            break
    assert loaded is not None and loaded.status_code == 200, getattr(loaded, "text", None)

    stats = loaded.json()["stats"]["firepower"]
    weapon = stats["weapon"]["value"]
    assert weapon["em"] == pytest.approx(29.2215, rel=1e-4)
    assert weapon["kinetic"] == pytest.approx(3.2468333333333335, rel=1e-4)
    assert weapon["explosive"] == pytest.approx(6.493666666666667, rel=1e-4)
    assert stats["dps"]["value"]["total"] == pytest.approx(38.962, rel=1e-4)

    volley = stats["volley"]["value"]
    assert volley["em"] == pytest.approx(49.31128125, rel=1e-4)

    resources = loaded.json()["stats"]["resources"]
    assert resources["cpu"]["used"] > 0
    assert resources["powergrid"]["used"] > 0
    assert resources["hardpoints"]["turret"]["used"] == 1


def module_at(detail, rack, position):
    """The rack entry for a module, addressed by its position in ``fit.modules``."""
    return next(module for module in detail["racks"][rack] if module["position"] == position)


def test_module_states_and_workflow(user_client):
    fit_id = make_fit(user_client)
    run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID)

    detail = user_client.get("/api/fits/{}".format(fit_id)).json()
    position = next(m["position"] for m in detail["racks"]["high"] if m["itemId"] == AUTOCANNON_ID)
    assert module_at(detail, "high", position)["state"] == "active"

    # ctrl-click puts a module offline; a plain click cycles it back
    offline = run_command(user_client, fit_id, "changeLocalModuleStates",
                          main={"kind": "module", "position": position}, click="ctrl")
    assert offline.status_code == 200, offline.text
    assert module_at(offline.json(), "high", position)["state"] == "offline"

    online = run_command(user_client, fit_id, "changeLocalModuleStates",
                         main={"kind": "module", "position": position}, click="left")
    assert module_at(online.json(), "high", position)["state"] in ("online", "active")


def test_state_click_cycles_through_overload(user_client):
    """A plain click walks online, active, overheated and back to online.

    ``cycle`` is the browser's own click (see ``web/services/commands.py``): the desktop's
    left click only ever toggles online and active, so without it overload is reachable
    through the right click alone, which is what a browser cannot discover.
    """
    fit_id = make_fit(user_client)
    run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID)
    detail = user_client.get("/api/fits/{}".format(fit_id)).json()
    position = next(m["position"] for m in detail["racks"]["high"] if m["itemId"] == AUTOCANNON_ID)
    assert module_at(detail, "high", position)["state"] == "active"

    def click(kind):
        response = run_command(user_client, fit_id, "changeLocalModuleStates",
                               main={"kind": "module", "position": position}, click=kind)
        assert response.status_code == 200, response.text
        return module_at(response.json(), "high", position)["state"]

    assert click("cycle") == "overheated"
    # Overload is the top of the ladder: the next click drops back to online
    assert click("cycle") == "online"
    assert click("cycle") == "active"
    # Off is still ctrl-click, and the ladder starts again from there
    assert click("ctrl") == "offline"
    assert click("cycle") == "online"
    # A right click overloads in one go, from wherever the module is
    assert click("right") == "overheated"


def test_a_module_with_nowhere_to_go_is_answered_not_refused(user_client):
    """A passive module's chip: nothing to change, and the refusal names the state."""
    fit_id = make_fit(user_client)
    added = run_command(user_client, fit_id, "addLocalModule", itemId=DAMAGE_CONTROL_ID)
    assert added.status_code == 200, added.text
    position = next(m["position"] for m in added.json()["racks"]["low"] if m["itemId"] == DAMAGE_CONTROL_ID)
    module = module_at(added.json(), "low", position)
    assert module["state"] == "online"
    # Not a weapon, so the high rack would never offer to group it
    assert module["hardpoint"] is None

    detail = refusal(run_command(user_client, fit_id, "changeLocalModuleStates",
                                 main={"kind": "module", "position": position}, click="cycle"))
    assert detail["code"] == "stateUnchanged"
    assert detail["params"] == {"name": module["item"]["name"], "state": "online"}
    # The fit is untouched
    assert module_at(user_client.get("/api/fits/{}".format(fit_id)).json(),
                     "low", position)["state"] == "online"


def test_grouped_weapons_move_together(user_client):
    """What the high rack's grouping button sends: one click, several positions.

    The button itself lives in the browser (see ``web/frontend/src/components/FittingView.vue``);
    this is the part that reaches the engine, and it is the multi-position form of the same
    commands the desktop uses when several modules are selected.
    """
    fit_id = make_fit(user_client)
    for itemId in (AUTOCANNON_ID, AUTOCANNON_ID, LAUNCHER_ID):
        response = run_command(user_client, fit_id, "addLocalModule", itemId=itemId)
        assert response.status_code == 200, response.text
    high = response.json()["racks"]["high"]

    # The hardpoint is what the rack groups by: turrets and launchers, nothing else
    guns = [module["position"] for module in high if module["itemId"] == AUTOCANNON_ID]
    assert len(guns) == 2
    assert {module["hardpoint"] for module in high if module["itemId"] == AUTOCANNON_ID} == {"turret"}
    launcher = next(module for module in high if module["itemId"] == LAUNCHER_ID)
    assert launcher["hardpoint"] == "launcher"

    # One click, both guns -- which is what makes them a group
    moved = run_command(user_client, fit_id, "changeLocalModuleStates",
                        main={"kind": "module", "position": guns[0]},
                        positions=guns[1:], click="cycle")
    assert moved.status_code == 200, moved.text
    assert {module_at(moved.json(), "high", position)["state"] for position in guns} == {"overheated"}
    # A weapon of another type in the same rack is a group of its own and stays put
    assert module_at(moved.json(), "high", launcher["position"])["state"] == "active"

    # and one charge reaches the whole group
    loaded = run_command(user_client, fit_id, "changeLocalModuleCharges",
                         positions=guns, chargeItemId=EMP_S_ID)
    assert loaded.status_code == 200, loaded.text
    charged = {module_at(loaded.json(), "high", position)["charge"]["item"]["id"] for position in guns}
    assert charged == {EMP_S_ID}


def test_remove_module(user_client):
    fit_id = make_fit(user_client)
    run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID)
    detail = user_client.get("/api/fits/{}".format(fit_id)).json()
    position = next(m["position"] for m in detail["racks"]["high"] if m["itemId"] == AUTOCANNON_ID)

    removed = run_command(user_client, fit_id, "removeLocalModules", positions=[position])
    assert removed.status_code == 200, removed.text
    assert all(module["isEmpty"] for module in removed.json()["racks"]["high"])


def test_invalid_position_is_rejected(user_client):
    fit_id = make_fit(user_client)
    response = run_command(user_client, fit_id, "removeLocalModules", positions=[99])
    assert response.status_code == 400
    assert "out of range" in response.json()["detail"]


def test_undo_and_redo(user_client):
    fit_id = make_fit(user_client)
    run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID)

    history = user_client.get("/api/fits/{}/history".format(fit_id)).json()
    assert history["canUndo"] is True
    assert history["canRedo"] is False
    assert history["undoName"] == "Add Local Module"

    undone = user_client.post("/api/fits/{}/undo".format(fit_id))
    assert undone.status_code == 200, undone.text
    payload = undone.json()
    assert payload["history"]["canUndo"] is False
    assert payload["history"]["canRedo"] is True
    assert payload["history"]["redoName"] == "Add Local Module"
    assert all(module["isEmpty"] for module in payload["racks"]["high"])
    # DPS must go back to zero once the module is gone
    assert payload["stats"]["firepower"]["dps"]["value"]["total"] == 0

    redone = user_client.post("/api/fits/{}/redo".format(fit_id))
    assert redone.status_code == 200, redone.text
    payload = redone.json()
    assert payload["history"]["canRedo"] is False
    assert payload["history"]["redoName"] is None
    assert any(module["itemId"] == AUTOCANNON_ID for module in payload["racks"]["high"])


def test_undo_on_clean_fit_is_rejected(user_client):
    fit_id = make_fit(user_client)
    assert user_client.post("/api/fits/{}/undo".format(fit_id)).status_code == 400


def test_drones_cargo_and_rename(user_client):
    """A broader sweep across containers, mixing containers in one undo stack."""
    drone_id = 2456  # Hobgoblin II
    fit_id = make_fit(user_client)

    assert run_command(user_client, fit_id, "addLocalDrone", itemId=drone_id, amount=5).status_code == 200
    assert run_command(user_client, fit_id, "addCargo", itemId=EMP_S_ID, amount=100).status_code == 200
    renamed = run_command(user_client, fit_id, "renameFit", name="Renamed By Command")
    assert renamed.status_code == 200, renamed.text

    detail = renamed.json()
    assert detail["name"] == "Renamed By Command"
    assert detail["drones"][0]["itemId"] == drone_id
    assert detail["drones"][0]["amount"] == 5
    assert detail["cargo"][0]["itemId"] == EMP_S_ID
    assert detail["cargo"][0]["amount"] == 100
    assert detail["stats"]["resources"]["drones"]["bayUsed"] > 0

    # Three edits, three undos
    assert detail["history"]["depth"] == 3
    for _ in range(3):
        assert user_client.post("/api/fits/{}/undo".format(fit_id)).status_code == 200
    final = user_client.get("/api/fits/{}".format(fit_id)).json()
    assert final["name"] == "Edit Test"
    assert final["drones"] == []
    assert final["cargo"] == []


def test_drone_stack_state_toggle(user_client):
    fit_id = make_fit(user_client)
    run_command(user_client, fit_id, "addLocalDrone", itemId=2456, amount=5)
    detail = user_client.get("/api/fits/{}".format(fit_id)).json()
    assert detail["drones"][0]["amountActive"] == 0

    toggled = run_command(user_client, fit_id, "toggleLocalDroneStates",
                          main={"kind": "drone", "position": 0})
    assert toggled.status_code == 200, toggled.text
    assert toggled.json()["drones"][0]["amountActive"] > 0


def test_reset_clears_the_fit(user_client):
    fit_id = make_fit(user_client)
    run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID)
    run_command(user_client, fit_id, "addLocalDrone", itemId=2456, amount=3)

    assert user_client.post("/api/fits/{}/reset".format(fit_id)).status_code == 204
    detail = user_client.get("/api/fits/{}".format(fit_id)).json()
    assert all(module["isEmpty"] for module in detail["racks"]["high"])
    assert detail["drones"] == []
    assert detail["stats"]["firepower"]["dps"]["value"]["total"] == 0


def test_undo_stacks_are_per_user(user_client, second_user_client):
    """Undo must never reach into another user's fit."""
    first_fit = make_fit(user_client, "First")
    second_fit = make_fit(second_user_client, "Second")

    run_command(user_client, first_fit, "addLocalModule", itemId=AUTOCANNON_ID)
    run_command(second_user_client, second_fit, "addLocalModule", itemId=AUTOCANNON_ID)

    assert user_client.get("/api/fits/{}/history".format(first_fit)).json()["depth"] == 1
    assert second_user_client.get("/api/fits/{}/history".format(second_fit)).json()["depth"] == 1

    user_client.post("/api/fits/{}/undo".format(first_fit))
    assert second_user_client.get("/api/fits/{}/history".format(second_fit)).json()["canUndo"] is True
    # The other user's fit is untouched by our undo
    assert any(module["itemId"] == AUTOCANNON_ID
               for module in second_user_client.get(
                   "/api/fits/{}".format(second_fit)).json()["racks"]["high"])


def test_commands_require_login(client):
    fit_id = 1
    response = client.post("/api/fits/{}/commands".format(fit_id),
                           json={"command": "addLocalModule", "args": {"itemId": AUTOCANNON_ID}})
    assert response.status_code == 401


def test_deleting_a_fit_forgets_its_undo_history(user_client):
    """The stack is keyed per user, so the engine clearing its own is not enough."""
    fit_id = make_fit(user_client)
    run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID)
    assert user_client.get("/api/fits/{}/history".format(fit_id)).json()["depth"] == 1

    assert user_client.delete("/api/fits/{}".format(fit_id)).status_code == 204

    history = user_client.get("/api/fits/{}/history".format(fit_id)).json()
    assert history["depth"] == 0
    assert history["canUndo"] is False


def test_duplicate_copies_the_fit_and_starts_a_clean_history(user_client):
    fit_id = make_fit(user_client, "Original")
    run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID)

    response = user_client.post("/api/fits/{}/duplicate".format(fit_id))
    assert response.status_code == 201, response.text
    clone = response.json()
    assert clone["id"] != fit_id
    assert clone["name"] == "Original (copy)"

    copied = user_client.get("/api/fits/{}".format(clone["id"])).json()
    assert any(module["itemId"] == AUTOCANNON_ID for module in copied["racks"]["high"])
    # The copy is a new fit: nothing to undo in it yet
    assert user_client.get("/api/fits/{}/history".format(clone["id"])).json()["depth"] == 0


# -- refused edits -------------------------------------------------------------------------


def test_ammunition_is_refused_with_the_reason(user_client):
    """A refusal names the item, so the browser can explain it instead of shrugging."""
    fit_id = make_fit(user_client)

    detail = refusal(run_command(user_client, fit_id, "addLocalModule", itemId=EMP_S_ID))

    assert detail["code"] == "isACharge"
    assert detail["params"]["name"] == "EMP S"
    assert detail["params"]["group"] == "Projectile Ammo"
    assert "EMP S" in detail["message"]


def test_full_high_rack_is_refused_with_the_reason(user_client):
    fit_id = make_fit(user_client)
    for _ in range(3):  # the Rifter has three high slots
        assert run_command(user_client, fit_id, "addLocalModule",
                           itemId=AUTOCANNON_ID).status_code == 200

    detail = refusal(run_command(user_client, fit_id, "addLocalModule", itemId=AUTOCANNON_ID))

    assert detail["code"] == "noFreeSlot"
    assert detail["params"]["rack"] == "high"
    assert detail["params"]["name"] == "200mm AutoCannon II"


def test_used_up_hardpoints_are_refused_with_the_reason(user_client):
    fit_id = make_fit(user_client)
    for _ in range(2):  # ... and two launcher hardpoints
        assert run_command(user_client, fit_id, "addLocalModule",
                           itemId=LAUNCHER_ID).status_code == 200

    detail = refusal(run_command(user_client, fit_id, "addLocalModule", itemId=LAUNCHER_ID))

    assert detail["code"] == "noHardpoint"
    assert detail["params"]["hardpoint"] == "launcher"


def test_an_item_that_does_not_exist_is_answered_rather_than_crashing(user_client):
    """Every command dereferences its item, so a stale id used to be a 500."""
    fit_id = make_fit(user_client)

    for command, args in (("addLocalModule", {}), ("addLocalDrone", {"amount": 1}),
                          ("addLocalFighter", {})):
        detail = refusal(run_command(user_client, fit_id, command, itemId=UNKNOWN_ITEM_ID, **args))
        assert detail["code"] == "unknownItem"
        assert detail["params"]["itemId"] == UNKNOWN_ITEM_ID


def test_a_non_numeric_item_id_is_a_client_mistake(user_client):
    fit_id = make_fit(user_client)

    response = run_command(user_client, fit_id, "addLocalModule", itemId="200mm AutoCannon II")

    assert response.status_code == 400
    assert "itemId must be an integer" in response.json()["detail"]


def test_a_refusal_we_cannot_explain_still_names_the_item(user_client):
    """Two damage controls: the reason is ``maxGroupFitted``, which this leaves generic."""
    fit_id = make_fit(user_client)
    assert run_command(user_client, fit_id, "addLocalModule",
                       itemId=DAMAGE_CONTROL_ID).status_code == 200

    detail = refusal(run_command(user_client, fit_id, "addLocalModule", itemId=DAMAGE_CONTROL_ID))

    assert detail["code"] == "doesNotFit"
    assert detail["params"]["name"] == "Damage Control II"
    assert "Damage Control II" in detail["message"]


def test_unexplained_commands_keep_the_plain_refusal(user_client):
    """Only module edits are explained; everything else answers as it always did."""
    fit_id = make_fit(user_client)

    detail = refusal(run_command(user_client, fit_id, "addLocalFighter", itemId=FIGHTER_ID))

    assert detail["code"] == "engineRefused"
    assert detail["params"]["command"] == "addLocalFighter"
