"""Fit editing, using pyfa's own undoable commands.

Every mutation the desktop application supports is a ``Gui*Command`` in
``gui/fitCommands/gui/``. They wrap the ``calc`` commands, run the state checks,
recalculate, fill, commit and post a change event; the only GUI-specific thing
about them is that they post that event to the main window, which
:mod:`pyfa_compat.mainframe_stub` and :mod:`web.events` handle.

So the web layer does not reimplement editing: it maps a JSON command name onto
one of those classes, submits it to a per-user, per-fit undo stack, and lets the
existing code do the work. That is why undo/redo, "fill with similar modules",
mutation handling, charge swapping and so on all behave exactly like the desktop.

Security note: clients name a command from :data:`COMMANDS`; they never name a
Python class. Anything not in the registry is rejected.
"""

import math
from contextlib import contextmanager

from logbook import Logger

import eos.db
from eos.const import FittingSlot
from web.events import publishing_as

pyfalog = Logger(__name__)

#: Container name -> attribute on the fit, for resolving client references
CONTAINERS = {
    "module": "modules",
    "projectedModule": "projectedModules",
    "drone": "drones",
    "projectedDrone": "projectedDrones",
    "fighter": "fighters",
    "projectedFighter": "projectedFighters",
    "implant": "implants",
    "booster": "boosters",
    "cargo": "cargo",
    "projectedFit": "projectedFits",
    "commandFit": "commandFits",
}


