"""Items: search, detail, attributes, charges and variations.

These back the market browser, the item-stats panel and the "pick ammo" /
"change variation" menus.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from logbook import Logger

from web.deps import get_user_data, require_user
from web.services.search import SCOPES, search_items
from web.services.serialize import display_name, serialize_item

pyfalog = Logger(__name__)

router = APIRouter(prefix="/items", tags=["items"])


def _market():
    from service.market import Market

    return Market.getInstance()


def _get_item(item_id, detail=False):
    item = _market().getItem(item_id, eager=("group.category", "metaGroup", "attributes"))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


def _attribute_rows(item):
    rows = []
    for attribute in getattr(item, "attributes", {}).values():
        if not getattr(attribute, "published", True):
            continue
        unit = getattr(attribute, "unit", None)
        rows.append({
            "id": attribute.ID,
            "name": attribute.name,
            "displayName": display_name(getattr(attribute, "info", None)) or attribute.name,
            "value": attribute.value,
            "unit": display_name(unit),
            "highIsGood": bool(getattr(attribute, "highIsGood", False)),
            "description": getattr(attribute, "description", None),
        })
    rows.sort(key=lambda row: (row["displayName"] or "").lower())
    return rows


def _modified_attribute_rows(modified):
    """Attribute rows for an item as modified by a fit.

    Only published attributes are listed. The unpublished ones have no name in the game
    data to show -- they read as ``accuracyBonus``, in English, in the middle of a
    Chinese panel -- and pyfa's own item window hides them too (see
    ``gui/builtinItemStatsViews/itemAttributes.py``, whose plain view is the one the
    browser panel mirrors).
    """
    from eos.db import getAttributeInfo

    rows = []
    for name in modified:
        try:
            value = modified[name]
        except Exception:
            continue
        info = getAttributeInfo(name)
        if info is None or not info.published:
            continue
        rows.append({
            "name": name,
            "id": info.ID,
            "displayName": display_name(info) or name,
            "value": value,
            "baseValue": modified.getOriginal(name),
            "unit": display_name(getattr(info, "unit", None)),
            "highIsGood": bool(getattr(info, "highIsGood", False)),
        })
    rows.sort(key=lambda row: (row["displayName"] or "").lower())
    return rows


#: The rows a fit keeps things in, as the browser names them (see ``FittedKind`` in
#: ``web/frontend/src/api.ts``). A module's loaded charge is not one of them: it is
#: reached through the module it sits in.
FITTED_KINDS = ("module", "drone", "fighter", "cargo", "implant", "booster")


def _fitted_modified_attributes(fit, kind, position, item_id):
    """One row of a fit's attribute values, as the fit has modified them.

    A click in the fitting view says what it was on: the kind of row, where in that row
    list, and which item it expects to find there. That last part matters -- a click on a
    module's loaded charge asks about the charge, and answering with the module's numbers
    (or the other way round) is worse than saying no.
    """
    if kind == "moduleCharge":
        return _fitted_charge_attributes(fit, position, item_id)
    if kind not in FITTED_KINDS:
        raise HTTPException(
            status_code=400,
            detail="kind must be one of {}, or moduleCharge".format(", ".join(FITTED_KINDS)))
    rows = {
        "module": list(fit.modules),
        "drone": list(fit.drones),
        "fighter": list(fit.fighters),
        "cargo": list(fit.cargo),
        "implant": list(fit.implants),
        "booster": list(fit.boosters),
    }[kind]
    if position < 0 or position >= len(rows):
        raise HTTPException(status_code=400, detail="position out of range")
    entry = rows[position]
    item = getattr(entry, "item", None)
    if item is None or getattr(entry, "isEmpty", False):
        raise HTTPException(status_code=400, detail="nothing in that slot")
    if item.ID != item_id:
        raise HTTPException(status_code=400, detail="no such item in that slot")
    return entry.itemModifiedAttributes


def _fitted_charge_attributes(fit, position, item_id):
    """The values of the charge loaded in one of a fit's modules."""
    if position < 0 or position >= len(fit.modules):
        raise HTTPException(status_code=400, detail="position out of range")
    module = fit.modules[position]
    charge = getattr(module, "charge", None)
    # ``Module.charge`` is the charge *type* itself (an Item), not a fitted wrapper
    if charge is None or charge.ID != item_id:
        raise HTTPException(status_code=400, detail="no charge in that module")
    return module.chargeModifiedAttributes


