"""Fault injector catalog + CLI for the simulation world (E5)."""

from .catalog import CATALOG, injectors_for_service, resolve_effects

__all__ = ["CATALOG", "injectors_for_service", "resolve_effects"]