class CommandError(Exception):
    """A client mistake: unknown command, missing argument, bad reference."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class CommandFailed(Exception):
    """The engine refused the change (does not fit, invalid target, ...).

    ``code`` names the reason and ``params`` carry the values that belong in the
    sentence, so a browser can say the same thing in the reader's own language. The
    message itself stays English: it is what lands in the log and what a client that
    ignores codes shows.
    """

    def __init__(self, message, code=None, params=None):
        super().__init__(message)
        self.code = code
        #: Values interpolated into the message by name (``{name}``, ``{rack}``, ...)
        self.params = dict(params or {})

    def detail(self):
        """The body the API answers a refused edit with."""
        return {
            "message": str(self),
            "code": self.code or "engineRefused",
            "params": self.params,
        }


COMMANDS = {}


def command(name, requires=(), summary="", args=None):
    """Register a JSON command name."""

    def decorator(func):
        COMMANDS[name] = {
            "name": name,
            "handler": func,
            "requires": tuple(requires),
            "summary": summary or (func.__doc__ or "").strip().split("\n")[0],
            "args": args or {},
        }
        return func

    return decorator


class CommandContext:
    """Everything a handler needs: the fit, the command module, the payload."""

    def __init__(self, fit, fitID, payload, userData):
        self.fit = fit
        self.fitID = fitID
        self.payload = payload
        self.userData = userData
        self._cmd = None

    @property
    def cmd(self):
        """``gui.fitCommands`` (imported lazily so the stub is installed first)."""
        if self._cmd is None:
            import gui.fitCommands as cmd

            self._cmd = cmd
        return self._cmd

    # -- payload access -----------------------------------------------------------------

    def require(self, *names):
        missing = [name for name in names if self.payload.get(name) is None]
        if missing:
            raise CommandError("missing argument(s): {}".format(", ".join(missing)))
        for name in names:
            yield self.payload[name]

    def get(self, name, default=None):
        return self.payload.get(name, default)

    def container(self, kind):
        attribute = CONTAINERS.get(kind)
        if attribute is None:
            raise CommandError("unknown container kind {!r}; expected one of {}".format(
                kind, ", ".join(sorted(CONTAINERS))))
        return getattr(self.fit, attribute)

    def resolve(self, ref):
        """Turn a client reference into an engine object."""
        if not isinstance(ref, dict):
            raise CommandError("expected an object reference, got {!r}".format(ref))
        kind = ref.get("kind")
        items = self.container(kind)
        if "position" in ref:
            position = ref["position"]
            if not isinstance(position, int) or position < 0 or position >= len(items):
                raise CommandError("{} position {} is out of range".format(kind, position))
            return items[position]
        if "itemId" in ref:
            for item in items:
                if getattr(item, "itemID", None) == ref["itemId"]:
                    return item
            raise CommandError("no {} with item id {} in this fit".format(kind, ref["itemId"]))
        if "fitId" in ref:
            for item in items:
                if getattr(item, "ID", None) == ref["fitId"]:
                    return item
            raise CommandError("no {} with fit id {} in this fit".format(kind, ref["fitId"]))
        raise CommandError("reference needs position, itemId or fitId")

    def resolveAll(self, refs):
        if not isinstance(refs, (list, tuple)):
            raise CommandError("expected a list of references")
        return [self.resolve(ref) for ref in refs]

    def positions(self, refs, kind):
        """Positions of the referenced objects inside their container."""
        if not isinstance(refs, (list, tuple)):
            raise CommandError("expected a list of {} references".format(kind))
        container = self.container(kind)
        positions = []
        for ref in refs:
            obj = self.resolve(ref if isinstance(ref, dict) else {"kind": kind, "position": ref})
            try:
                positions.append(container.index(obj))
            except ValueError:
                raise CommandError("referenced {} is not part of this fit".format(kind))
        return positions


# ---------------------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------------------


@command("addLocalModule", requires=("itemId",), args={"itemId": "type id of the module"})
def addLocalModule(ctx):
    """Add a module to the first free slot that accepts it."""
    return ctx.cmd.GuiAddLocalModuleCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("removeLocalModules", requires=("positions",), args={"positions": "list of module positions"})
def removeLocalModules(ctx):
    """Remove the modules in the given slot positions."""
    positions = ctx.positions(ctx.payload["positions"], "module")
    return ctx.cmd.GuiRemoveLocalModuleCommand(fitID=ctx.fitID, positions=positions)


@command("replaceLocalModule", requires=("itemId", "positions"),
         args={"itemId": "type id", "positions": "module positions to replace"})
def replaceLocalModule(ctx):
    """Replace the modules at the given positions."""
    positions = ctx.positions(ctx.payload["positions"], "module")
    return ctx.cmd.GuiReplaceLocalModuleCommand(
        fitID=ctx.fitID, itemID=ctx.payload["itemId"], positions=positions)


@command("swapLocalModules", requires=("position1", "position2"),
         args={"position1": "module position", "position2": "module position"})
def swapLocalModules(ctx):
    """Swap two modules between slots."""
    return ctx.cmd.GuiSwapLocalModulesCommand(
        fitID=ctx.fitID, position1=ctx.payload["position1"], position2=ctx.payload["position2"])


@command("cloneLocalModule", requires=("position",),
         args={"position": "module position to copy from"})
def cloneLocalModule(ctx):
    """Duplicate a module (and its charge/mutation) into a free slot."""
    return ctx.cmd.GuiCloneLocalModuleCommand(fitID=ctx.fitID, position=ctx.payload["position"])


@command("fillWithNewLocalModules", requires=("itemId",), args={"itemId": "type id"})
def fillWithNewLocalModules(ctx):
    """Fill every compatible free slot with new modules."""
    return ctx.cmd.GuiFillWithNewLocalModulesCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("fillWithClonedLocalModules", requires=("position",), args={"position": "module position"})
def fillWithClonedLocalModules(ctx):
    """Fill compatible free slots by cloning the module at ``position``."""
    position = ctx.positions([ctx.payload["position"]], "module")[0]
    return ctx.cmd.GuiFillWithClonedLocalModulesCommand(fitID=ctx.fitID, position=position)


@command("changeLocalModuleStates",
         requires=("main",),
         args={"main": "reference to clicked module", "positions": "additional module positions",
               "click": "'cycle' (one state up, overload drops back to online), 'left' (pyfa's"
                        " toggle), 'right' (overheat) or 'ctrl' (offline)"})
def changeLocalModuleStates(ctx):
    """Cycle/heat/offline modules, exactly like clicking the state column.

    ``cycle`` is the browser's own click: it walks online, active, overheated and back to
    online, which the desktop's vocabulary cannot express -- there a plain click only ever
    toggles between online and active, so overload is left to the right click.
    """
    main = ctx.resolve(ctx.payload["main"])
    positions = ctx.positions(ctx.payload.get("positions") or [], "module")
    mainPosition = ctx.container("module").index(main)
    click = ctx.payload.get("click", "left")
    unchanged = explain_state_refusal(main, click, positions)
    if unchanged is not None:
        raise unchanged
    return ctx.cmd.GuiChangeLocalModuleStatesCommand(
        fitID=ctx.fitID, mainPosition=mainPosition, positions=positions, click=click)


@command("changeLocalModuleCharges", requires=("positions", "chargeItemId"),
         args={"positions": "module positions", "chargeItemId": "type id of the charge, or null to unload"})
def changeLocalModuleCharges(ctx):
    """Load a charge into the given modules."""
    positions = ctx.positions(ctx.payload["positions"], "module")
    return ctx.cmd.GuiChangeLocalModuleChargesCommand(
        fitID=ctx.fitID, positions=positions, chargeItemID=ctx.payload["chargeItemId"])


@command("changeLocalModuleMetas", requires=("positions", "newItemId"),
         args={"positions": "module positions", "newItemId": "type id of the variant"})
def changeLocalModuleMetas(ctx):
    """Switch modules to another meta variant (T1/T2/faction)."""
    positions = ctx.positions(ctx.payload["positions"], "module")
    return ctx.cmd.GuiChangeLocalModuleMetasCommand(
        fitID=ctx.fitID, positions=positions, newItemID=ctx.payload["newItemId"])


@command("changeLocalModuleSpool", requires=("position", "spoolType", "spoolAmount"),
         args={"position": "module position", "spoolType": "SpoolType value",
               "spoolAmount": "spool amount"})
def changeLocalModuleSpool(ctx):
    """Set the spool-up of a module such as a dreadnought lance."""
    position = ctx.positions([ctx.payload["position"]], "module")[0]
    return ctx.cmd.GuiChangeLocalModuleSpoolCommand(
        fitID=ctx.fitID, position=position,
        spoolType=ctx.payload["spoolType"], spoolAmount=ctx.payload["spoolAmount"])


@command("changeLocalModuleMutation", requires=("position", "mutations"),
         args={"position": "module position", "mutations": "{attribute id: value}"})
def changeLocalModuleMutation(ctx):
    """Apply mutated attribute values to an already-mutated module."""
    position = ctx.positions([ctx.payload["position"]], "module")[0]
    mutations = {int(k): v for k, v in ctx.payload["mutations"].items()}
    return ctx.cmd.GuiChangeLocalModuleMutationCommand(
        fitID=ctx.fitID, position=position, mutation=mutations)


@command("convertMutatedLocalModule", requires=("position", "mutaplasmidId"),
         args={"position": "module position", "mutaplasmidId": "type id of the mutaplasmid"})
def convertMutatedLocalModule(ctx):
    """Turn a plain module into a mutated one using a mutaplasmid."""
    position = ctx.positions([ctx.payload["position"]], "module")[0]
    mutaplasmid = eos.db.getDynamicItem(ctx.payload["mutaplasmidId"])
    if mutaplasmid is None:
        raise CommandError("unknown mutaplasmid {}".format(ctx.payload["mutaplasmidId"]))
    return ctx.cmd.GuiConvertMutatedLocalModuleCommand(
        fitID=ctx.fitID, position=position, mutaplasmid=mutaplasmid)


@command("revertMutatedLocalModule", requires=("position",), args={"position": "module position"})
def revertMutatedLocalModule(ctx):
    """Turn a mutated module back into its base module."""
    position = ctx.positions([ctx.payload["position"]], "module")[0]
    return ctx.cmd.GuiRevertMutatedLocalModuleCommand(fitID=ctx.fitID, position=position)


@command("importLocalMutatedModule", requires=("baseItemId", "mutaplasmidId"),
         args={"baseItemId": "type id of the base module", "mutaplasmidId": "type id of the mutaplasmid",
               "mutations": "{attribute id: value}"})
def importLocalMutatedModule(ctx):
    """Create a mutated module from pasted abyssal data."""
    from service.market import Market

    mutaplasmid = eos.db.getDynamicItem(ctx.payload["mutaplasmidId"])
    if mutaplasmid is None:
        raise CommandError("unknown mutaplasmid {}".format(ctx.payload["mutaplasmidId"]))
    baseItem = Market.getInstance().getItem(ctx.payload["baseItemId"], eager=("attributes", "group.category"))
    if baseItem is None:
        raise CommandError("unknown base item {}".format(ctx.payload["baseItemId"]))
    mutations = {int(k): v for k, v in (ctx.payload.get("mutations") or {}).items()}
    return ctx.cmd.GuiImportLocalMutatedModuleCommand(
        fitID=ctx.fitID, baseItem=baseItem, mutaplasmid=mutaplasmid, mutations=mutations)


@command("cargoToLocalModule", requires=("cargoItemId", "modPosition", "copy"),
         args={"cargoItemId": "type id of the cargo stack", "modPosition": "target module position",
               "copy": "true to leave the cargo in place"})
def cargoToLocalModule(ctx):
    """Fit an item from the cargo hold into a module slot."""
    return ctx.cmd.GuiCargoToLocalModuleCommand(
        fitID=ctx.fitID, cargoItemID=ctx.payload["cargoItemId"],
        modPosition=ctx.payload["modPosition"], copy=bool(ctx.payload["copy"]))


@command("localModuleToCargo", requires=("modPosition", "cargoItemId", "copy"),
         args={"modPosition": "module position", "cargoItemId": "type id of the cargo stack",
               "copy": "true to keep the module fitted"})
def localModuleToCargo(ctx):
    """Move a fitted module into the cargo hold."""
    return ctx.cmd.GuiLocalModuleToCargoCommand(
        fitID=ctx.fitID, modPosition=ctx.payload["modPosition"],
        cargoItemID=ctx.payload["cargoItemId"], copy=bool(ctx.payload["copy"]))


# ---------------------------------------------------------------------------------------
# Drones
# ---------------------------------------------------------------------------------------


@command("addLocalDrone", requires=("itemId", "amount"), args={"itemId": "type id", "amount": "how many"})
def addLocalDrone(ctx):
    """Add a stack of drones to the drone bay."""
    return ctx.cmd.GuiAddLocalDroneCommand(
        fitID=ctx.fitID, itemID=ctx.payload["itemId"], amount=ctx.payload["amount"])


@command("removeLocalDrones", requires=("positions",),
         args={"positions": "drone stack positions", "amount": "how many to remove (default all)"})
def removeLocalDrones(ctx):
    """Remove drone stacks."""
    positions = ctx.positions(ctx.payload["positions"], "drone")
    amount = ctx.payload.get("amount")
    return ctx.cmd.GuiRemoveLocalDronesCommand(
        fitID=ctx.fitID, positions=positions, amount=math.inf if amount is None else amount)


@command("changeLocalDroneAmount", requires=("position", "amount"),
         args={"position": "drone stack position", "amount": "new stack size"})
def changeLocalDroneAmount(ctx):
    """Change how many drones are in a stack."""
    position = ctx.positions([ctx.payload["position"]], "drone")[0]
    return ctx.cmd.GuiChangeLocalDroneAmountCommand(
        fitID=ctx.fitID, position=position, amount=ctx.payload["amount"])


@command("changeLocalDroneMetas", requires=("positions", "newItemId"),
         args={"positions": "drone positions", "newItemId": "type id of the variant"})
def changeLocalDroneMetas(ctx):
    """Switch drone stacks to another meta variant."""
    positions = ctx.positions(ctx.payload["positions"], "drone")
    return ctx.cmd.GuiChangeLocalDroneMetasCommand(
        fitID=ctx.fitID, positions=positions, newItemID=ctx.payload["newItemId"])


@command("changeLocalDroneMutation", requires=("position", "mutations"),
         args={"position": "drone position", "mutations": "{attribute id: value}"})
def changeLocalDroneMutation(ctx):
    """Apply mutated attribute values to a mutated drone stack."""
    position = ctx.positions([ctx.payload["position"]], "drone")[0]
    mutations = {int(k): v for k, v in ctx.payload["mutations"].items()}
    return ctx.cmd.GuiChangeLocalDroneMutationCommand(
        fitID=ctx.fitID, position=position, mutation=mutations)


@command("cloneLocalDrone", requires=("position",), args={"position": "drone position"})
def cloneLocalDrone(ctx):
    """Duplicate a drone stack."""
    position = ctx.positions([ctx.payload["position"]], "drone")[0]
    return ctx.cmd.GuiCloneLocalDroneCommand(fitID=ctx.fitID, position=position)


@command("splitLocalDroneStack", requires=("position", "amount"),
         args={"position": "drone position", "amount": "size of the new stack"})
def splitLocalDroneStack(ctx):
    """Split a drone stack in two."""
    position = ctx.positions([ctx.payload["position"]], "drone")[0]
    return ctx.cmd.GuiSplitLocalDroneStackCommand(
        fitID=ctx.fitID, position=position, amount=ctx.payload["amount"])


@command("mergeLocalDroneStacks", requires=("srcPosition", "dstPosition"),
         args={"srcPosition": "drone position", "dstPosition": "drone position"})
def mergeLocalDroneStacks(ctx):
    """Merge one drone stack into another."""
    return ctx.cmd.GuiMergeLocalDroneStacksCommand(
        fitID=ctx.fitID, srcPosition=ctx.payload["srcPosition"], dstPosition=ctx.payload["dstPosition"])


@command("toggleLocalDroneStates", requires=("main",),
         args={"main": "reference to the clicked drone stack", "positions": "additional stacks"})
def toggleLocalDroneStates(ctx):
    """Activate or deactivate drone stacks."""
    main = ctx.resolve(ctx.payload["main"])
    positions = ctx.positions(ctx.payload.get("positions") or [], "drone")
    return ctx.cmd.GuiToggleLocalDroneStatesCommand(
        fitID=ctx.fitID, mainPosition=ctx.container("drone").index(main), positions=positions)


@command("convertMutatedLocalDrone", requires=("position", "mutaplasmidId"),
         args={"position": "drone position", "mutaplasmidId": "type id"})
def convertMutatedLocalDrone(ctx):
    """Turn a plain drone stack into a mutated one."""
    position = ctx.positions([ctx.payload["position"]], "drone")[0]
    mutaplasmid = eos.db.getDynamicItem(ctx.payload["mutaplasmidId"])
    if mutaplasmid is None:
        raise CommandError("unknown mutaplasmid {}".format(ctx.payload["mutaplasmidId"]))
    return ctx.cmd.GuiConvertMutatedLocalDroneCommand(
        fitID=ctx.fitID, position=position, mutaplasmid=mutaplasmid)


@command("revertMutatedLocalDrone", requires=("position",), args={"position": "drone position"})
def revertMutatedLocalDrone(ctx):
    """Turn a mutated drone stack back into its base drone."""
    position = ctx.positions([ctx.payload["position"]], "drone")[0]
    return ctx.cmd.GuiRevertMutatedLocalDroneCommand(fitID=ctx.fitID, position=position)


@command("importLocalMutatedDrone", requires=("baseItemId", "mutaplasmidId", "amount"),
         args={"baseItemId": "type id", "mutaplasmidId": "type id", "amount": "stack size",
               "mutations": "{attribute id: value}"})
def importLocalMutatedDrone(ctx):
    """Create a mutated drone stack from pasted abyssal data."""
    from service.market import Market

    mutaplasmid = eos.db.getDynamicItem(ctx.payload["mutaplasmidId"])
    if mutaplasmid is None:
        raise CommandError("unknown mutaplasmid {}".format(ctx.payload["mutaplasmidId"]))
    baseItem = Market.getInstance().getItem(ctx.payload["baseItemId"], eager=("attributes", "group.category"))
    if baseItem is None:
        raise CommandError("unknown base item {}".format(ctx.payload["baseItemId"]))
    mutations = {int(k): v for k, v in (ctx.payload.get("mutations") or {}).items()}
    return ctx.cmd.GuiImportLocalMutatedDroneCommand(
        fitID=ctx.fitID, baseItem=baseItem, mutaplasmid=mutaplasmid,
        mutations=mutations, amount=ctx.payload["amount"])


# ---------------------------------------------------------------------------------------
# Fighters
# ---------------------------------------------------------------------------------------


@command("addLocalFighter", requires=("itemId",), args={"itemId": "type id"})
def addLocalFighter(ctx):
    """Add a fighter squadron."""
    return ctx.cmd.GuiAddLocalFighterCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("removeLocalFighters", requires=("positions",), args={"positions": "squadron positions"})
def removeLocalFighters(ctx):
    """Remove fighter squadrons."""
    positions = ctx.positions(ctx.payload["positions"], "fighter")
    return ctx.cmd.GuiRemoveLocalFightersCommand(fitID=ctx.fitID, positions=positions)


@command("changeLocalFighterAmount", requires=("position", "amount"),
         args={"position": "squadron position", "amount": "new squadron size"})
def changeLocalFighterAmount(ctx):
    """Change the size of a fighter squadron."""
    position = ctx.positions([ctx.payload["position"]], "fighter")[0]
    return ctx.cmd.GuiChangeLocalFighterAmountCommand(
        fitID=ctx.fitID, position=position, amount=ctx.payload["amount"])


@command("changeLocalFighterMetas", requires=("positions", "newItemId"),
         args={"positions": "squadron positions", "newItemId": "type id of the variant"})
def changeLocalFighterMetas(ctx):
    """Switch squadrons to another meta variant."""
    positions = ctx.positions(ctx.payload["positions"], "fighter")
    return ctx.cmd.GuiChangeLocalFighterMetasCommand(
        fitID=ctx.fitID, positions=positions, newItemID=ctx.payload["newItemId"])


@command("toggleLocalFighterStates", requires=("main",),
         args={"main": "reference to the clicked squadron", "positions": "additional squadrons"})
def toggleLocalFighterStates(ctx):
    """Launch or recall fighter squadrons."""
    main = ctx.resolve(ctx.payload["main"])
    positions = ctx.positions(ctx.payload.get("positions") or [], "fighter")
    return ctx.cmd.GuiToggleLocalFighterStatesCommand(
        fitID=ctx.fitID, mainPosition=ctx.container("fighter").index(main), positions=positions)


@command("toggleLocalFighterAbilityState",
         requires=("main", "effectId"),
         args={"main": "reference to the clicked squadron", "positions": "additional squadrons",
               "effectId": "ability effect id"})
def toggleLocalFighterAbilityState(ctx):
    """Enable or disable a squadron ability."""
    main = ctx.resolve(ctx.payload["main"])
    positions = ctx.positions(ctx.payload.get("positions") or [], "fighter")
    return ctx.cmd.GuiToggleLocalFighterAbilityStateCommand(
        fitID=ctx.fitID, mainPosition=ctx.container("fighter").index(main),
        positions=positions, effectID=ctx.payload["effectId"])


# ---------------------------------------------------------------------------------------
# Cargo
# ---------------------------------------------------------------------------------------


@command("addCargo", requires=("itemId", "amount"), args={"itemId": "type id", "amount": "quantity"})
def addCargo(ctx):
    """Add items to the cargo hold."""
    return ctx.cmd.GuiAddCargoCommand(
        fitID=ctx.fitID, itemID=ctx.payload["itemId"], amount=ctx.payload["amount"])


@command("removeCargos", requires=("itemIds",), args={"itemIds": "type ids of cargo stacks"})
def removeCargos(ctx):
    """Remove cargo stacks."""
    return ctx.cmd.GuiRemoveCargosCommand(fitID=ctx.fitID, itemIDs=ctx.payload["itemIds"])


@command("changeCargosAmount", requires=("itemIds", "amount"),
         args={"itemIds": "type ids of cargo stacks", "amount": "new quantity"})
def changeCargosAmount(ctx):
    """Change a cargo stack's quantity."""
    return ctx.cmd.GuiChangeCargosAmountCommand(
        fitID=ctx.fitID, itemIDs=ctx.payload["itemIds"], amount=ctx.payload["amount"])


