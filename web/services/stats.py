"""Fitting statistics, mirroring what the desktop stat views show.

The desktop views in ``gui/builtinStatsViews/`` are wx panels: they compute a
value in ``refreshPanel()`` and push it into a label. There is no way to reuse
them from a server, so the same numbers are gathered here from the very same
``eos`` properties the views call. Numbers are returned raw, together with the
rounding hints pyfa uses (``prec``/``lowest``/``highest``/``unit``) so the browser
can format them exactly like the desktop does.

Anything that needs the GUI is skipped, and a failing section is reported in
``errors`` rather than taking the whole response down -- one broken stat should
not make a fit unviewable.
"""

from logbook import Logger

import eos.config
from eos.const import FittingHardpoint
from eos.utils.spoolSupport import SpoolOptions, SpoolType

pyfalog = Logger(__name__)

#: Hold capacities that pyfa shows under "Targeting & Misc". Order matches the desktop.
HOLD_ATTRS = (
    ("fleetHangarCapacity", "Fleet hangar"),
    ("shipMaintenanceBayCapacity", "Maintenance bay"),
    ("specialColonyResourcesHoldCapacity", "Infrastructure hold"),
    ("specialAmmoHoldCapacity", "Ammo hold"),
    ("specialFuelBayCapacity", "Fuel bay"),
    ("specialShipHoldCapacity", "Ship hold"),
    ("specialSmallShipHoldCapacity", "Small ship hold"),
    ("specialMediumShipHoldCapacity", "Medium ship hold"),
    ("specialLargeShipHoldCapacity", "Large ship hold"),
    ("specialIndustrialShipHoldCapacity", "Industrial ship hold"),
    ("generalMiningHoldCapacity", "Mining hold"),
    ("specialIceHoldCapacity", "Ice hold"),
    ("specialGasHoldCapacity", "Gas hold"),
    ("specialMineralHoldCapacity", "Mineral hold"),
    ("specialMaterialBayCapacity", "Material bay"),
    ("specialSalvageHoldCapacity", "Salvage hold"),
    ("specialCommandCenterHoldCapacity", "Command center hold"),
    ("specialPlanetaryCommoditiesHoldCapacity", "Planetary goods hold"),
    ("specialQuafeHoldCapacity", "Quafe hold"),
    ("specialMobileDepotHoldCapacity", "Mobile depot hold"),
    ("specialExpeditionHoldCapacity", "Expedition hold"),
)

#: Targeting ranges that get a lock-time tooltip on the desktop
LOCK_TIME_RADII = (
    ("Pod", 25),
    ("Interceptor", 33),
    ("Frigate", 38),
    ("Destroyer", 83),
    ("Cruiser", 130),
    ("Battlecruiser", 265),
    ("Battleship", 420),
    ("Carrier", 3000),
)

DAMAGE_TYPES = ("em", "thermal", "kinetic", "explosive")


def _spool(amount, absolute=False):
    return SpoolOptions(SpoolType.SPOOL_SCALE, amount, absolute)


def damage_types(value):
    """Serialise a ``DmgTypes`` instance."""
    if value is None:
        return None
    return {
        "em": value.em,
        "thermal": value.thermal,
        "kinetic": value.kinetic,
        "explosive": value.explosive,
        "pure": value.pure,
        "total": value.total,
    }


def _spooled(fit, getter, defaultSpoolValue):
    """Value at the configured spool level plus the pre/full spool extremes."""
    return {
        "value": getter(_spool(defaultSpoolValue, False)),
        "preSpool": getter(_spool(0, True)),
        "fullSpool": getter(_spool(1, True)),
    }


def _attr(fit, name, default=None):
    value = fit.ship.getModifiedItemAttr(name)
    return default if value is None else value


def serialize_damage_profile(pattern):
    """The incoming damage profile, if one is selected."""
    if pattern is None:
        return None
    return {
        "em": getattr(pattern, "emAmount", 0),
        "thermal": getattr(pattern, "thermalAmount", 0),
        "kinetic": getattr(pattern, "kineticAmount", 0),
        "explosive": getattr(pattern, "explosiveAmount", 0),
    }


