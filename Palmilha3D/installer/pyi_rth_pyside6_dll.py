"""Load this application's bundled Qt Core before any other Qt libraries."""

import ctypes
import os
import sys


if sys.platform == "win32" and getattr(sys, "frozen", False):
    _pyside_dir = os.path.join(sys._MEIPASS, "PySide6")
    _shiboken_dir = os.path.join(sys._MEIPASS, "shiboken6")
    if os.path.isdir(_shiboken_dir):
        os.add_dll_directory(_shiboken_dir)
    os.add_dll_directory(_pyside_dir)
    # Pin QtCore to the version shipped beside the PySide6 extension modules.
    # This avoids resolving a same-named Qt DLL from another installed program.
    _qt_core_handle = ctypes.WinDLL(os.path.join(_pyside_dir, "Qt6Core.dll"))