@command("changeCargoMetas", requires=("itemIds", "newItemId"),
         args={"itemIds": "type ids of cargo stacks", "newItemId": "type id of the variant"})
def changeCargoMetas(ctx):
    """Switch cargo stacks to another meta variant."""
    return ctx.cmd.GuiChangeCargoMetasCommand(
        fitID=ctx.fitID, itemIDs=ctx.payload["itemIds"], newItemID=ctx.payload["newItemId"])


# ---------------------------------------------------------------------------------------
# Implants
# ---------------------------------------------------------------------------------------


@command("addImplant", requires=("itemId",), args={"itemId": "type id"})
def addImplant(ctx):
    """Add an implant to the fit."""
    return ctx.cmd.GuiAddImplantCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("removeImplants", requires=("positions",), args={"positions": "implant positions"})
def removeImplants(ctx):
    """Remove implants."""
    positions = ctx.positions(ctx.payload["positions"], "implant")
    return ctx.cmd.GuiRemoveImplantsCommand(fitID=ctx.fitID, positions=positions)


@command("changeImplantLocation", requires=("source",),
         args={"source": "ImplantLocation value (0 fit, 1 character)"})
def changeImplantLocation(ctx):
    """Choose whether implants come from the fit or the character."""
    return ctx.cmd.GuiChangeImplantLocationCommand(fitID=ctx.fitID, source=ctx.payload["source"])