def _resource_section(fit):
    return {
        "hardpoints": {
            "turret": {
                "used": fit.getHardpointsUsed(FittingHardpoint.TURRET),
                "total": _attr(fit, "turretSlotsLeft", 0),
            },
            "launcher": {
                "used": fit.getHardpointsUsed(FittingHardpoint.MISSILE),
                "total": _attr(fit, "launcherSlotsLeft", 0),
            },
        },
        "calibration": {
            "used": fit.calibrationUsed,
            "total": _attr(fit, "upgradeCapacity", 0),
        },
        "cpu": {"used": fit.cpuUsed, "total": _attr(fit, "cpuOutput", 0)},
        "powergrid": {"used": fit.pgUsed, "total": _attr(fit, "powerOutput", 0)},
        "drones": {
            "active": fit.activeDrones,
            "maxActive": fit.extraAttributes["maxActiveDrones"],
            "bayUsed": fit.droneBayUsed,
            "bayTotal": _attr(fit, "droneCapacity", 0),
            "bandwidthUsed": fit.droneBandwidthUsed,
            "bandwidthTotal": _attr(fit, "droneBandwidth", 0),
        },
        "fighters": {
            "tubesUsed": fit.fighterTubesUsed,
            "tubesTotal": fit.fighterTubesTotal,
            "bayUsed": fit.fighterBayUsed,
            "bayTotal": _attr(fit, "fighterCapacity", 0),
        },
        "cargo": {"used": fit.cargoBayUsed, "total": _attr(fit, "capacity", 0)},
        "droneControlRange": fit.extraAttributes["droneControlRange"],
    }


def _firepower_section(fit):
    defaultSpool = eos.config.settings["globalDefaultSpoolupPercentage"]
    weapon = _spooled(fit, lambda s: damage_types(fit.getWeaponDps(spoolOptions=s)), defaultSpool)
    drone = _spooled(fit, lambda s: damage_types(fit.getDroneDps()), defaultSpool)
    volley = _spooled(fit, lambda s: damage_types(fit.getTotalVolley(spoolOptions=s)), defaultSpool)
    dps = _spooled(fit, lambda s: damage_types(fit.getTotalDps(spoolOptions=s)), defaultSpool)
    return {
        "weapon": weapon,
        "drone": drone,
        "volley": volley,
        "dps": dps,
        "defaultSpoolValue": defaultSpool,
        "hasTargetProfile": fit.targetProfile is not None,
    }


def _mining_section(fit):
    return {
        "miner": {"yield": fit.minerYield, "drain": fit.minerDrain},
        "drone": {"yield": fit.droneYield, "drain": fit.droneDrain},
        "total": {"yield": fit.totalYield, "drain": fit.totalDrain},
    }


def _capacitor_section(fit):
    capacity = _attr(fit, "capacitorCapacity", 0)
    recharge = fit.capRecharge
    used = fit.capUsed
    neutResistance = fit.ship.getModifiedItemAttr("energyWarfareResistance", 1) or 1
    return {
        "capacity": capacity,
        "delta": fit.capDelta,
        "recharge": recharge,
        "used": used,
        "stable": fit.capStable,
        "state": fit.capState,
        "resistance": (1 - neutResistance) * 100,
        "effectiveCapacity": capacity / neutResistance,
    }


def _recharge_section(fit):
    """Tank numbers under both normal and reinforced/sustained assumptions."""
    tank = fit.tank or {}
    effective = fit.effectiveTank or {}
    sustainable = fit.sustainableTank or {}
    effectiveSustainable = fit.effectiveSustainableTank or {}

    def pack(source):
        return {
            "passiveShield": source.get("passiveShield", 0),
            "shieldRepair": source.get("shieldRepair", 0),
            "armorRepair": source.get("armorRepair", 0),
            "hullRepair": source.get("hullRepair", 0),
            "armorRepairPreSpool": source.get("armorRepairPreSpool", 0),
            "armorRepairFullSpool": source.get("armorRepairFullSpool", 0),
        }

    return {
        "normal": pack(tank),
        "effective": pack(effective),
        "sustained": pack(sustainable),
        "effectiveSustained": pack(effectiveSustainable),
    }


