"""A minimal, honest stand-in for the parts of wxPython that pyfa's non-GUI code uses.

This module is registered as ``sys.modules['wx']`` by :mod:`pyfa_compat` when the
real wxPython is not installed. Only these are implemented:

* translations -- ``GetTranslation``, ``Locale``, ``Translations``
* GUI-thread marshalling -- ``CallAfter``, ``PostEvent`` (routed to a dispatcher)
* undo/redo -- ``Command``, ``CommandProcessor``
* odds and ends used at import time -- ``Colour``, a few ``ID_*``/style constants,
  ``__version__``

Anything else raises :class:`pyfa_compat.HeadlessUnsupportedError` so that an
unexpected GUI code path fails loudly instead of silently misbehaving.
"""

import os
import sys
import threading
import types

__pyfa_headless__ = True

_LOCALE_DIR = None
_LANGUAGE = None
_translation = None

_call_after_hook = None
_post_event_hook = None
_hook_lock = threading.Lock()


class HeadlessUnsupportedError(NotImplementedError):
    pass


# --------------------------------------------------------------------------------------
# i18n
# --------------------------------------------------------------------------------------


def configure_i18n(locale_dir=None, language=None):
    """Point ``GetTranslation`` at pyfa's locale catalogs.

    Falls back to an identity translation when the catalog cannot be loaded, which
    is the same behaviour wxWidgets has for a missing catalog.
    """
    global _LOCALE_DIR, _LANGUAGE, _translation

    if locale_dir is not None:
        _LOCALE_DIR = locale_dir
    if language is not None:
        _LANGUAGE = language

    _translation = None

    if not _LOCALE_DIR or not _LANGUAGE:
        return None

    mo_path = os.path.join(_LOCALE_DIR, _LANGUAGE, "LC_MESSAGES", "lang.mo")
    if os.path.isfile(mo_path):
        try:
            import gettext

            with open(mo_path, "rb") as fp:
                _translation = gettext.GNUTranslations(fp)
            return _translation
        except Exception:
            _translation = None
    return None


def GetTranslation(text):
    """Drop-in replacement for ``wx.GetTranslation``."""
    if _translation is None:
        return text
    try:
        return _translation.gettext(text)
    except Exception:
        return text


class _LanguageInfo:
    """What ``wx.Locale.FindLanguageInfo`` returns, in the parts pyfa uses."""

    def __init__(self, language):
        self.Language = language
        self.LanguageName = language
        self.CanonicalName = language
        self.LocaleName = language


class Locale:
    def __init__(self, language=0):
        self._language = language

    def IsOk(self):
        return True

    def AddCatalog(self, catalog):
        configure_i18n(language=_LANGUAGE)
        return True

    @staticmethod
    def AddCatalogLookupPathPrefix(path):
        global _LOCALE_DIR
        _LOCALE_DIR = path

    @staticmethod
    def FindLanguageInfo(language):
        if not language:
            return None
        return _LanguageInfo(language)


class _Translations:
    @staticmethod
    def Get():
        return _Translations()

    def GetAvailableTranslations(self, catalog=None):
        """Language codes pyfa ships a catalog for, discovered on disk."""
        if not _LOCALE_DIR or not os.path.isdir(_LOCALE_DIR):
            return []
        names = []
        for name in sorted(os.listdir(_LOCALE_DIR)):
            mo = os.path.join(_LOCALE_DIR, name, "LC_MESSAGES", "lang.mo")
            po = os.path.join(_LOCALE_DIR, name, "LC_MESSAGES", "lang.po")
            if os.path.isfile(mo) or os.path.isfile(po):
                names.append(name)
        return names


class Translations:
    @staticmethod
    def Get():
        return _Translations.Get()


# --------------------------------------------------------------------------------------
# GUI thread marshalling
# --------------------------------------------------------------------------------------


def set_call_after_hook(hook):
    """Route ``CallAfter`` through ``hook(func, args, kwargs)``."""
    global _call_after_hook
    with _hook_lock:
        _call_after_hook = hook