@command("changeImplantMeta", requires=("position", "newItemId"),
         args={"position": "implant position", "newItemId": "type id of the variant"})
def changeImplantMeta(ctx):
    """Switch an implant to another meta variant."""
    position = ctx.positions([ctx.payload["position"]], "implant")[0]
    return ctx.cmd.GuiChangeImplantMetaCommand(
        fitID=ctx.fitID, position=position, newItemID=ctx.payload["newItemId"])


@command("toggleImplantStates", requires=("main",),
         args={"main": "reference to the clicked implant", "positions": "additional implants"})
def toggleImplantStates(ctx):
    """Activate or deactivate implants."""
    main = ctx.resolve(ctx.payload["main"])
    positions = ctx.positions(ctx.payload.get("positions") or [], "implant")
    return ctx.cmd.GuiToggleImplantStatesCommand(
        fitID=ctx.fitID, mainPosition=ctx.container("implant").index(main), positions=positions)


@command("addImplantSet", requires=("itemIds",), args={"itemIds": "type ids of the implants"})
def addImplantSet(ctx):
    """Add a whole implant set by item ids."""
    return ctx.cmd.GuiAddImplantSetCommand(fitID=ctx.fitID, itemIDs=ctx.payload["itemIds"])


# ---------------------------------------------------------------------------------------
# Boosters
# ---------------------------------------------------------------------------------------


