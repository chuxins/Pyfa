# =============================================================================
# Copyright (C) 2014 Ryan Holmes
#
# This file is part of pyfa.
#
# pyfa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyfa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyfa.  If not, see <http://www.gnu.org/licenses/>.
# =============================================================================


import json
from collections import defaultdict

from logbook import Logger

from eos.const import FittingModuleState, FittingSlot
from eos.saveddata.cargo import Cargo
from eos.saveddata.citadel import Citadel
from eos.saveddata.drone import Drone
from eos.saveddata.fighter import Fighter
from eos.saveddata.fit import Fit
from eos.saveddata.module import Module
from eos.saveddata.ship import Ship
from gui.fitCommands.helpers import activeStateLimit
from service.fit import Fit as svcFit
from service.market import Market


class ESIExportException(Exception):
    pass


pyfalog = Logger(__name__)

INV_FLAGS = {
    FittingSlot.LOW: 11,
    FittingSlot.MED: 19,
    FittingSlot.HIGH: 27,
    FittingSlot.RIG: 92,
    FittingSlot.SUBSYSTEM: 125,
    FittingSlot.SERVICE: 164
}

INV_FLAG_CARGOBAY = 5
INV_FLAG_DRONEBAY = 87
INV_FLAG_FIGHTER = 158

# ESI names the flags ('HiSlot0', 'DroneBay', 'Cargo'); pyfa's own format -- and
# everything below -- uses EVE's inventory flag ids. Both spellings are accepted when
# importing, so a fitting read from ESI arrives as complete as one pyfa exported.
_FLAG_GROUPS = {
    "HiSlot": INV_FLAGS[FittingSlot.HIGH],
    "MedSlot": INV_FLAGS[FittingSlot.MED],
    "LoSlot": INV_FLAGS[FittingSlot.LOW],
    "RigSlot": INV_FLAGS[FittingSlot.RIG],
    "SubSystemSlot": INV_FLAGS[FittingSlot.SUBSYSTEM],
    "ServiceSlot": INV_FLAGS[FittingSlot.SERVICE],
}

_FLAG_NAMES = {
    "Cargo": INV_FLAG_CARGOBAY,
    "DroneBay": INV_FLAG_DRONEBAY,
    "FighterBay": INV_FLAG_FIGHTER,
}


def _flagId(flag):
    """The inventory flag id for a flag spelled either way; unchanged when unknown."""
    if isinstance(flag, int):
        return flag
    if flag in _FLAG_NAMES:
        return _FLAG_NAMES[flag]
    if isinstance(flag, str):
        if flag.startswith("FighterTube"):
            # A launched squadron sits in a tube rather than in the bay; an import does
            # not care which, it appends the fighter either way
            return INV_FLAG_FIGHTER
        for prefix, base in _FLAG_GROUPS.items():
            if flag.startswith(prefix):
                index = flag[len(prefix):]
                if index.isdigit():
                    return base + int(index)
    return flag


