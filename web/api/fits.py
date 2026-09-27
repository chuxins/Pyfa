"""Fits: list, read, create, rename, duplicate, delete.

Editing individual items (modules, drones, cargo...) goes through
:mod:`web.api.commands`, which reuses pyfa's own undoable command objects.
"""

import copy

from fastapi import APIRouter, Depends, HTTPException, Query
from logbook import Logger
from pydantic import BaseModel, Field

from web.deps import get_user_data, require_user
from web.events import publish
from web.services import commands as commandService
from web.services.serialize import serialize_fit, serialize_fit_summary
from web.services.stats import SECTIONS, build_stats

pyfalog = Logger(__name__)

router = APIRouter(prefix="/fits", tags=["fits"])

SECTION_NAMES = tuple(name for name, _ in SECTIONS)


class FitCreate(BaseModel):
    shipId: int
    name: str | None = None


class FitUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    factorReload: bool | None = None
    ignoreRestrictions: bool | None = None


def _service_fit():
    from service.fit import Fit

    return Fit.getInstance()


def _require_fit(fit_id):
    fit = _service_fit().getFit(fit_id)
    if fit is None:
        raise HTTPException(status_code=404, detail="fit not found")
    return fit


@router.get("")
def list_fits(
    shipId: int | None = Query(None),
    q: str | None = Query(None, min_length=1),
    limit: int = Query(200, ge=1, le=1000),
):
    """Fits for a ship, or search results when ``q`` is given."""
    import eos.db

    if q:
        results = _service_fit().searchFits(q)
        fits = []
        for entry in results:
            fitId, name, shipId, shipName, booster, modified, notes = entry
            fits.append({
                "id": fitId,
                "name": name,
                "booster": bool(booster),
                "shipId": shipId,
                "shipName": shipName,
                "modified": modified.isoformat() if modified is not None else None,
                "notes": notes,
            })
        return {"fits": fits[:limit]}

    if shipId is not None:
        records = eos.db.getFitsWithShip(shipId)
    else:
        records = eos.db.getFitList()

    fits = [serialize_fit_summary(fit) for fit in records]
    fits.sort(key=lambda f: (f["modified"] or "", f["name"] or ""), reverse=True)
    return {"fits": fits[:limit], "count": len(fits)}


@router.post("", status_code=201)
def create_fit(payload: FitCreate, user=Depends(require_user)):
    """Create an empty fit for a ship."""
    sFit = _service_fit()
    try:
        fitId = sFit.newFit(payload.shipId, name=payload.name)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        pyfalog.exception("Failed to create fit for ship {}", payload.shipId)
        raise HTTPException(status_code=400, detail=str(ex))
    publish(user.id, "fit.created", fitId=fitId)
    return serialize_fit(sFit.getFit(fitId), includeStats=False)


@router.get("/{fit_id}")
def get_fit(
    fit_id: int,
    sections: str | None = Query(None, description="Comma separated stat section names"),
    stats: bool = Query(True),
):
    fit = _require_fit(fit_id)
    wanted = None
    if sections:
        wanted = [s.strip() for s in sections.split(",") if s.strip() in SECTION_NAMES]
    return serialize_fit(fit, includeStats=stats, statsSections=wanted)


@router.get("/{fit_id}/stats")
def get_fit_stats(fit_id: int, sections: str | None = Query(None)):
    fit = _require_fit(fit_id)
    wanted = None
    if sections:
        wanted = [s.strip() for s in sections.split(",") if s.strip() in SECTION_NAMES]
    return {"id": fit.ID, "stats": build_stats(fit, sections=wanted)}


@router.patch("/{fit_id}")
def update_fit(fit_id: int, payload: FitUpdate, user=Depends(require_user)):
    """Rename a fit, edit its notes, or toggle its flags."""
    import eos.db

    fit = _require_fit(fit_id)
    changed = []
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        fit.name = name
        changed.append("name")
    if payload.notes is not None:
        fit.notes = payload.notes
        changed.append("notes")
    if payload.factorReload is not None:
        fit.factorReload = payload.factorReload
        changed.append("factorReload")
    if payload.ignoreRestrictions is not None:
        fit.ignoreRestrictions = payload.ignoreRestrictions
        changed.append("ignoreRestrictions")
    if not changed:
        raise HTTPException(status_code=400, detail="nothing to update")

    eos.db.commit()
    sFit = _service_fit()
    if any(field in changed for field in ("factorReload", "ignoreRestrictions")):
        sFit.recalc(fit)
        sFit.fill(fit)
    publish(user.id, "fit.changed", fitIds=[fit_id], action="update")
    return serialize_fit(fit, includeStats=False)


@router.post("/{fit_id}/duplicate", status_code=201)
def duplicate_fit(fit_id: int, user=Depends(require_user)):
    """Copy a fit; the copy is owned by the same user."""
    import eos.db

    fit = _require_fit(fit_id)
    clone = copy.deepcopy(fit)
    clone.name = "{} (copy)".format(fit.name)
    eos.db.save(clone)
    publish(user.id, "fit.created", fitId=clone.ID)
    return serialize_fit_summary(clone)


@router.delete("/{fit_id}", status_code=204)
def delete_fit(fit_id: int, user=Depends(require_user), userData=Depends(get_user_data)):
    _require_fit(fit_id)
    _service_fit().deleteFit(fit_id)
    # The engine only forgets its own per-fit stack; ours is keyed per user, so
    # without this the deleted fit's commands would outlive it, and a later fit
    # reusing the id would inherit them.
    commandService.clear_history(userData, fit_id)
    publish(user.id, "fit.removed", fitIds=[fit_id])
    return None
