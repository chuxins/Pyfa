"""Turns engine objects into JSON.

Deliberately explicit rather than generic: pyfa's models are SQLAlchemy-mapped
with relationship graphs that cycle (fits project onto fits, modules point back
at fits), so naive attribute dumping either explodes or leaks another user's
data. Every field the browser needs is listed here by hand.
"""

import eos.config
from eos.const import FittingHardpoint, FittingModuleState, FittingSlot, ImplantLocation
from logbook import Logger

from web.services.stats import build_stats

pyfalog = Logger(__name__)

SLOT_NAMES = {
    FittingSlot.LOW: "low",
    FittingSlot.MED: "med",
    FittingSlot.HIGH: "high",
    FittingSlot.RIG: "rig",
    FittingSlot.SUBSYSTEM: "subsystem",
    FittingSlot.MODE: "mode",
    FittingSlot.SYSTEM: "system",
    FittingSlot.SERVICE: "service",
}

#: Order racks appear in the fitting view
RACK_ORDER = ("high", "med", "low", "rig", "subsystem", "service", "mode", "system")

STATE_NAMES = {
    FittingModuleState.OFFLINE: "offline",
    FittingModuleState.ONLINE: "online",
    FittingModuleState.ACTIVE: "active",
    FittingModuleState.OVERHEATED: "overheated",
}

#: Where a weapon hangs on a ship. Turrets and launchers have a hardpoint and everything
#: else has none, which is how the fitting view knows what its high rack can group. The
#: words are also what a refusal says when a hardpoint is used up ("no free turret
#: hardpoint for ..."), and the browser has a word per key in its own catalogue.
HARDPOINT_NAMES = {
    FittingHardpoint.TURRET: "turret",
    FittingHardpoint.MISSILE: "launcher",
}


def slot_name(slot):
    return SLOT_NAMES.get(slot, str(slot))


def state_name(state):
    return STATE_NAMES.get(state, str(state))


def hardpoint_name(hardpoint):
    """``turret``, ``launcher``, or None for everything that is not a weapon."""
    return HARDPOINT_NAMES.get(hardpoint)


def _icon_id(item):
    if item is None:
        return None
    return getattr(item, "iconID", None)


def _graphic_id(item):
    if item is None:
        return None
    return getattr(item, "graphicID", None)


def _group_name(item):
    """English group name -- the engine compares these against English literals."""
    group = getattr(item, "group", None)
    return getattr(group, "name", None)


def _category_name(item):
    """English category name -- see :func:`_group_name`."""
    group = getattr(item, "group", None)
    category = getattr(group, "category", None)
    return getattr(category, "name", None)


def display_name(obj):
    """What a named gamedata row is called in the language the server runs as.

    Two shapes of row come through here. Groups and categories keep ``name`` on their
    English column -- the engine (and :func:`classify_item`) compares those against
    English literals -- and bind ``displayName`` to a language column when the gamedata
    models are imported (see :func:`web.engine.gamedata_language`). Attributes and units
    are plain tables that instead keep one column per language
    (:data:`eos.config.translation_mapping`), which leaves ``displayName`` on English;
    those rows are read at the column for the language in play.

    That second case is why the attribute list of a *fitted* item follows the server's
    language: it is built from the attribute table itself, not from the engine's wrapper
    around it (see ``_modified_attribute_rows`` in :mod:`web.api.items`).
    """
    if obj is None:
        return None
    if eos.config.lang:
        value = getattr(obj, "displayName" + eos.config.lang, None)
        if value:
            return value
    return getattr(obj, "displayName", None) or getattr(obj, "name", None)


def _group_display_name(item):
    return display_name(getattr(item, "group", None))


def _category_display_name(item):
    group = getattr(item, "group", None)
    return display_name(getattr(group, "category", None))


#: Categories/groups that map onto a fitting action, so the UI knows what happens
#: when an item is clicked (add as module, load as charge, put in cargo, ...).
MODULE_CATEGORIES = ("Module", "Subsystem", "Structure Module")


