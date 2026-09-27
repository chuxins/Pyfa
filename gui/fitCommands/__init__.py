"""Undoable fit commands, resolved lazily.

Each command lives in its own module, and the ones under ``gui/`` import
``gui.mainFrame`` -- dragging in the entire wxPython widget tree. The web backend
needs the ``calc/`` commands but must not import any widgets, so the ``Gui*``
commands are resolved on first attribute access instead of at import time:

    import gui.fitCommands as cmd
    cmd.GuiAddLocalModuleCommand(fitID=fitID, itemID=itemID)

Names are re-exported exactly as before, so desktop callers are unaffected.
"""

from importlib import import_module


_COMMAND_MODULES = {
    'GuiAddBoosterCommand': '.gui.booster.add',
    'GuiChangeBoosterMetaCommand': '.gui.booster.changeMeta',
    'GuiImportBoostersCommand': '.gui.booster.imprt',
    'GuiRemoveBoostersCommand': '.gui.booster.remove',
    'GuiToggleBoosterSideEffectStateCommand': '.gui.booster.sideEffectToggleState',
    'GuiToggleBoosterStatesCommand': '.gui.booster.toggleStates',
    'GuiAddCargoCommand': '.gui.cargo.add',
    'GuiChangeCargosAmountCommand': '.gui.cargo.changeAmount',
    'GuiChangeCargoMetasCommand': '.gui.cargo.changeMetas',
    'GuiImportCargosCommand': '.gui.cargo.imprt',
    'GuiRemoveCargosCommand': '.gui.cargo.remove',
    'GuiAddCommandFitsCommand': '.gui.commandFit.add',
    'GuiRemoveCommandFitsCommand': '.gui.commandFit.remove',
    'GuiToggleCommandFitStatesCommand': '.gui.commandFit.toggleStates',
    'GuiAddCommandLinkCommand': '.gui.commandLink.add',
    'GuiRemoveCommandLinksCommand': '.gui.commandLink.remove',
    'GuiToggleCommandLinkStatesCommand': '.gui.commandLink.toggleStates',
    'GuiChangeFitPilotSecurityCommand': '.gui.fitPilotSecurity',
    'GuiRenameFitCommand': '.gui.fitRename',
    'GuiToggleFittingRestrictionsCommand': '.gui.fitRestrictionToggle',
    'GuiChangeFitSystemSecurityCommand': '.gui.fitSystemSecurity',
    'GuiAddImplantCommand': '.gui.implant.add',
    'GuiChangeImplantLocationCommand': '.gui.implant.changeLocation',
    'GuiChangeImplantMetaCommand': '.gui.implant.changeMeta',
    'GuiImportImplantsCommand': '.gui.implant.imprt',
    'GuiRemoveImplantsCommand': '.gui.implant.remove',
    'GuiAddImplantSetCommand': '.gui.implant.setAdd',
    'GuiToggleImplantStatesCommand': '.gui.implant.toggleStates',
    'GuiRebaseItemsCommand': '.gui.itemsRebase',
    'GuiAddLocalDroneCommand': '.gui.localDrone.add',
    'GuiChangeLocalDroneAmountCommand': '.gui.localDrone.changeAmount',
    'GuiChangeLocalDroneMetasCommand': '.gui.localDrone.changeMetas',
    'GuiChangeLocalDroneMutationCommand': '.gui.localDrone.changeMutation',
    'GuiCloneLocalDroneCommand': '.gui.localDrone.clone',
    'GuiImportLocalDronesCommand': '.gui.localDrone.imprt',
    'GuiConvertMutatedLocalDroneCommand': '.gui.localDrone.mutatedConvert',
    'GuiImportLocalMutatedDroneCommand': '.gui.localDrone.mutatedImport',
    'GuiRevertMutatedLocalDroneCommand': '.gui.localDrone.mutatedRevert',
    'GuiRemoveLocalDronesCommand': '.gui.localDrone.remove',
    'GuiSplitLocalDroneStackCommand': '.gui.localDrone.stackSplit',
    'GuiMergeLocalDroneStacksCommand': '.gui.localDrone.stacksMerge',
    'GuiToggleLocalDroneStatesCommand': '.gui.localDrone.toggleStates',
    'GuiToggleLocalFighterAbilityStateCommand': '.gui.localFighter.abilityToggleState',
    'GuiAddLocalFighterCommand': '.gui.localFighter.add',
    'GuiChangeLocalFighterAmountCommand': '.gui.localFighter.changeAmount',
    'GuiChangeLocalFighterMetasCommand': '.gui.localFighter.changeMetas',
    'GuiImportLocalFightersCommand': '.gui.localFighter.imprt',
    'GuiRemoveLocalFightersCommand': '.gui.localFighter.remove',
    'GuiToggleLocalFighterStatesCommand': '.gui.localFighter.toggleStates',
    'GuiAddLocalModuleCommand': '.gui.localModule.add',
    'GuiChangeLocalModuleChargesCommand': '.gui.localModule.changeCharges',
    'GuiChangeLocalModuleMetasCommand': '.gui.localModule.changeMetas',
    'GuiChangeLocalModuleMutationCommand': '.gui.localModule.changeMutation',
    'GuiChangeLocalModuleSpoolCommand': '.gui.localModule.changeSpool',
    'GuiChangeLocalModuleStatesCommand': '.gui.localModule.changeStates',
    'GuiCloneLocalModuleCommand': '.gui.localModule.clone',
    'GuiFillWithNewLocalModulesCommand': '.gui.localModule.fillAdd',
    'GuiFillWithClonedLocalModulesCommand': '.gui.localModule.fillClone',
    'GuiConvertMutatedLocalModuleCommand': '.gui.localModule.mutatedConvert',
    'GuiImportLocalMutatedModuleCommand': '.gui.localModule.mutatedImport',
    'GuiRevertMutatedLocalModuleCommand': '.gui.localModule.mutatedRevert',
    'GuiRemoveLocalModuleCommand': '.gui.localModule.remove',
    'GuiReplaceLocalModuleCommand': '.gui.localModule.replace',
    'GuiSwapLocalModulesCommand': '.gui.localModule.swap',
    'GuiCargoToLocalModuleCommand': '.gui.localModuleCargo.cargoToLocalModule',
    'GuiLocalModuleToCargoCommand': '.gui.localModuleCargo.localModuleToCargo',
    'GuiChangeProjectedItemsProjectionRangeCommand': '.gui.projectedChangeProjectionRange',
    'GuiChangeProjectedItemStatesCommand': '.gui.projectedChangeStates',
    'GuiAddProjectedDroneCommand': '.gui.projectedDrone.add',
    'GuiChangeProjectedDroneAmountCommand': '.gui.projectedDrone.changeAmount',
    'GuiChangeProjectedDroneMetasCommand': '.gui.projectedDrone.changeMetas',
    'GuiToggleProjectedFighterAbilityStateCommand': '.gui.projectedFighter.abilityToggleState',
    'GuiAddProjectedFighterCommand': '.gui.projectedFighter.add',
    'GuiChangeProjectedFighterAmountCommand': '.gui.projectedFighter.changeAmount',
    'GuiChangeProjectedFighterMetasCommand': '.gui.projectedFighter.changeMetas',
    'GuiAddProjectedFitsCommand': '.gui.projectedFit.add',
    'GuiChangeProjectedFitAmountCommand': '.gui.projectedFit.changeAmount',
    'GuiAddProjectedModuleCommand': '.gui.projectedModule.add',
    'GuiChangeProjectedModuleChargesCommand': '.gui.projectedModule.changeCharges',
    'GuiChangeProjectedModuleMetasCommand': '.gui.projectedModule.changeMetas',
    'GuiChangeProjectedModuleSpoolCommand': '.gui.projectedModule.changeSpool',
    'GuiRemoveProjectedItemsCommand': '.gui.projectedRemove',
    'GuiChangeShipModeCommand': '.gui.shipModeChange',
}


def __getattr__(name):
    moduleName = _COMMAND_MODULES.get(name)
    if moduleName is None:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    value = getattr(import_module(moduleName, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_COMMAND_MODULES))
