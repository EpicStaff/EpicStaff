"""Importing this package wires the app: dependencies and lifespan hooks."""

from manager.bootstrap import di, error_handlers, lifespans

__all__ = ["di", "error_handlers", "lifespans"]
