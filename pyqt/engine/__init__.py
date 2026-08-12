"""AI Modpack Builder — Python engine (port of the Node engine).

This package is the entire backend, running in-process inside the PyQt6
launcher: providers (Modrinth/CurseForge), prompt interpreter, solver,
conflict engine, downloads, exports, Mojang/loader install, the test pipeline,
the launcher, and the repair agent. No Node server is required.
"""
from .service import PyEngine  # noqa: F401
from .core import BuildLogger, EVENT_BUS  # noqa: F401

__all__ = ["PyEngine", "BuildLogger", "EVENT_BUS"]