def classify_item(item):
    """What a fitting action would do with this item."""
    if item is None:
        return None
    category = _category_name(item) or ""
    group = _group_name(item) or ""
    if category == "Drone":
        return "drone"
    if category == "Fighter":
        return "fighter"
    if category == "Charge":
        return "charge"
    if category == "Implant":
        # Boosters live in the Implant category but fit in their own rack
        return "booster" if group == "Booster" else "implant"
    if category in MODULE_CATEGORIES:
        return "module"
    if category in ("Ship", "Structure"):
        return "ship"
    return "cargo"


def item_image(item):
    """Which image file represents an item, and under which kind.

    Modules and charges carry an ``iconID``; ships have no icon in the static data
    and are represented by their render, keyed by ``graphicID`` -- exactly how the
    desktop ship browser picks its images.
    """
    if item is None:
        return None
    iconId = _icon_id(item)
    if iconId:
        return {"kind": "icons", "id": iconId}
    graphicId = _graphic_id(item)
    if graphicId:
        return {"kind": "renders", "id": graphicId}
    return None


def serialize_item(item, detail=False):
    """Identity plus display metadata for an EVE type."""
    if item is None:
        return None
    data = {
        "id": item.ID,
        "name": item.name,
        "iconId": _icon_id(item),
        "graphicId": _graphic_id(item),
        "image": item_image(item),
        "group": _group_display_name(item),
        "category": _category_display_name(item),
        "itemKind": classify_item(item),
    }
    metaGroup = getattr(item, "metaGroup", None)
    if metaGroup is not None:
        data["metaGroup"] = getattr(metaGroup, "name", None)
    metaLevel = getattr(item, "metaLevel", None)
    if metaLevel:
        data["metaLevel"] = metaLevel
    if detail:
        data["description"] = getattr(item, "description", None)
        marketGroup = getattr(item, "marketGroup", None)
        if marketGroup is not None:
            data["marketGroup"] = {"id": marketGroup.ID, "name": getattr(marketGroup, "name", None)}
        volume = item.getAttribute("volume") if hasattr(item, "getAttribute") else None
        if volume:
            data["volume"] = volume
        data["published"] = bool(getattr(item, "published", False))
    return data


def module_accepts_charges(module):
    """Whether a module has a charge slot at all.

    ``Module.getValidCharges`` reads ``chargeGroup0`` .. ``chargeGroup4`` and nothing
    else, so a module carrying none of them can never take a charge: the two agree on
    every published module in the game data (997 of the 4252 carry a charge group, and
    each of those has at least one valid charge). Reading those attributes is also what
    makes the question affordable -- asking for the charges themselves loads a group and
    all of its items out of the static data, which is more than a fit's every row can
    pay for.
    """
    return any(
        module.getModifiedItemAttr("chargeGroup" + str(index), None) for index in range(5)
    )


def serialize_charge(module):
    charge = getattr(module, "charge", None)
    if charge is None:
        return None
    return {
        "item": serialize_item(charge),
        "amount": module.numCharges,
    }


def serialize_module(module, position=None):
    if module is None:
        return None
    item = module.item
    data = {
        "position": position,
        "slot": slot_name(module.slot),
        "isEmpty": bool(module.isEmpty),
        "itemId": module.itemID,
        "item": serialize_item(item),
        "state": state_name(module.state),
        "amount": getattr(module, "amount", 1),
    }
    if not module.isEmpty:
        data["charge"] = serialize_charge(module)
        #: Whether the row has a charge slot to offer: a heat sink has none, and the
        #: fitting view hides the control rather than open a list that is always empty
        data["canFitCharges"] = module_accepts_charges(module)
        #: What the high rack offers to group: a turret, a launcher, or nothing
        data["hardpoint"] = hardpoint_name(module.hardpoint)
        data["isMutated"] = bool(getattr(module, "isMutated", False))
        if getattr(module, "isMutated", False):
            data["baseItemId"] = module.baseItemID
            data["mutaplasmidId"] = module.mutaplasmidID
            data["mutations"] = {
                str(mutator.attrID): mutator.value for mutator in module.mutators.values()
            }
        spoolType = getattr(module, "spoolType", None)
        if spoolType is not None:
            data["spool"] = {"type": int(spoolType), "amount": module.spoolAmount}
        rahPattern = getattr(module, "rahPatternOverride", None)
        if rahPattern:
            data["rahPattern"] = rahPattern
        data["isValidState"] = bool(module.isValidState(module.state))
        try:
            data["maxRange"] = module.maxRange
        except Exception:
            data["maxRange"] = None
    return data


