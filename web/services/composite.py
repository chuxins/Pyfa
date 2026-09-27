"""Composite edits: one user action made of several of pyfa's own commands.

``Gui*Command`` subclasses are the desktop's unit of undo. Where a web action
needs several of them (emptying a fit), they are batched with the same
``InternalCommandHistory`` helper the desktop uses for multi-part edits, so the
whole thing is a single undo step.
"""

from logbook import Logger

from pyfa_compat.wx_headless import Command

pyfalog = Logger(__name__)


def _cmd():
    import gui.fitCommands as cmd

    return cmd


class ClearFitCommand(Command):
    """Strip a fit down to its hull, keeping everything undoable."""

    def __init__(self, fitID):
        Command.__init__(self, True, "Clear Fit")
        self.fitID = fitID
        self.history = None

    def _build(self):
        from gui.fitCommands.helpers import InternalCommandHistory
        from service.fit import Fit

        cmd = _cmd()
        sFit = Fit.getInstance()
        fit = sFit.getFit(self.fitID)
        if fit is None:
            return None

        commands = []

        projected = []
        for container in (fit.projectedModules, fit.projectedDrones, fit.projectedFighters):
            projected.extend(container)
        projected.extend(fit.projectedFits)
        if projected:
            commands.append(cmd.GuiRemoveProjectedItemsCommand(
                fitID=self.fitID, items=projected, amount=float("inf")))

        if fit.commandFits:
            commands.append(cmd.GuiRemoveCommandFitsCommand(
                fitID=self.fitID, commandFitIDs=[commandFit.ID for commandFit in fit.commandFits]))

        for container, command in (
            (fit.boosters, cmd.GuiRemoveBoostersCommand),
            (fit.implants, cmd.GuiRemoveImplantsCommand),
            (fit.cargo, None),
            (fit.fighters, cmd.GuiRemoveLocalFightersCommand),
            (fit.drones, cmd.GuiRemoveLocalDronesCommand),
        ):
            if not container:
                continue
            if command is None:
                commands.append(cmd.GuiRemoveCargosCommand(
                    fitID=self.fitID, itemIDs=[entry.itemID for entry in container]))
            elif container is fit.drones:
                commands.append(command(fitID=self.fitID,
                                        positions=list(range(len(container))),
                                        amount=float("inf")))
            else:
                commands.append(command(fitID=self.fitID, positions=list(range(len(container)))))

        modulePositions = [position for position, module in enumerate(fit.modules) if not module.isEmpty]
        if modulePositions:
            commands.append(cmd.GuiRemoveLocalModuleCommand(
                fitID=self.fitID, positions=modulePositions))

        self.history = InternalCommandHistory()
        return commands

    def Do(self):
        commands = self._build()
        if not commands:
            return False
        return self.history.submitBatch(*commands)

    def Undo(self):
        if self.history is None:
            return False
        return self.history.undoAll()