@command("addBooster", requires=("itemId",), args={"itemId": "type id"})
def addBooster(ctx):
    """Add a booster."""
    return ctx.cmd.GuiAddBoosterCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("removeBoosters", requires=("positions",), args={"positions": "booster positions"})
def removeBoosters(ctx):
    """Remove boosters."""
    positions = ctx.positions(ctx.payload["positions"], "booster")
    return ctx.cmd.GuiRemoveBoostersCommand(fitID=ctx.fitID, positions=positions)


@command("changeBoosterMeta", requires=("position", "newItemId"),
         args={"position": "booster position", "newItemId": "type id of the variant"})
def changeBoosterMeta(ctx):
    """Switch a booster to another meta variant."""
    position = ctx.positions([ctx.payload["position"]], "booster")[0]
    return ctx.cmd.GuiChangeBoosterMetaCommand(
        fitID=ctx.fitID, position=position, newItemID=ctx.payload["newItemId"])


@command("toggleBoosterStates", requires=("main",),
         args={"main": "reference to the clicked booster", "positions": "additional boosters"})
def toggleBoosterStates(ctx):
    """Activate or deactivate boosters."""
    main = ctx.resolve(ctx.payload["main"])
    positions = ctx.positions(ctx.payload.get("positions") or [], "booster")
    return ctx.cmd.GuiToggleBoosterStatesCommand(
        fitID=ctx.fitID, mainPosition=ctx.container("booster").index(main), positions=positions)


@command("toggleBoosterSideEffectState", requires=("position", "effectId"),
         args={"position": "booster position", "effectId": "side effect id"})
def toggleBoosterSideEffectState(ctx):
    """Toggle a booster's side effect."""
    position = ctx.positions([ctx.payload["position"]], "booster")[0]
    return ctx.cmd.GuiToggleBoosterSideEffectStateCommand(
        fitID=ctx.fitID, position=position, effectID=ctx.payload["effectId"])


# ---------------------------------------------------------------------------------------
# Projected onto this fit
# ---------------------------------------------------------------------------------------


@command("addProjectedModule", requires=("itemId",), args={"itemId": "type id of the projected module"})
def addProjectedModule(ctx):
    """Project a module (remote rep, web, ...) onto this fit."""
    return ctx.cmd.GuiAddProjectedModuleCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("addProjectedDrone", requires=("itemId",), args={"itemId": "type id"})
def addProjectedDrone(ctx):
    """Project a drone (e.g. logistics) onto this fit."""
    return ctx.cmd.GuiAddProjectedDroneCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("addProjectedFighter", requires=("itemId",), args={"itemId": "type id"})
def addProjectedFighter(ctx):
    """Project a fighter squadron onto this fit."""
    return ctx.cmd.GuiAddProjectedFighterCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("addProjectedFits", requires=("fitIds", "amount"),
         args={"fitIds": "ids of fits to project (remote reps, command links)", "amount": "how many"})
def addProjectedFits(ctx):
    """Project whole fits onto this one."""
    return ctx.cmd.GuiAddProjectedFitsCommand(
        fitID=ctx.fitID, projectedFitIDs=ctx.payload["fitIds"], amount=ctx.payload["amount"])


@command("removeProjectedItems", requires=("items",),
         args={"items": "references to projected items", "amount": "how many to remove (default all)"})
def removeProjectedItems(ctx):
    """Remove projected modules, drones, fighters or fits."""
    items = ctx.resolveAll(ctx.payload["items"])
    amount = ctx.payload.get("amount")
    return ctx.cmd.GuiRemoveProjectedItemsCommand(
        fitID=ctx.fitID, items=items, amount=math.inf if amount is None else amount)


@command("changeProjectedItemStates", requires=("main", "items"),
         args={"main": "reference to the clicked item", "items": "other affected items",
               "click": "'left' (cycle), 'right' (overheat) or 'ctrl' (offline)"})
def changeProjectedItemStates(ctx):
    """Change the state of projected items."""
    main = ctx.resolve(ctx.payload["main"])
    items = ctx.resolveAll(ctx.payload["items"])
    return ctx.cmd.GuiChangeProjectedItemStatesCommand(
        fitID=ctx.fitID, mainItem=main, items=items, click=ctx.payload.get("click", "left"))


@command("changeProjectedItemsProjectionRange", requires=("items", "projectionRange"),
         args={"items": "references to projected items", "projectionRange": "range in metres"})
def changeProjectedItemsProjectionRange(ctx):
    """Set the assumed projection range (drives falloff/optimal)."""
    items = ctx.resolveAll(ctx.payload["items"])
    return ctx.cmd.GuiChangeProjectedItemsProjectionRangeCommand(
        fitID=ctx.fitID, items=items, projectionRange=ctx.payload["projectionRange"])


@command("changeProjectedModuleCharges", requires=("positions", "chargeItemId"),
         args={"positions": "projected module positions", "chargeItemId": "type id, or null to unload"})