def set_post_event_hook(hook):
    """Route ``PostEvent`` through ``hook(dest, event)``."""
    global _post_event_hook
    with _hook_lock:
        _post_event_hook = hook


def CallAfter(func, *args, **kwargs):
    """Run ``func`` on the GUI thread, or as close to it as headless mode gets.

    With no hook registered this runs synchronously, which keeps single-threaded
    callers (tests, scripts) working.
    """
    hook = _call_after_hook
    if hook is not None:
        return hook(func, args, kwargs)
    return func(*args, **kwargs)


def PostEvent(dest, event):
    hook = _post_event_hook
    if hook is not None:
        return hook(dest, event)
    return True


# --------------------------------------------------------------------------------------
# undo / redo
# --------------------------------------------------------------------------------------


class Command:
    """Base class mirroring ``wx.Command``."""

    def __init__(self, canUndo=True, name=""):
        self._canUndo = canUndo
        self._name = name

    @property
    def CanUndo(self):
        return self._canUndo

    @CanUndo.setter
    def CanUndo(self, value):
        self._canUndo = value

    @property
    def Name(self):
        return self._name

    @Name.setter
    def Name(self, value):
        self._name = value

    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def Do(self):
        return False

    def Undo(self):
        return False

    def Redo(self):
        return self.Do()


class CommandProcessor:
    """Undo/redo stack mirroring the parts of ``wx.CommandProcessor`` pyfa relies on."""

    def __init__(self, maxCommands=-1):
        self._commands = []
        self._maxCommands = maxCommands
        self._current = -1
        self._editMenu = None

    # -- introspection ------------------------------------------------------------------

    @property
    def Commands(self):
        """The live list of commands, newest last. pyfa's InternalCommandHistory reads it."""
        return self._commands

    def GetCommands(self):
        return list(self._commands)

    def GetCurrentCommand(self):
        if self._current < 0:
            return None
        return self._commands[self._current]

    def GetMaxCommands(self):
        return self._maxCommands

    def SetMaxCommands(self, maxCommands):
        self._maxCommands = maxCommands
        self._trim()

    def GetEditMenu(self):
        return self._editMenu

    def SetEditMenu(self, menu):
        self._editMenu = menu

    # -- mutation -----------------------------------------------------------------------

    def Submit(self, command, storeIt=True):
        """Execute ``command``; on success push it onto the stack."""
        if not command.Do():
            return False
        if storeIt:
            # Anything that had been undone is no longer reachable
            del self._commands[self._current + 1:]
            self._commands.append(command)
            self._current = len(self._commands) - 1
            self._trim()
        return True

    def Undo(self):
        if self._current < 0:
            return False
        command = self._commands[self._current]
        if not command.Undo():
            return False
        self._current -= 1
        return True

    def Redo(self):
        if self._current >= len(self._commands) - 1:
            return False
        command = self._commands[self._current + 1]
        if not command.Redo():
            return False
        self._current += 1
        return True

    def ClearCommands(self):
        self._commands = []
        self._current = -1

    def CanUndo(self):
        return self._current >= 0

    def CanRedo(self):
        return self._current < len(self._commands) - 1

    def MarkAsSaved(self):
        pass

    def IsDirty(self):
        return False

    def _trim(self):
        if self._maxCommands <= 0:
            return
        overflow = len(self._commands) - self._maxCommands
        if overflow > 0:
            del self._commands[:overflow]
            self._current = max(-1, self._current - overflow)


# --------------------------------------------------------------------------------------
# Import-time odds and ends
# --------------------------------------------------------------------------------------


