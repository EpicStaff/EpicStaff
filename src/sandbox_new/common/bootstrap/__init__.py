"""Importing this package wires the cross-service runtime (queues + background runners)."""

from common.bootstrap import lifespan, logging

__all__ = ["lifespan", "logging"]
