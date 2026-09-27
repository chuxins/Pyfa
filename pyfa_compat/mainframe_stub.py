"""A stand-in for ``gui.mainFrame`` so pyfa's own fit commands can run headlessly.

``gui/fitCommands/gui/**`` are the real, undoable editing commands: they wrap the
``calc`` commands, run the state checks, recalculate, fill and notify. They are
exactly what the desktop application uses when a user drags a module into a slot.

Their only GUI dependency is ``gui.mainFrame.MainFrame.getInstance()``, and always
in the same way: as the *target* of ``wx.PostEvent``. Everything else they touch
(``gui.globalEvents``, ``gui.fitCommands.calc.*``, the service layer) is already
GUI-free or covered by the wx shim.

So registering this stub makes the whole editing layer reusable by the web server.
The event target is inert here; notifications are re-routed to the browser by the
``PostEvent`` hook in :mod:`web.events`.
"""

import sys
import types

from pyfa_compat import HeadlessUnsupportedError


class HeadlessMainFrame:
    """Accepts events destined for the desktop main window and ignores them."""

    _instance = None

    @classmethod
    def getInstance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __repr__(self):
        return "<HeadlessMainFrame>"

    def __getattr__(self, name):
        raise HeadlessUnsupportedError(
            "MainFrame.{} was used in headless mode. Only wx.PostEvent is supported "
            "as an event target; the web server has no main window.".format(name)
        )


def is_installed():
    module = sys.modules.get("gui.mainFrame")
    return module is not None and getattr(module, "__pyfa_headless__", False)


def install():
    """Make ``import gui.mainFrame`` resolve to the stub.

    Does nothing if the real GUI module is already loaded (which would mean this
    process is the desktop application, not the server).
    """
    existing = sys.modules.get("gui.mainFrame")
    if existing is not None:
        if getattr(existing, "__pyfa_headless__", False):
            return True
        return False

    module = types.ModuleType("gui.mainFrame")
    module.__pyfa_headless__ = True
    module.MainFrame = HeadlessMainFrame
    sys.modules["gui.mainFrame"] = module

    # Keep the parent package consistent so `from gui import mainFrame` works
    import gui

    setattr(gui, "mainFrame", module)
    return True
