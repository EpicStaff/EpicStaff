"""Shared framework foundation: reusable base classes and utilities."""

from .base.entity import Entity
from .base.factory import Factory
from .base.schema import Schema
from .base.unit_of_work import AbstractUnitOfWork
from .base.value_object import ValueObject
from .utils.env import Env, EnvironmentBlankError, EnvironmentNotFoundError

__all__ = [
    "AbstractUnitOfWork",
    "Entity",
    "Env",
    "EnvironmentBlankError",
    "EnvironmentNotFoundError",
    "Factory",
    "Schema",
    "ValueObject",
]