@router.get("/search")
def search(q: str = Query(..., min_length=1), scope: str = Query("market"), limit: int = Query(50, ge=1, le=200)):
    if scope not in SCOPES:
        raise HTTPException(status_code=400, detail="scope must be one of {}".format(", ".join(SCOPES)))
    results = search_items(q, scope=scope, limit=limit)
    return {"query": q, "scope": scope, "results": [serialize_item(item) for item in results]}


@router.get("/{item_id}")
def get_item(item_id: int):
    item = _get_item(item_id, detail=True)
    data = serialize_item(item, detail=True)
    metaGroup = getattr(item, "metaGroup", None)
    if metaGroup is not None:
        data["metaGroupId"] = metaGroup.ID
    return data


@router.get("/{item_id}/attributes")
def get_attributes(
    item_id: int,
    fitId: int | None = Query(None, description="Show attributes as modified by this fit"),
    position: int | None = Query(None, description="Which row of the fit to read, see kind"),
    kind: str = Query(
        "module",
        description="What that row is: {} or moduleCharge for a module's loaded charge".format(
            ", ".join(FITTED_KINDS))),
    userData=Depends(get_user_data),
):
    """Published attributes of an item, optionally as modified inside a fit.

    Without ``fitId`` the answer is the type's own values, which is what the item browser
    shows. With one -- and the row a click was on -- it is what the fit makes of that
    item, the same numbers the fitting engine works with.
    """
    item = _get_item(item_id)

    if fitId is not None and position is not None:
        from service.fit import Fit

        fit = Fit.getInstance().getFit(fitId)
        if fit is None:
            raise HTTPException(status_code=404, detail="fit not found")
        return {
            "itemId": item_id,
            "kind": kind,
            "modified": True,
            "rows": _modified_attribute_rows(
                _fitted_modified_attributes(fit, kind, position, item_id)),
        }

    return {"itemId": item_id, "modified": False, "rows": _attribute_rows(item)}


@router.get("/{item_id}/charges")
def get_charges(
    item_id: int,
    fitId: int | None = Query(None),
    position: int | None = Query(None),
):
    """Charges that can be loaded into this module, when relevant."""
    item = _get_item(item_id)
    if not item.isModule:
        return {"charges": []}

    from eos.saveddata.module import Module

    charges = []
    if fitId is not None and position is not None:
        from service.fit import Fit

        fit = Fit.getInstance().getFit(fitId)
        if fit is None or position >= len(fit.modules):
            raise HTTPException(status_code=404, detail="module not found in fit")
        module = fit.modules[position]
        if module.isEmpty:
            return {"charges": []}
        charges = module.getValidCharges()
    else:
        try:
            from eos.saveddata.module import Module as ModuleModel

            module = ModuleModel(item)
            charges = module.getValidCharges()
        except Exception:
            pyfalog.exception("Failed to work out valid charges for {}", item_id)
            charges = []

    return {
        "charges": [
            {"item": serialize_item(charge), "amount": None}
            for charge in charges
        ]
    }


@router.get("/{item_id}/variations")
def get_variations(item_id: int, includeCharge: bool = Query(False)):
    """Meta variants of an item, for the "change variation" menu.

    Uses the market service's own lookup, which walks the item's variation parent
    the same way the desktop's "change variation" menu does.
    """
    item = _get_item(item_id)
    variants = _market().getVariationsByItems([item])
    variations = [serialize_item(variant) for variant in variants]
    if includeCharge and item.isModule:
        from eos.saveddata.module import Module

        try:
            module = Module(item)
            charges = [charge for charge in module.getValidCharges()]
            if charges:
                variations.extend(
                    serialize_item(variant) for variant in _market().getVariationsByItems(charges))
        except Exception:
            pyfalog.exception("Failed to gather charge variations for {}", item_id)

    seen = {}
    for entry in variations:
        seen[entry["id"]] = entry
    ordered = sorted(seen.values(), key=lambda entry: (entry["name"] or "").lower())
    return {"itemId": item_id, "variations": ordered}


@router.get("/{item_id}/requirements")
def get_requirements(item_id: int):
    """Skills required to use/fit an item."""
    item = _get_item(item_id)
    rows = []
    for skill, level in (item.requiredSkills or {}).items():
        rows.append({"skillId": skill.ID, "name": skill.name, "level": level})
    rows.sort(key=lambda row: row["name"])
    return {"itemId": item_id, "skills": rows}
