"""Server and game-data information."""

from fastapi import APIRouter, Depends, Request

import config as pyfaConfig
from web.deps import AppState, current_user, get_app_state

router = APIRouter(tags=["meta"])


@router.get("/meta")
def get_meta(request: Request, state: AppState = Depends(get_app_state)):
    """Version and capability info; the browser calls this on startup."""
    import eos.config

    user = current_user(request)
    return {
        "pyfaVersion": pyfaConfig.getVersion(),
        "webVersion": request.app.version,
        "language": pyfaConfig.language,
        "gamedata": {
            "build": eos.config.gamedata_version,
            "date": eos.config.gamedata_date,
        },
        "sso": {
            "server": state.config.sso.server,
            "configured": state.config.sso.configured,
            # Only a signed-in client is told about the development bypass: an
            # anonymous caller has no use for it, and on a deployment where it was
            # left on by mistake the flag is an invitation.
            "devBypass": state.config.dev_auth_bypass if user is not None else False,
        },
        "user": None if user is None else {
            "id": user.id,
            "characterId": user.character_id,
            "characterName": user.character_name,
        },
    }