def changeProjectedModuleCharges(ctx):
    """Load charges into projected modules."""
    positions = ctx.positions(ctx.payload["positions"], "projectedModule")
    return ctx.cmd.GuiChangeProjectedModuleChargesCommand(
        fitID=ctx.fitID, positions=positions, chargeItemID=ctx.payload["chargeItemId"])


@command("changeProjectedModuleMetas", requires=("positions", "newItemId"),
         args={"positions": "projected module positions", "newItemId": "type id of the variant"})
def changeProjectedModuleMetas(ctx):
    """Switch projected modules to another variant."""
    positions = ctx.positions(ctx.payload["positions"], "projectedModule")
    return ctx.cmd.GuiChangeProjectedModuleMetasCommand(
        fitID=ctx.fitID, positions=positions, newItemID=ctx.payload["newItemId"])


@command("changeProjectedModuleSpool", requires=("position", "spoolType", "spoolAmount"),
         args={"position": "projected module position", "spoolType": "SpoolType", "spoolAmount": "amount"})
def changeProjectedModuleSpool(ctx):
    """Set the spool-up of a projected module."""
    position = ctx.positions([ctx.payload["position"]], "projectedModule")[0]
    return ctx.cmd.GuiChangeProjectedModuleSpoolCommand(
        fitID=ctx.fitID, position=position,
        spoolType=ctx.payload["spoolType"], spoolAmount=ctx.payload["spoolAmount"])


@command("changeProjectedDroneAmount", requires=("itemId", "amount"),
         args={"itemId": "type id of the projected drone", "amount": "how many"})
def changeProjectedDroneAmount(ctx):
    """Change how many projected drones are applied."""
    return ctx.cmd.GuiChangeProjectedDroneAmountCommand(
        fitID=ctx.fitID, itemID=ctx.payload["itemId"], amount=ctx.payload["amount"])


@command("changeProjectedDroneMetas", requires=("itemIds", "newItemId"),
         args={"itemIds": "type ids of projected drones", "newItemId": "type id of the variant"})
def changeProjectedDroneMetas(ctx):
    """Switch projected drones to another variant."""
    return ctx.cmd.GuiChangeProjectedDroneMetasCommand(
        fitID=ctx.fitID, itemIDs=ctx.payload["itemIds"], newItemID=ctx.payload["newItemId"])


@command("changeProjectedFighterAmount", requires=("position", "amount"),
         args={"position": "projected squadron position", "amount": "squadron size"})
def changeProjectedFighterAmount(ctx):
    """Change the size of a projected squadron."""
    position = ctx.positions([ctx.payload["position"]], "projectedFighter")[0]
    return ctx.cmd.GuiChangeProjectedFighterAmountCommand(
        fitID=ctx.fitID, position=position, amount=ctx.payload["amount"])


@command("changeProjectedFighterMetas", requires=("positions", "newItemId"),
         args={"positions": "projected squadron positions", "newItemId": "type id of the variant"})
def changeProjectedFighterMetas(ctx):
    """Switch projected squadrons to another variant."""
    positions = ctx.positions(ctx.payload["positions"], "projectedFighter")
    return ctx.cmd.GuiChangeProjectedFighterMetasCommand(
        fitID=ctx.fitID, positions=positions, newItemID=ctx.payload["newItemId"])


@command("changeProjectedFitAmount", requires=("fitId", "amount"),
         args={"fitId": "id of the projected fit", "amount": "how many instances"})
def changeProjectedFitAmount(ctx):
    """Change how many instances of a projected fit are applied."""
    return ctx.cmd.GuiChangeProjectedFitAmountCommand(
        fitID=ctx.fitID, projectedFitID=ctx.payload["fitId"], amount=ctx.payload["amount"])


@command("toggleProjectedFighterAbilityState",
         requires=("main", "effectId"),
         args={"main": "reference to the projected squadron", "positions": "additional squadrons",
               "effectId": "ability effect id"})
def toggleProjectedFighterAbilityState(ctx):
    """Enable or disable a projected squadron's ability."""
    main = ctx.resolve(ctx.payload["main"])
    positions = ctx.positions(ctx.payload.get("positions") or [], "projectedFighter")
    return ctx.cmd.GuiToggleProjectedFighterAbilityStateCommand(
        fitID=ctx.fitID, mainPosition=ctx.container("projectedFighter").index(main),
        positions=positions, effectID=ctx.payload["effectId"])


# ---------------------------------------------------------------------------------------
# Command fits and command links
# ---------------------------------------------------------------------------------------


@command("addCommandFits", requires=("fitIds",), args={"fitIds": "ids of fits providing boosts"})
def addCommandFits(ctx):
    """Add command fits that boost this one."""
    return ctx.cmd.GuiAddCommandFitsCommand(fitID=ctx.fitID, commandFitIDs=ctx.payload["fitIds"])


@command("removeCommandFits", requires=("fitIds",), args={"fitIds": "ids of command fits"})
def removeCommandFits(ctx):
    """Remove command fits."""
    return ctx.cmd.GuiRemoveCommandFitsCommand(fitID=ctx.fitID, commandFitIDs=ctx.payload["fitIds"])


@command("toggleCommandFitStates", requires=("mainFitId", "fitIds"),
         args={"mainFitId": "id of the clicked command fit", "fitIds": "other command fits"})
def toggleCommandFitStates(ctx):
    """Enable or disable command fits."""
    return ctx.cmd.GuiToggleCommandFitStatesCommand(
        fitID=ctx.fitID, mainCommandFitID=ctx.payload["mainFitId"], commandFitIDs=ctx.payload["fitIds"])


@command("addCommandLink", requires=("linkType", "strength"),
         args={"linkType": "link type id", "strength": "link strength", "mindlink": "mindlink item id"})
def addCommandLink(ctx):
    """Add a command link to this fit."""
    return ctx.cmd.GuiAddCommandLinkCommand(
        fitID=ctx.fitID, linkType=ctx.payload["linkType"], strength=ctx.payload["strength"],
        mindlink=ctx.payload.get("mindlink"))


@command("removeCommandLinks", requires=("linkIds",), args={"linkIds": "command link ids"})
def removeCommandLinks(ctx):
    """Remove command links."""
    return ctx.cmd.GuiRemoveCommandLinksCommand(fitID=ctx.fitID, linkIDs=ctx.payload["linkIds"])


@command("toggleCommandLinkStates", requires=("mainLinkId", "linkIds"),
         args={"mainLinkId": "id of the clicked link", "linkIds": "other links"})
