"""Keep the bundled PySide6 DLL search paths active in frozen Windows builds."""

import os
import sys


if sys.platform == "win32" and getattr(sys, "frozen", False):
    _pyside_dir = os.path.join(sys._MEIPASS, "PySide6")
    _shiboken_dir = os.path.join(sys._MEIPASS, "shiboken6")
    # Keep these handles on sys for the entire process lifetime. Dropping them
    # unregisters the directories and makes PySide imports depend on PATH.
    _dll_directory_handles = getattr(sys, "_pyside_dll_directory_handles", [])
    for _directory in (_pyside_dir, _shiboken_dir):
        if os.path.isdir(_directory):
            _dll_directory_handles.append(os.add_dll_directory(_directory))
    sys._pyside_dll_directory_handles = _dll_directory_handles
    if os.path.isdir(_pyside_dir):
        os.environ["PATH"] = _pyside_dir + os.pathsep + os.environ.get("PATH", "")