def serialize_drone(drone):
    data = {
        "itemId": drone.itemID,
        "item": serialize_item(drone.item),
        "amount": drone.amount,
        "amountActive": drone.amountActive,
    }
    if getattr(drone, "isMutated", False):
        data["isMutated"] = True
        data["baseItemId"] = drone.baseItemID
        data["mutaplasmidId"] = drone.mutaplasmidID
        data["mutations"] = {str(m.itemID if hasattr(m, "itemID") else m.attrID): m.value
                             for m in drone.mutators.values()}
    try:
        data["ehp"] = drone.getEhp()
    except Exception:
        pass
    return data


def serialize_fighter(fighter):
    return {
        "itemId": fighter.itemID,
        "item": serialize_item(fighter.item),
        "amount": fighter.amount,
        "active": bool(fighter.active),
        "abilities": [
            {"effectId": ability.effectID, "name": getattr(ability, "name", None), "active": bool(ability.active)}
            for ability in getattr(fighter, "abilities", [])
        ],
    }


def serialize_cargo(cargo):
    return {
        "itemId": cargo.itemID,
        "item": serialize_item(cargo.item),
        "amount": cargo.amount,
    }


def serialize_implant(implant):
    return {
        "itemId": implant.itemID,
        "item": serialize_item(implant.item),
        "active": bool(implant.active),
    }


def serialize_booster(booster):
    return {
        "itemId": booster.itemID,
        "item": serialize_item(booster.item),
        "active": bool(booster.active),
        "sideEffects": [
            {"effectId": effect.effectID, "active": bool(effect.active)}
            for effect in getattr(booster, "sideEffects", [])
        ],
    }


def serialize_damage_pattern(pattern):
    if pattern is None:
        return None
    return {
        "id": getattr(pattern, "ID", None),
        "name": getattr(pattern, "name", None),
        "em": getattr(pattern, "emAmount", 0),
        "thermal": getattr(pattern, "thermalAmount", 0),
        "kinetic": getattr(pattern, "kineticAmount", 0),
        "explosive": getattr(pattern, "explosiveAmount", 0),
    }


def serialize_target_profile(profile):
    if profile is None:
        return None
    return {
        "id": getattr(profile, "ID", None),
        "name": getattr(profile, "name", None),
        "em": getattr(profile, "emAmount", 0),
        "thermal": getattr(profile, "thermalAmount", 0),
        "kinetic": getattr(profile, "kineticAmount", 0),
        "explosive": getattr(profile, "explosiveAmount", 0),
        "hp": getattr(profile, "hp", None),
    }


def serialize_character(character):
    if character is None:
        return None
    return {
        "id": character.ID,
        "name": character.name,
        "isDefault": bool(getattr(character, "isDefault", False)) if hasattr(character, "isDefault") else False,
    }


def ship_slots(fit):
    """Slot and hardpoint counts, so the UI can draw empty slots."""
    counts = {}
    for slot, name in SLOT_NAMES.items():
        try:
            counts[name] = int(fit.getNumSlots(slot) or 0)
        except Exception:
            counts[name] = 0
    counts["turretHardpoints"] = int(fit.ship.getModifiedItemAttr("turretSlotsLeft") or 0)
    counts["launcherHardpoints"] = int(fit.ship.getModifiedItemAttr("launcherSlotsLeft") or 0)
    return counts


def fit_racks(fit):
    """Modules grouped into the racks the fitting view draws."""
    racks = {name: [] for name in RACK_ORDER}
    for position, module in enumerate(fit.modules):
        name = slot_name(module.slot)
        racks.setdefault(name, []).append(serialize_module(module, position))
    return racks