def exportESI(ofit, exportCharges, exportImplants, exportBoosters, callback):
    # A few notes:
    # max fit name length is 50 characters
    # Most keys are created simply because they are required, but bogus data is okay

    nested_dict = lambda: defaultdict(nested_dict)
    fit = nested_dict()
    sFit = svcFit.getInstance()

    # max length is 50 characters
    name = ofit.name[:47] + '...' if len(ofit.name) > 50 else ofit.name
    fit['name'] = name
    fit['ship_type_id'] = ofit.ship.item.ID

    # 2017/03/29 NOTE: "<" or "&lt;" is Ignored
    # fit['description'] = "<pyfa:%d />" % ofit.ID
    fit['description'] = "" if ofit.notes is None else ofit.notes[:397] + '...' if len(ofit.notes) > 400 else ofit.notes
    fit['items'] = []

    slotNum = {}
    charges = {}
    for module in ofit.modules:
        if module.isEmpty:
            continue

        item = nested_dict()
        slot = module.slot

        if slot == FittingSlot.SUBSYSTEM:
            # Order of subsystem matters based on this attr. See GH issue #130
            slot = int(module.getModifiedItemAttr("subSystemSlot"))
            item['flag'] = slot
        else:
            if slot not in slotNum:
                slotNum[slot] = INV_FLAGS[slot]

            item['flag'] = slotNum[slot]
            slotNum[slot] += 1

        item['quantity'] = 1
        item['type_id'] = module.item.ID
        fit['items'].append(item)

        if module.charge and exportCharges:
            if module.chargeID not in charges:
                charges[module.chargeID] = 0
            # `or 1` because some charges (ie scripts) are without qty
            charges[module.chargeID] += module.numCharges or 1

    for cargo in ofit.cargo:
        item = nested_dict()
        item['flag'] = INV_FLAG_CARGOBAY
        item['quantity'] = cargo.amount
        item['type_id'] = cargo.item.ID
        fit['items'].append(item)

    for chargeID, amount in list(charges.items()):
        item = nested_dict()
        item['flag'] = INV_FLAG_CARGOBAY
        item['quantity'] = amount
        item['type_id'] = chargeID
        fit['items'].append(item)

    for drone in ofit.drones:
        item = nested_dict()
        item['flag'] = INV_FLAG_DRONEBAY
        item['quantity'] = drone.amount
        item['type_id'] = drone.item.ID
        fit['items'].append(item)

    for fighter in ofit.fighters:
        item = nested_dict()
        item['flag'] = INV_FLAG_FIGHTER
        item['quantity'] = fighter.amount
        item['type_id'] = fighter.item.ID
        fit['items'].append(item)

    if exportImplants:
        for implant in ofit.implants:
            item = nested_dict()
            item['flag'] = INV_FLAG_CARGOBAY
            item['quantity'] = 1
            item['type_id'] = implant.item.ID
            fit['items'].append(item)

    if exportBoosters:
        for booster in ofit.boosters:
            item = nested_dict()
            item['flag'] = INV_FLAG_CARGOBAY
            item['quantity'] = 1
            item['type_id'] = booster.item.ID
            fit['items'].append(item)

    if len(fit['items']) == 0:
        raise ESIExportException("Cannot export fitting: module list cannot be empty.")

    text = json.dumps(fit)

    if callback:
        callback(text)
    else:
        return text


def importESI(string):

    sMkt = Market.getInstance()
    fitobj = Fit()
    refobj = json.loads(string)
    # Flags decide where an item goes: named ones come from ESI, ids from pyfa's own
    # export. Sorting below needs one or the other, never a mixture.
    items = [dict(item, flag=_flagId(item.get('flag', 0))) for item in refobj['items']]
    # "<" and ">" is replace to "&lt;", "&gt;" by EVE client
    fitobj.name = refobj['name']
    # 2017/03/29: read description
    fitobj.notes = refobj['description']

    try:
        ship = refobj['ship_type_id']
        try:
            fitobj.ship = Ship(sMkt.getItem(ship))
        except ValueError:
            fitobj.ship = Citadel(sMkt.getItem(ship))
    except (KeyboardInterrupt, SystemExit):
        raise
    except:
        pyfalog.warning("Caught exception in importESI")
        return None

    items.sort(key=lambda k: k['flag'])

    moduleList = []
    for module in items:
        try:
            item = sMkt.getItem(module['type_id'], eager="group.category")
            if not item.published:
                continue
            if module['flag'] == INV_FLAG_DRONEBAY:
                d = Drone(item)
                d.amount = module['quantity']
                fitobj.drones.append(d)
            elif module['flag'] == INV_FLAG_CARGOBAY:
                c = Cargo(item)
                c.amount = module['quantity']
                fitobj.cargo.append(c)
            elif module['flag'] == INV_FLAG_FIGHTER:
                fighter = Fighter(item)
                fitobj.fighters.append(fighter)
            else:
                try:
                    m = Module(item)
                # When item can't be added to any slot (unknown item or just charge), ignore it
                except ValueError:
                    pyfalog.debug("Item can't be added to any slot (unknown item or just charge)")
                    continue
                # Add subsystems before modules to make sure T3 cruisers have subsystems installed
                if item.category.name == "Subsystem":
                    if m.fits(fitobj):
                        fitobj.modules.append(m)
                else:
                    if m.isValidState(FittingModuleState.ACTIVE):
                        m.state = activeStateLimit(m.item)

                    moduleList.append(m)

        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            pyfalog.warning("Could not process module.")
            continue

    # Recalc to get slot numbers correct for T3 cruisers
    sFit = svcFit.getInstance()
    sFit.recalc(fitobj)
    sFit.fill(fitobj)

    for module in moduleList:
        if module.fits(fitobj):
            fitobj.modules.append(module)

    return fitobj