def toggleCommandLinkStates(ctx):
    """Enable or disable command links."""
    return ctx.cmd.GuiToggleCommandLinkStatesCommand(
        fitID=ctx.fitID, mainLinkID=ctx.payload["mainLinkId"], linkIDs=ctx.payload["linkIds"])


# ---------------------------------------------------------------------------------------
# Fit level
# ---------------------------------------------------------------------------------------


@command("renameFit", requires=("name",), args={"name": "new fit name"})
def renameFit(ctx):
    """Rename the fit."""
    name = str(ctx.payload["name"]).strip()
    if not name:
        raise CommandError("name cannot be empty")
    return ctx.cmd.GuiRenameFitCommand(fitID=ctx.fitID, name=name)


@command("changeShipMode", requires=("itemId",), args={"itemId": "type id of the mode"})
def changeShipMode(ctx):
    """Switch a ship between its modes (e.g. tactical destroyer modes)."""
    return ctx.cmd.GuiChangeShipModeCommand(fitID=ctx.fitID, itemID=ctx.payload["itemId"])


@command("changeFitSystemSecurity", requires=("secStatus",),
         args={"secStatus": "FitSystemSecurity value (0 hisec .. 3 wspace)"})
def changeFitSystemSecurity(ctx):
    """Set the system security status used for attribute modifiers."""
    return ctx.cmd.GuiChangeFitSystemSecurityCommand(fitID=ctx.fitID, secStatus=ctx.payload["secStatus"])


@command("changeFitPilotSecurity", requires=("secStatus",),
         args={"secStatus": "pilot security status"})
def changeFitPilotSecurity(ctx):
    """Set the pilot's security status."""
    return ctx.cmd.GuiChangeFitPilotSecurityCommand(fitID=ctx.fitID, secStatus=ctx.payload["secStatus"])


@command("toggleFittingRestrictions", args={})
def toggleFittingRestrictions(ctx):
    """Ignore or enforce fitting restrictions."""
    return ctx.cmd.GuiToggleFittingRestrictionsCommand(fitID=ctx.fitID)


@command("rebaseItems", requires=("rebaseMap",),
         args={"rebaseMap": "{old type id: new type id}"})
def rebaseItems(ctx):
    """Swap items for their replacements (used by "optimise fit price")."""
    rebaseMap = {int(k): int(v) for k, v in ctx.payload["rebaseMap"].items()}
    return ctx.cmd.GuiRebaseItemsCommand(fitID=ctx.fitID, rebaseMap=rebaseMap)


# ---------------------------------------------------------------------------------------
# Explaining refusals
# ---------------------------------------------------------------------------------------


#: Commands that put one catalogued item into a free slot. When the engine refuses one
#: of these the client usually wants to know which item it refused and why. Replacing is
#: deliberately not in here: a replacement goes where the module it replaces was, so
#: "there is no free slot" would be a wrong answer for it.
RACK_COMMANDS = ("addLocalModule",)


def explain_module_refusal(fit, itemID):
    """Why the engine would refuse ``itemID`` as a local module.

    Returns ``(message, code, params)`` -- or, when nothing here accounts for the
    refusal, ``None`` and the caller keeps the plain message. This is asked only *after*
    the engine has refused, and it mirrors the questions ``CalcAddLocalModuleCommand``
    and ``Module.fits()`` ask; the engine stays the authority on what fits. Every answer
    here is something the user can act on ("that is ammunition", "the high slots are
    full"), because "the item may not fit" is not.
    """
    from eos.saveddata.citadel import Citadel
    from eos.saveddata.module import Module
    from service.market import Market

    # Hardpoint names, as they read inside a sentence; the browser has a word per key
    # (`turret`, `launcher`) in its own catalogue
    from web.services.serialize import HARDPOINT_NAMES, slot_name

    item = Market.getInstance().getItem(itemID, eager=("attributes", "group.category"))
    if item is None:
        return ("there is no item with id {} in the game data".format(itemID),
                "unknownItem", {"itemId": itemID})

    name = item.name
    group = getattr(item.group, "name", None) or "unknown group"
    if item.isCharge:
        return ("'{0}' is ammunition ({1}), not a module: load it into a fitted module instead".format(name, group),
                "isACharge", {"name": name, "group": group})
    if not (item.isModule or item.isSubsystem):
        return ("'{0}' is a {1}, not a module, so it cannot go into a slot".format(name, group),
                "notAModule", {"name": name, "group": group})

    ship = fit.ship.item if getattr(fit, "ship", None) is not None else None
    shipName = ship.name if ship is not None else "this ship"
    try:
        mod = Module(item)
    except ValueError:
        return ("'{0}' cannot be built as a module".format(name),
                "notAModule", {"name": name, "group": group})

    slot = mod.slot
    if slot is None:
        return ("'{0}' has no slot to fit into".format(name), "noSlot", {"name": name})
    rack = slot_name(slot)
    if fit.getSlotsFree(slot) <= 0:
        return ("the fit has no free {0} slot for '{1}'".format(rack, name),
                "noFreeSlot", {"name": name, "rack": rack})
    if not fit.canFit(item):
        return ("'{0}' is restricted to certain hulls and cannot be fitted to a {1}".format(name, shipName),
                "notAllowedOnShip", {"name": name, "ship": shipName})

    # EVE will not let capital modules onto subcapital hulls, which is a volume check
    if getattr(fit, "ship", None) is not None and not isinstance(fit.ship, Citadel) \
            and fit.ship.getModifiedItemAttr("isCapitalSize", 0) != 1 and mod.isCapitalSize:
        return ("'{0}' is a capital-size module and is too big for a {1}".format(name, shipName),
                "tooBig", {"name": name, "ship": shipName})
    if slot == FittingSlot.RIG and mod.getModifiedItemAttr("rigSize") != fit.ship.getModifiedItemAttr("rigSize"):
        return ("'{0}' is the wrong size for the rig slots of a {1}".format(name, shipName),
                "wrongRigSize", {"name": name, "ship": shipName})
    hardpoint = mod.hardpoint
    if hardpoint in HARDPOINT_NAMES and fit.getHardpointsFree(hardpoint) < 1:
        return ("the fit has no free {0} hardpoint for '{1}'".format(HARDPOINT_NAMES[hardpoint], name),
                "noHardpoint", {"name": name, "hardpoint": HARDPOINT_NAMES[hardpoint]})

    # Reasons this does not cover (maxGroupFitted, an already-filled subsystem slot...)
    # still leave the fit unable to take the item, so the fallback stays true.
    return ("'{0}' does not fit this fit".format(name), "doesNotFit", {"name": name})