def serialize_projection(fit, other, kind):
    """A projected-onto / command relationship between two fits."""
    info = fit.getProjectionInfo(other.ID) if kind == "projected" else fit.getCommandInfo(other.ID)
    entry = {
        "fitId": other.ID,
        "name": other.name,
        "shipId": other.shipID,
        "shipName": other.ship.item.name if other.ship and other.ship.item else None,
        "shipIconId": _icon_id(other.ship.item) if other.ship else None,
    }
    if info is not None:
        entry["state"] = state_name(getattr(info, "state", FittingModuleState.OFFLINE))
        amount = getattr(info, "amount", None)
        if amount is not None:
            entry["amount"] = amount
        projectionRange = getattr(info, "projectionRange", None)
        if projectionRange is not None:
            entry["projectionRange"] = projectionRange
        for attr in ("commandLinkState", "commandFitState"):
            value = getattr(info, attr, None)
            if value is not None:
                entry[attr] = value
    return entry


def serialize_fit(fit, includeStats=True, statsSections=None):
    """The full payload the fitting view needs."""
    shipItem = fit.ship.item if fit.ship is not None else None
    payload = {
        "id": fit.ID,
        "name": fit.name,
        "notes": fit.notes,
        "booster": bool(fit.booster),
        "created": _iso(fit.created),
        "modified": _iso(fit.modified),
        "timestamp": fit.timestamp,
        "calculated": bool(fit.calculated),
        "factorReload": bool(getattr(fit, "factorReload", False)),
        "ignoreRestrictions": bool(getattr(fit, "ignoreRestrictions", False)),
        "implantLocation": int(getattr(fit, "implantLocation", ImplantLocation.FIT)),
        "systemSecurity": int(getattr(fit, "systemSecurity", 0) or 0),
        "pilotSecurity": getattr(fit, "pilotSecurity", None),
        "isStructure": bool(fit.isStructure),
        "ship": {
            "id": fit.shipID,
            "item": serialize_item(shipItem),
            "slots": ship_slots(fit) if fit.ship is not None else {},
        },
        "character": serialize_character(fit.character),
        "damagePattern": serialize_damage_pattern(fit.damagePattern),
        "targetProfile": serialize_target_profile(fit.targetProfile),
        "racks": fit_racks(fit),
        "drones": [serialize_drone(drone) for drone in fit.drones],
        "fighters": [serialize_fighter(fighter) for fighter in fit.fighters],
        "cargo": [serialize_cargo(cargo) for cargo in fit.cargo],
        "implants": [serialize_implant(implant) for implant in fit.implants],
        "appliedImplants": [serialize_implant(implant) for implant in fit.appliedImplants],
        "boosters": [serialize_booster(booster) for booster in fit.boosters],
        "projected": {
            "modules": [serialize_module(module) for module in fit.projectedModules],
            "drones": [serialize_drone(drone) for drone in fit.projectedDrones],
            "fighters": [serialize_fighter(fighter) for fighter in fit.projectedFighters],
            "fits": [serialize_projection(fit, other, "projected") for other in fit.projectedFits],
            "commandFits": [serialize_projection(fit, other, "command") for other in fit.commandFits],
        },
        "modCount": fit.modCount,
    }
    mode = getattr(fit, "mode", None)
    if mode is not None and getattr(mode, "item", None) is not None:
        payload["mode"] = {"itemId": mode.item.ID, "item": serialize_item(mode.item)}
    if includeStats:
        payload["stats"] = build_stats(fit, sections=statsSections)
    return payload


def serialize_fit_summary(fit):
    """The lightweight row used in lists."""
    shipItem = fit.ship.item if fit.ship is not None else None
    return {
        "id": fit.ID,
        "name": fit.name,
        "booster": bool(fit.booster),
        "shipId": fit.shipID,
        "shipName": shipItem.name if shipItem is not None else None,
        "shipIconId": _icon_id(shipItem),
        "shipGraphicId": _graphic_id(shipItem),
        "shipImage": item_image(shipItem),
        "modified": _iso(fit.modifiedCoalesce),
        "notes": fit.notes,
    }


def _iso(value):
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)
