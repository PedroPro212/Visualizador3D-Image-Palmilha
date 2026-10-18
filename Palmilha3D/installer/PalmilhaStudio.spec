# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Codigos/Visualizador3D-Image-Palmilha/Palmilha3D/app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['PySide6.QtOpenGLWidgets', 'PySide6.QtOpenGL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PalmilhaStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PalmilhaStudio',
)