def _refusal(name, fit, payload):
    """The :class:`CommandFailed` to raise for a command the engine just refused."""
    itemID = payload.get("itemId")
    if name in RACK_COMMANDS and itemID is not None:
        try:
            explained = explain_module_refusal(fit, int(itemID))
        except Exception:
            pyfalog.exception("Could not explain a refused {} for item {}", name, itemID)
        else:
            message, code, params = explained
            pyfalog.warning("Refused {} for item {}: {}", name, itemID, message)
            return CommandFailed(message, code=code, params=params)
    return CommandFailed(
        "the engine refused to run {!r}; the item may not fit, or the target is invalid".format(name),
        code="engineRefused", params={"command": name})


def explain_state_refusal(module, click, positions):
    """The answer for a state click on a module that is already where it would go.

    The engine reports "nothing changed" the same way it reports a refusal, and the browser
    would read that as "the item may not fit". Naming the state is the honest answer: a
    passive module has nowhere to go, and a module can be offline already.

    Returns ``None`` when the click would move the module, so the engine stays the one that
    decides. Clicking one of several selected modules can move the others, so a multi-slot
    click is left to the engine too.
    """
    if module.isEmpty or positions:
        return None
    from eos.saveddata.module import Module

    if Module.getProposedState(module, click) != module.state:
        return None

    from web.services.serialize import state_name

    state = state_name(module.state)
    name = module.item.name
    return CommandFailed("'{}' is already {}".format(name, state),
                         code="stateUnchanged", params={"name": name, "state": state})


def _unknown_item(payload):
    """The refusal for an item id that is not in the game data, or None if it is there.

    Commands dereference their item as soon as they are built, so an id that no longer
    exists (a stale bookmark, a typo, game data that moved on) crashes the engine rather
    than being refused by it. Looking the item up first turns that into an answer.
    """
    itemID = payload.get("itemId")
    if itemID is None:
        return None
    try:
        itemID = int(itemID)
    except (TypeError, ValueError):
        raise CommandError("itemId must be an integer, got {!r}".format(itemID))

    from service.market import Market

    if Market.getInstance().getItem(itemID) is None:
        return CommandFailed(
            "there is no item with id {} in the game data".format(itemID),
            code="unknownItem", params={"itemId": itemID})
    return None


# ---------------------------------------------------------------------------------------
# Executing commands
# ---------------------------------------------------------------------------------------


def available_commands():
    """The registry, for the docs endpoint and the frontend."""
    return [
        {"name": spec["name"], "summary": spec["summary"],
         "requires": list(spec["requires"]), "args": spec["args"]}
        for spec in sorted(COMMANDS.values(), key=lambda s: s["name"])
    ]


def processor_for(userData, fitID):
    """The per-user undo stack of one fit."""
    processor = userData.command_processors.get(fitID)
    if processor is None:
        from pyfa_compat.wx_headless import CommandProcessor

        processor = userData.command_processors[fitID] = CommandProcessor(maxCommands=100)
    return processor


def history_for(userData, fitID):
    processor = userData.command_processors.get(fitID)
    if processor is None:
        return {"canUndo": False, "canRedo": False, "depth": 0,
                "undoName": None, "redoName": None}
    current = processor.GetCurrentCommand()
    commands = processor.GetCommands()
    redo = None
    if processor.CanRedo():
        if current is None:
            # Undone past the start: the next redo is the oldest command on the stack
            redo = commands[0] if commands else None
        elif current in commands:
            index = commands.index(current) + 1
            if index < len(commands):
                redo = commands[index]
    return {
        "canUndo": processor.CanUndo(),
        "canRedo": processor.CanRedo(),
        "depth": len(commands),
        "undoName": current.GetName() if current is not None else None,
        "redoName": redo.GetName() if redo is not None else None,
    }


def _load_fit(userData, fitID):
    from service.fit import Fit

    fit = Fit.getInstance().getFit(fitID)
    if fit is None:
        raise CommandError("fit {} not found".format(fitID), status_code=404)
    return fit


def execute(userData, userID, fitID, name, payload):
    """Run one registered command against one fit.

    Returns the fit's history state; the fit itself is refetched by the caller.
    """
    spec = COMMANDS.get(name)
    if spec is None:
        raise CommandError("unknown command {!r}".format(name))

    payload = payload or {}
    missing = [arg for arg in spec["requires"] if payload.get(arg) is None]
    if missing:
        raise CommandError("{} requires {}".format(name, ", ".join(missing)))

    unknown = _unknown_item(payload)
    if unknown is not None:
        raise unknown

    fit = _load_fit(userData, fitID)
    ctx = CommandContext(fit, fitID, payload, userData)
    command = spec["handler"](ctx)
    if command is None:
        raise CommandError("{} did not produce a change".format(name))

    processor = processor_for(userData, fitID)
    # Events posted by the command are routed to this user's browsers
    with publishing_as(userID):
        success = processor.Submit(command)
    if not success:
        raise _refusal(name, fit, payload)
    return history_for(userData, fitID)


def undo(userData, userID, fitID):
    processor = processor_for(userData, fitID)
    if not processor.CanUndo():
        raise CommandError("nothing to undo for fit {}".format(fitID))
    with publishing_as(userID):
        success = processor.Undo()
    if not success:
        raise CommandFailed("undo failed; the fit may have changed underneath", code="undoFailed")
    _recalc(userData, fitID)
    return history_for(userData, fitID)


def redo(userData, userID, fitID):
    processor = processor_for(userData, fitID)
    if not processor.CanRedo():
        raise CommandError("nothing to redo for fit {}".format(fitID))
    with publishing_as(userID):
        success = processor.Redo()
    if not success:
        raise CommandFailed("redo failed; the fit may have changed underneath", code="redoFailed")
    _recalc(userData, fitID)
    return history_for(userData, fitID)


def clear_history(userData, fitID):
    if fitID in userData.command_processors:
        userData.command_processors[fitID].ClearCommands()
    return history_for(userData, fitID)


def _recalc(userData, fitID):
    """Recalculate and persist after undo/redo.

    The commands do this themselves on submit; undo/redo needs it here.
    """
    from service.fit import Fit

    sFit = Fit.getInstance()
    eos.db.flush()
    sFit.recalc(fitID)
    sFit.fill(fitID)
    eos.db.commit()
