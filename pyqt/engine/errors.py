"""Shared engine errors (moved here when the legacy HTTP client api.py was
deleted — the in-process bridge needed ApiError without the whole client)."""


class ApiError(Exception):
    """Engine error surfaced to the UI with an honest, human-readable message."""
