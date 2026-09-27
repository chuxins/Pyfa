"""Headless compatibility layer for running pyfa outside of wxPython.

The desktop application in ``gui/`` needs wxPython. The calculation engine
(``eos/``) and most of the service layer (``service/``) do not, but a handful of
modules there still touch wx for three things:

* translations (``wx.GetTranslation``)
* marshalling work onto the GUI thread (``wx.CallAfter`` / ``wx.PostEvent``)
* the undo/redo stack (``wx.Command`` / ``wx.CommandProcessor``)

:func:`install` registers :mod:`pyfa_compat.wx_headless` as the ``wx`` module when
the real wxPython is unavailable, so those modules import and run unchanged. GUI
widget APIs are deliberately *not* stubbed: touching one raises
``HeadlessUnsupportedError`` with a clear message instead of silently doing
nothing.
"""

import sys

from logbook import Logger

pyfalog = Logger(__name__)

__all__ = ["install", "is_headless", "HeadlessUnsupportedError"]


class HeadlessUnsupportedError(NotImplementedError):
    """Raised when GUI-only wxPython functionality is used in headless mode."""


_installed = False


def is_headless():
    """True when the headless wx shim is (or would be) in use."""
    wx = sys.modules.get("wx")
    if wx is not None:
        return getattr(wx, "__pyfa_headless__", False)
    return not _real_wx_available()


def _real_wx_available():
    try:
        import wx  # noqa: F401
    except Exception:
        return False
    return not getattr(sys.modules["wx"], "__pyfa_headless__", False)


def install(force=False):
    """Make ``import wx`` resolve to the headless shim.

    Does nothing when real wxPython is importable, unless ``force`` is set.
    Returns True when the shim is active after the call.
    """
    global _installed

    if _installed:
        return True

    if not force and _real_wx_available():
        pyfalog.debug("Real wxPython is available, not installing headless shim")
        return False

    from pyfa_compat import mainframe_stub, wx_headless

    wx_headless.install()
    # pyfa's undoable fit commands are only usable once `import gui.mainFrame`
    # stops pulling in the widget tree
    mainframe_stub.install()
    _installed = True
    pyfalog.info("Headless wx compatibility layer installed")
    return True
