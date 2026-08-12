@echo off
REM ============================================================
REM  AI Modpack Builder - desktop launcher
REM  One self-contained system: the Python engine runs inside the
REM  PyQt6 app (no Node server, no browser, no localhost).
REM ============================================================
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"

REM --- 1. Launch the PyQt6 desktop app (no console window) ---
start "" "%ROOT%\pyqt\.venv\Scripts\pythonw.exe" "%ROOT%\pyqt\main.py"
endlocal
