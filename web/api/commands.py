"""Fit editing endpoints.

One endpoint runs any registered edit command; separate ones undo and redo. Every
response carries the fit and its undo state, so the browser can redraw without a
second round trip.

An edit the engine refuses is a 409 whose ``detail`` is ``{message, code, params}``:
English text for the log, plus the reason and its values so the browser can say the
same thing in the reader's language (see ``web/services/commands.py``).
"""

from fastapi import APIRouter, Depends, HTTPException
from logbook import Logger
from pydantic import BaseModel, Field

from web.deps import UserData, get_user_data, require_user
from web.events import publish
from web.services import commands as commandService
from web.services.serialize import serialize_fit
from web.userdb import User

pyfalog = Logger(__name__)

router = APIRouter(tags=["commands"])


class CommandRequest(BaseModel):
    command: str = Field(..., description="Name from GET /api/commands")
    args: dict = Field(default_factory=dict, description="Command arguments")


def _run(user: User, userData: UserData, fitId: int, action):
    """Execute ``action`` and return the refreshed fit plus its undo state."""
    try:
        history = action()
    except commandService.CommandError as ex:
        raise HTTPException(status_code=ex.status_code, detail=str(ex))
    except commandService.CommandFailed as ex:
        raise HTTPException(status_code=409, detail=ex.detail())
    except HTTPException:
        raise
    except Exception as ex:
        pyfalog.exception("Edit command failed for fit {}", fitId)
        raise HTTPException(status_code=500, detail="{}: {}".format(type(ex).__name__, ex))

    from service.fit import Fit

    fit = Fit.getInstance().getFit(fitId)
    if fit is None:
        raise HTTPException(status_code=404, detail="fit not found")
    payload = serialize_fit(fit, includeStats=True)
    payload["history"] = history
    return payload


@router.get("/commands")
def list_commands(user=Depends(require_user)):
    """Every edit command this server accepts, with its arguments."""
    return {"commands": commandService.available_commands()}


@router.post("/fits/{fit_id}/commands")
def run_command(
    fit_id: int,
    payload: CommandRequest,
    user: User = Depends(require_user),
    userData: UserData = Depends(get_user_data),
):
    """Run one edit command, e.g. add a module or toggle a state."""
    return _run(user, userData, fit_id, lambda: commandService.execute(
        userData, user.id, fit_id, payload.command, payload.args))


@router.post("/fits/{fit_id}/undo")
def undo(
    fit_id: int,
    user: User = Depends(require_user),
    userData: UserData = Depends(get_user_data),
):
    """Undo the last edit of this fit for this user."""
    return _run(user, userData, fit_id, lambda: commandService.undo(userData, user.id, fit_id))


@router.post("/fits/{fit_id}/redo")
def redo(
    fit_id: int,
    user: User = Depends(require_user),
    userData: UserData = Depends(get_user_data),
):
    """Redo the last undone edit."""
    return _run(user, userData, fit_id, lambda: commandService.redo(userData, user.id, fit_id))


@router.get("/fits/{fit_id}/history")
def history(
    fit_id: int,
    user: User = Depends(require_user),
    userData: UserData = Depends(get_user_data),
):
    """Undo/redo state of a fit."""
    return commandService.history_for(userData, fit_id)


@router.delete("/fits/{fit_id}/history", status_code=204)
def clear_history(
    fit_id: int,
    user: User = Depends(require_user),
    userData: UserData = Depends(get_user_data),
):
    """Forget the undo history (used when the fit is saved/closed)."""
    commandService.clear_history(userData, fit_id)
    return None


@router.get("/fits/{fit_id}/charge-targets")
def charge_targets(
    fit_id: int,
    chargeItemId: int,
    user: User = Depends(require_user),
):
    """Which fitted modules can load this charge.

    The desktop shows this as the "load ammo into..." menu; the browser needs it
    to decide what clicking a charge in the market should do.
    """
    from service.fit import Fit
    from service.market import Market

    fit = Fit.getInstance().getFit(fit_id)
    if fit is None:
        raise HTTPException(status_code=404, detail="fit not found")

    charge = Market.getInstance().getItem(chargeItemId)
    if charge is None:
        raise HTTPException(status_code=404, detail="charge not found")

    targets = []
    for position, module in enumerate(fit.modules):
        if module.isEmpty:
            continue
        try:
            if module.isValidCharge(charge):
                targets.append({
                    "position": position,
                    "itemId": module.itemID,
                    "name": module.item.name if module.item else None,
                    "item": None if module.item is None else {
                        "id": module.item.ID,
                        "name": module.item.name,
                        "image": None,
                    },
                })
        except Exception:
            pyfalog.exception("Failed to check charge validity for position {}", position)
    return {"fitId": fit_id, "chargeItemId": chargeItemId, "targets": targets}


@router.post("/fits/{fit_id}/reset", status_code=204)
def reset_fit(
    fit_id: int,
    user: User = Depends(require_user),
    userData: UserData = Depends(get_user_data),
):
    """Strip everything off a fit, leaving the hull. One undo step."""
    from web.services.composite import ClearFitCommand

    command = ClearFitCommand(fit_id)
    processor = commandService.processor_for(userData, fit_id)
    from web.events import publishing_as

    with publishing_as(user.id):
        success = processor.Submit(command)
    if not success:
        # Nothing to remove is not an error, but the fit must exist
        from service.fit import Fit

        if Fit.getInstance().getFit(fit_id) is None:
            raise HTTPException(status_code=404, detail="fit not found")
    publish(user.id, "fit.changed", fitIds=[fit_id], action="reset")
    return None
