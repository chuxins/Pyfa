"""The fittings a pilot has saved in game, brought into pyfa.

ESI's character fittings endpoint answers with the fittings saved in the EVE client
-- the same list the desktop's "Browse EVE Fittings" window shows. Turning one into a
fit is already pyfa's own job (``service.port.esi.importESI``, reached through
``Port.importFitFromBuffer``), so what is added here is only what a server needs:
finding the tokens a login left behind, calling ESI, and not importing the same
fitting twice.

The tokens come from the SSO login, not from anywhere else: :mod:`web.auth` writes an
``SsoCharacter`` row -- encrypted refresh token included -- into the pilot's own
database when they sign in, and ``Esi.getFittings`` reads it back out of there. That
is the desktop's own object, so an access token that has expired is refreshed by
pyfa's own code; the refreshed row is written back below, which is the part the
desktop does from its token validation thread instead.
"""

import json
from collections import Counter

import eos.db
from logbook import Logger

from web.services.serialize import serialize_fit_summary

pyfalog = Logger(__name__)

#: Why one of a pilot's in-game fittings did not arrive. The browser translates them.
ALREADY_IMPORTED = "alreadyImported"
UNKNOWN_SHIP = "unknownShip"
UNREADABLE = "unreadable"


class EsiError(Exception):
    """A failure with a code the browser can translate, and the status to answer with.

    ``noCharacter``/``tokenRefused`` mean the pilot has to sign in again (409), a
    failure at EVE's end is a gateway error (502), and an answer this code cannot make
    sense of is ours to look at (500).
    """

    def __init__(self, code, message, status=502, params=None):
        super().__init__(message)
        self.code = code
        self.status = status
        #: Values interpolated into the sentence by name
        self.params = dict(params or {})


def _esi():
    """pyfa's ESI service, imported lazily so a test can stand in for it."""
    from service.esi import Esi

    return Esi.getInstance()


def fetch_fittings(character):
    """The fittings this pilot has saved in game, as ESI reports them.

    ``Esi.getFittings`` takes the id of the ``SsoCharacter`` *row* rather than the EVE
    character id: it looks the row up itself and answers with parsed JSON. It also
    refreshes the access token when it has expired, which is why the caller writes the
    row back afterwards.
    """
    import requests

    from service.esiAccess import APIException, GenericSsoError

    try:
        return _esi().getFittings(character.ID)
    except APIException as ex:
        raise EsiError(
            "esiRefused", "EVE refused to hand over the fittings: {}".format(ex),
            params={"reason": str(ex)}) from ex
    except GenericSsoError as ex:
        raise EsiError(
            "tokenRefused", "EVE did not accept the stored login: {}".format(ex),
            status=409) from ex
    except requests.exceptions.RequestException as ex:
        raise EsiError(
            "esiUnreachable", "EVE could not be reached: {}".format(ex)) from ex


def find_character(user, server_name):
    """The ``SsoCharacter`` row a login left in this user's database, if there is one.

    Matched by EVE character id, because that is what the account row and the SSO row
    have in common: the row's own id is local to the database, so the desktop's ids
    mean nothing here. A database holding exactly one character -- a desktop
    ``saveddata.db`` adopted with ``web.admin import-db``, say -- is accepted too, but
    an ambiguous one is not guessed at.
    """
    import config as pyfaConfig
    from eos.saveddata.ssocharacter import SsoCharacter

    rows = eos.db.saveddata_session.query(SsoCharacter).filter(
        SsoCharacter.client == pyfaConfig.getClientSecret(),
        SsoCharacter.server == server_name,
    ).all()
    for row in rows:
        if int(row.characterID) == int(user.character_id):
            return row
    if len(rows) == 1:
        return rows[0]
    return None


def import_character_fittings(user, server_name):
    """Fetch this account's in-game fittings and import them.

    Returns the payload ``POST /api/esi/fittings/import`` answers with. Raises
    :class:`EsiError` when there is nothing to fetch with, or when EVE does not
    answer.
    """
    character = find_character(user, server_name)
    if character is None:
        raise EsiError(
            "noCharacter",
            "No {} character with stored EVE tokens is available to this account; sign "
            "in with EVE again and retry.".format(server_name),
            status=409,
            params={"server": server_name},
        )

    fittings = fetch_fittings(character)
    # An expired access token was refreshed on the way through, and that new token only
    # exists in memory until it is written down.
    eos.db.save(character)

    if not isinstance(fittings, list):
        raise EsiError(
            "esiUnusable",
            "EVE did not answer with a list of fittings, so none were imported",
            status=500,
        )
    return import_fittings(fittings, character)


def import_fittings(fittings, character):
    """Turn ESI's fittings into this user's fits, under the ship each one belongs to."""
    from service.fit import Fit as ServiceFit
    from service.port.port import Port

    sFit = ServiceFit.getInstance()
    #: What the pilot already has, so pressing the button twice does not double every
    #: fitting. Counted rather than treated as a set, so that a second copy in EVE of a
    #: fit the pilot also has in pyfa is still imported.
    stored = Counter((fit.shipID, _name(fit.name)) for fit in eos.db.getFitListLite())
    matched = Counter()

    imported = []
    skipped = []

    for entry in fittings:
        if not isinstance(entry, dict):
            skipped.append(_skip("", 0, UNREADABLE))
            continue
        shipId = _as_int(entry.get("ship_type_id"))
        name = (entry.get("name") or "").strip()
        key = (shipId, _name(name))
        if eos.db.getItem(shipId) is None:
            skipped.append(_skip(name, shipId, UNKNOWN_SHIP))
            continue
        if stored[key] > matched[key]:
            matched[key] += 1
            skipped.append(_skip(name, shipId, ALREADY_IMPORTED))
            continue

        try:
            # pyfa's own ESI import, through the path a pasted fitting takes -- which also
            # sets the character, damage pattern and target profile, and saves the fit.
            _kind, made = Port.importFitFromBuffer(json.dumps(entry))
        except Exception:
            pyfalog.exception(
                "Could not import ESI fitting {!r} for ship {} of {}", name, shipId, character.characterName)
            skipped.append(_skip(name, shipId, UNREADABLE))
            continue

        for fit in made:
            # Port saved the fit; the numbers the browser reads live on the engine's
            # side, so recalculate the way a newly created fit is calculated.
            sFit.recalc(fit)
            sFit.fill(fit)
            entry_payload = dict(serialize_fit_summary(fit))
            entry_payload["esiFittingId"] = entry.get("fitting_id")
            imported.append(entry_payload)

    if imported:
        eos.db.commit()

    pyfalog.info(
        "Imported {} of {} ESI fittings for {} ({} skipped)",
        len(imported), len(fittings), character.characterName, len(skipped))

    return {
        "character": {
            "id": int(character.characterID),
            "name": character.characterName,
            "server": character.server,
        },
        "total": len(fittings),
        "imported": imported,
        "skipped": skipped,
    }


def _name(value):
    return (value or "").strip().casefold()


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _skip(name, shipId, reason):
    return {"name": name, "shipId": shipId, "reason": reason}
