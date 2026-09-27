"""Ship browser: the class tree, ship search, and per-ship detail."""

from fastapi import APIRouter, HTTPException, Query
from logbook import Logger

from web.services.serialize import display_name, item_image, serialize_fit_summary, serialize_item

pyfalog = Logger(__name__)

router = APIRouter(prefix="/ships", tags=["ships"])

#: Slot attributes as they appear on a ship type, in rack order
SLOT_ATTRIBUTES = (
    ("high", "hiSlots"),
    ("med", "medSlots"),
    ("low", "lowSlots"),
    ("rig", "rigSlots"),
    ("subsystem", "maxSubSystems"),
    ("service", "serviceSlots"),
    ("fighterLight", "fighterLightSlots"),
    ("fighterSupport", "fighterSupportSlots"),
    ("fighterHeavy", "fighterHeavySlots"),
    ("standupLight", "fighterStandupLightSlots"),
    ("standupSupport", "fighterStandupSupportSlots"),
    ("standupHeavy", "fighterStandupHeavySlots"),
)


def ship_slots(item):
    """How many slots of each kind a ship has."""
    layout = {}
    for name, attribute in SLOT_ATTRIBUTES:
        value = item.getAttribute(attribute) if hasattr(item, "getAttribute") else None
        layout[name] = int(value or 0)
    for name, attribute in (("turret", "turretSlotsLeft"), ("launcher", "launcherSlotsLeft")):
        value = item.getAttribute(attribute) if hasattr(item, "getAttribute") else None
        layout[name] = int(value or 0)
    return layout


def ship_summary(item, fitCount=None):
    summary = {
        "id": item.ID,
        "name": item.name,
        "iconId": getattr(item, "iconID", None),
        "graphicId": getattr(item, "graphicID", None),
        "image": item_image(item),
    }
    if fitCount is not None:
        summary["fitCount"] = fitCount
    return summary


@router.get("/tree")
def get_tree():
    """Ships grouped by group, grouped by category.

    Mirrors the desktop ship browser's root: every group in the Ship and
    Structure categories, with the ships that are published.

    ``name`` is whatever the engine calls the category/group in the server's
    language; ``key`` stays English so the client has something stable to sort and
    remember expand/collapse state by.

    ``fitCount`` is how many fits of this user's own database use the ship, counted in
    one query for the whole tree. It is what lets the browser offer the fits under the
    ship they belong to (see ``ShipBrowser.vue``), and it is the reason the tree is not
    cached per server.
    """
    import eos.db
    from service.market import Market

    market = Market.getInstance()
    groups = market.getShipRoot()
    fitCounts = dict(eos.db.countFitGroupedByShip())

    byCategory = {}
    for group in groups:
        category = getattr(group, "category", None)
        key = getattr(category, "name", None) or "Other"
        ships = []
        for item in market.getShipList(group.ID):
            if not market.getPublicityByItem(item):
                continue
            ships.append(ship_summary(item, fitCounts.get(item.ID, 0)))
        if not ships:
            continue
        ships.sort(key=lambda s: s["name"] or "")
        byCategory.setdefault(key, {
            "key": key,
            "name": display_name(category) or key,
            "groups": [],
        })["groups"].append({
            "id": group.ID,
            "name": display_name(group) or key,
            "ships": ships,
        })

    for entry in byCategory.values():
        entry["groups"].sort(key=lambda g: g["name"] or "")

    return {
        # Ships first, then structures and whatever else, all alphabetical
        "categories": [
            byCategory[key] for key in sorted(byCategory, key=lambda k: (k != "Ship", k))
        ]
    }


@router.get("/search")
def search_ships(q: str = Query(..., min_length=1), limit: int = Query(40, ge=1, le=200)):
    from service.market import Market

    market = Market.getInstance()
    ships = market.searchShips(q)
    results = [ship_summary(item) for item in ships]
    results.sort(key=lambda s: s["name"] or "")
    return {"results": results[:limit]}


@router.get("/{ship_id}")
def get_ship(ship_id: int):
    """Ship detail plus the fits this user has for it."""
    import eos.db
    from service.market import Market

    market = Market.getInstance()
    item = market.getItem(ship_id, eager=("group.category", "attributes"))
    if item is None:
        raise HTTPException(status_code=404, detail="ship not found")

    fits = []
    try:
        for fit in eos.db.getFitsWithShip(ship_id):
            fits.append(serialize_fit_summary(fit))
        fits.sort(key=lambda f: (f["modified"] or "", f["name"] or ""), reverse=True)
    except Exception:
        pyfalog.exception("Failed to list fits for ship {}", ship_id)

    return {
        "ship": serialize_item(item, detail=True),
        "slots": ship_slots(item),
        "fits": fits,
    }
