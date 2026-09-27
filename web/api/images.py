"""Serves game icons and ship renders out of pyfa's ``imgs/`` directory.

These requests deliberately bypass the engine: they need no database and are the
bulk of the traffic, so they are mounted outside the ``/api`` router (see
:mod:`web.main`) and answered straight from disk with long-lived caching.
"""

import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from web.deps import AppState, get_app_state
from fastapi import Depends

router = APIRouter(tags=["images"])

#: ``iconID`` or ``graphicID``; ``@1x``/``@2x`` are picked with ``size``
_NAME_PATTERN = re.compile(r"^\d+$")

KINDS = {
    "icons": "icons",
    "renders": "renders",
    "gui": "gui",
}

# A year: images change only when EVE's static data is rebuilt
CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.get("/img/{kind}/{image_id}")
def get_image(
    kind: str,
    image_id: str,
    size: int = Query(1, ge=1, le=2),
    state: AppState = Depends(get_app_state),
):
    directory = KINDS.get(kind)
    if directory is None:
        raise HTTPException(status_code=404, detail="unknown image kind")

    # Allow "123@2x" style ids as well as ?size=2
    if "@" in image_id:
        image_id, _, suffix = image_id.partition("@")
        if suffix.endswith("x") and suffix[:-1].isdigit():
            size = int(suffix[:-1])
    if not _NAME_PATTERN.match(image_id):
        raise HTTPException(status_code=404, detail="bad image id")

    root = state.config.imgs_dir / directory
    # Some ui assets live in subdirectories, so a plain id is tried at the top level
    candidates = [
        root / "{}@{}x.png".format(image_id, size),
        root / "{}.png".format(image_id),
    ]
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            return FileResponse(resolved, headers={"Cache-Control": CACHE_CONTROL})
    raise HTTPException(status_code=404, detail="image not found")
