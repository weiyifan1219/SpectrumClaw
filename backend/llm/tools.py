"""Compatibility entrypoint for registering built-in tools.

Tool definitions live exclusively in :mod:`backend.tools.registry`.
"""

from __future__ import annotations


def register_default_tools() -> None:
    from ..tools.registry import register_all

    register_all()