class Colour:
    """Just enough of ``wx.Colour`` for colour tables built at import time."""

    def __init__(self, red=0, green=0, blue=0, alpha=255):
        self._rgba = (int(red), int(green), int(blue), int(alpha))

    def Get(self, includeAlpha=False):
        if includeAlpha:
            return self._rgba
        return self._rgba[:3]

    def GetAsString(self, flags=0):
        return self.toHex()

    def toHex(self):
        red, green, blue, _ = self._rgba
        return "#{:02x}{:02x}{:02x}".format(red, green, blue)

    @property
    def Red(self):
        return self._rgba[0]

    @property
    def Green(self):
        return self._rgba[1]

    @property
    def Blue(self):
        return self._rgba[2]

    @property
    def Alpha(self):
        return self._rgba[3]

    def IsOk(self):
        return True

    def __eq__(self, other):
        if isinstance(other, Colour):
            return self._rgba == other._rgba
        return NotImplemented

    def __hash__(self):
        return hash(self._rgba)

    def __repr__(self):
        return "wx.Colour{}".format(self._rgba)


class _UnsupportedWidget:
    """Placeholder that fails on construction rather than silently doing nothing."""

    def __init__(self, *args, **kwargs):
        raise HeadlessUnsupportedError(
            "{} is a wxPython GUI class and cannot be used in headless mode. "
            "Use the GUI application for this code path, or move the call behind "
            "an explicit capability check.".format(type(self).__name__)
        )


class App(_UnsupportedWidget):
    pass


class MessageDialog(_UnsupportedWidget):
    pass


def MessageBox(*args, **kwargs):
    raise HeadlessUnsupportedError("wx.MessageBox is not available in headless mode")


# Style/id constants that pyfa references at import time
ID_OK = 5100
ID_CANCEL = 5101
ID_YES = 5103
ID_NO = 5104
ID_UNDO = 5031
ID_REDO = 5032
OK = 0x0004
CANCEL = 0x0010
YES = 0x0002
NO = 0x0008
ICON_ERROR = 0x0200
ICON_INFORMATION = 0x0400
STAY_ON_TOP = 0x8000


class _MouseState:
    def GetModifiers(self):
        return 0


def GetMouseState():
    return _MouseState()


# Version info, so `from wx.__version__ import VERSION` in prereqsCheck.py works
VERSION = (0, 0, 0)
VERSION_STRING = "headless"
wxWidgets_version = "headless"


# --------------------------------------------------------------------------------------
# Submodules
# --------------------------------------------------------------------------------------


def _new_event():
    """Stand-in for ``wx.lib.newevent.NewEvent``.

    Returns ``(event_class, event_type)`` where the event class is a small
    attribute bag, mirroring how pyfa's globalEvents module uses it.
    """

    class _Event:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def __repr__(self):
            attrs = ", ".join("{}={!r}".format(k, v) for k, v in sorted(self.__dict__.items()))
            return "<{} {}>".format(type(self).__name__, attrs)

    event_type = object()
    return _Event, event_type


def _install_submodules():
    lib = types.ModuleType("wx.lib")
    newevent = types.ModuleType("wx.lib.newevent")
    newevent.NewEvent = _new_event
    newevent.NewCommandEvent = _new_event
    lib.newevent = newevent

    version_mod = types.ModuleType("wx.__version__")
    version_mod.VERSION = VERSION
    version_mod.VERSION_STRING = VERSION_STRING

    this = sys.modules[__name__]
    this.lib = lib
    this.__version__ = version_mod

    sys.modules["wx.lib"] = lib
    sys.modules["wx.lib.newevent"] = newevent
    sys.modules["wx.__version__"] = version_mod


_install_submodules()


def install():
    """Register this module as ``wx`` so ``import wx`` resolves here."""
    this = sys.modules[__name__]
    sys.modules['wx'] = this
    # Submodules were built for the alias name too
    sys.modules['wx.lib'].__name__ = 'wx.lib'
    sys.modules['wx.lib.newevent'].__name__ = 'wx.lib.newevent'
    sys.modules['wx.__version__'].__name__ = 'wx.__version__'
    return True


def __getattr__(name):
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    raise HeadlessUnsupportedError(
        "wx.{} is not implemented by pyfa's headless compatibility layer. "
        "This usually means GUI code was reached from the web backend.".format(name)
    )
