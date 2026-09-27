"""JSON API.

Endpoints under ``/api`` run with the caller's engine context bound (see
:mod:`web.deps`), so the service layer transparently reads and writes that user's
own database.

The event stream is the exception: it is a long-lived connection and therefore
must not hold the user's lock, so it lives on its own router.
"""

from fastapi import APIRouter, Depends

from web.api import auth, commands, esi, events, fits, items, meta, ships
from web.deps import user_context

#: Everything that touches the database, one user at a time
api = APIRouter(prefix="/api", dependencies=[Depends(user_context)])

api.include_router(meta.router)
api.include_router(auth.router)
api.include_router(ships.router)
api.include_router(fits.router)
api.include_router(items.router)
api.include_router(commands.router)
api.include_router(esi.router)

#: Long-lived streams
eventsApi = APIRouter(prefix="/api")
eventsApi.include_router(events.router)

__all__ = ["api", "eventsApi"]
