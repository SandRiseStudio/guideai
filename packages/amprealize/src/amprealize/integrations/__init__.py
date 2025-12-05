"""Amprealize integrations for web frameworks.

This module provides optional integrations for popular web frameworks,
allowing easy embedding of Amprealize functionality into existing applications.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fastapi import create_amprealize_routes

__all__ = ["create_amprealize_routes"]