def _resistances_section(fit):
    hp = fit.hp or {}
    ehp = fit.ehp or {}
    pattern = fit.damagePattern
    targetProfile = fit.targetProfile

    resonances = {}
    for layer, names in (
        ("shield", ("shieldEmDamageResonance", "shieldThermalDamageResonance",
                    "shieldKineticDamageResonance", "shieldExplosiveDamageResonance")),
        ("armor", ("armorEmDamageResonance", "armorThermalDamageResonance",
                   "armorKineticDamageResonance", "armorExplosiveDamageResonance")),
        ("hull", ("emDamageResonance", "thermalDamageResonance",
                  "kineticDamageResonance", "explosiveDamageResonance")),
    ):
        resonances[layer] = {
            dmg: (1 - (_attr(fit, attr, 1) or 1)) * 100
            for dmg, attr in zip(DAMAGE_TYPES, names)
        }

    return {
        "hp": {
            "shield": hp.get("shield", 0),
            "armor": hp.get("armor", 0),
            "hull": hp.get("hull", 0),
            "total": sum(hp.values()) if hp else 0,
        },
        "ehp": {
            "shield": ehp.get("shield", 0),
            "armor": ehp.get("armor", 0),
            "hull": ehp.get("hull", 0),
            "total": sum(ehp.values()) if ehp else 0,
        },
        "resistances": resonances,
        "damagePattern": serialize_damage_profile(pattern),
        "damagePatternName": getattr(pattern, "name", None),
        "targetProfileName": getattr(targetProfile, "name", None) if targetProfile is not None else None,
    }


def _targeting_section(fit):
    holds = []
    for attr, label in HOLD_ATTRS:
        value = _attr(fit, attr)
        if value:
            holds.append({"attr": attr, "label": label, "capacity": value})

    lockTimes = [
        {"name": name, "radius": radius, "time": fit.calculateLockTime(radius)}
        for name, radius in LOCK_TIME_RADII
    ]

    warpScramble = _attr(fit, "warpScrambleStatus", 0) or 0

    return {
        "targets": fit.maxTargets,
        "maxTargetRange": fit.maxTargetRange,
        "scanResolution": _attr(fit, "scanResolution", 0),
        "sensorStrength": fit.scanStrength,
        "scanType": fit.scanType,
        "jamChance": fit.jamChance,
        "droneControlRange": fit.extraAttributes["droneControlRange"],
        "speed": fit.maxSpeed,
        "alignTime": fit.alignTime,
        "signatureRadius": _attr(fit, "signatureRadius", 0),
        "warpSpeed": fit.warpSpeed,
        "maxWarpDistance": fit.maxWarpDistance,
        "mass": _attr(fit, "mass", 0),
        "agility": _attr(fit, "agility", 0),
        "probeSize": fit.probeSize,
        "warpCoreStrength": -warpScramble if warpScramble else 0,
        "holds": holds,
        "lockTimes": lockTimes,
    }


def _remote_reps_section(fit):
    defaultSpool = eos.config.settings["globalDefaultSpoolupPercentage"]

    def pack(getter):
        value = getter(_spool(defaultSpool, False))
        preSpool = getter(_spool(0, True))
        fullSpool = getter(_spool(1, True))
        return {
            "value": {"shield": value.shield, "armor": value.armor,
                      "hull": value.hull, "capacitor": value.capacitor},
            "preSpool": {"shield": preSpool.shield, "armor": preSpool.armor,
                         "hull": preSpool.hull, "capacitor": preSpool.capacitor},
            "fullSpool": {"shield": fullSpool.shield, "armor": fullSpool.armor,
                          "hull": fullSpool.hull, "capacitor": fullSpool.capacitor},
        }

    return pack(lambda s: fit.getRemoteReps(spoolOptions=s))


SECTIONS = (
    ("resources", _resource_section),
    ("firepower", _firepower_section),
    ("mining", _mining_section),
    ("capacitor", _capacitor_section),
    ("tank", _recharge_section),
    ("resistances", _resistances_section),
    ("targeting", _targeting_section),
    ("remoteReps", _remote_reps_section),
)


def build_stats(fit, sections=None):
    """All fitting stats for ``fit`` as a JSON-friendly dict.

    ``errors`` is always present (empty when everything worked) so clients can
    rely on the shape.
    """
    result = {}
    errors = {}
    wanted = set(sections) if sections else None
    for name, builder in SECTIONS:
        if wanted is not None and name not in wanted:
            continue
        try:
            result[name] = builder(fit)
        except Exception as ex:
            pyfalog.exception("Failed to compute {} for fit {}", name, getattr(fit, "ID", None))
            result[name] = None
            errors[name] = "{}: {}".format(type(ex).__name__, ex)
    result["errors"] = errors
    return result
