# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AI Modpack Builder (PyQt6 desktop launcher + in-process engine).

Build from this directory:
    ../.venv/Scripts/python -m PyInstaller amb.spec --distpath ../../dist --workpath ../../build/pyi --noconfirm --clean

Output: ../../dist/AI Modpack Builder/AI Modpack Builder.exe  (one-folder, windowed)
"""
from pathlib import Path

APP = "AI Modpack Builder"
ROOT = Path(SPECPATH).resolve().parent  # pyqt/

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets"), "assets"),   # fonts (Inter, JetBrains Mono)
        (str(ROOT / "app.ico"), "."),       # window/taskbar icon
    ],
    hiddenimports=["_amb_secrets"],  # build-time generated, git-ignored (may be absent)
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "doctest", "pdb",
        "PIL", "PyQt6.QtWebEngine", "PyQt6.QtQuick", "PyQt6.QtMultimedia",
        "PyQt6.QtQml", "PyQt6.Qt3DCore", "PyQt6.QtBluetooth", "PyQt6.QtCharts",
        "PyQt6.QtDataVisualization", "PyQt6.QtDBus", "PyQt6.QtDesigner",
        "PyQt6.QtHelp", "PyQt6.QtLocation", "PyQt6.QtMultimediaWidgets",
        "PyQt6.QtNetworkAuth", "PyQt6.QtNfc", "PyQt6.QtOpenGL", "PyQt6.QtPositioning",
        "PyQt6.QtPdf", "PyQt6.QtPrintSupport", "PyQt6.QtQuick3D", "PyQt6.QtRemoteObjects",
        "PyQt6.QtScxml", "PyQt6.QtSensors", "PyQt6.QtSerialPort", "PyQt6.QtSql",
        "PyQt6.QtStateMachine", "PyQt6.QtTest", "PyQt6.QtTextToSpeech",
        "PyQt6.QtUiTools", "PyQt6.QtWebChannel", "PyQt6.QtWebSockets", "PyQt6.QtX11Extras",
        "PyQt6.QtXml",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP,
)
