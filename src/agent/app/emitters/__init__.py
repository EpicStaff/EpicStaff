"""
Layer 1 — Emitters sub-package (Bridge pattern).

Re-exports the ``Emitter`` ABC and the only concrete implementation built in
this plan.  Future emitters (e.g. ``RedisStreamDeltaEmitter`` for streaming
chat) will be added here without touching consumer code.
"""

from app.emitters.base import Emitter
from app.emitters.redis_batch import RedisStreamBatchEmitter

__all__ = ["Emitter", "RedisStreamBatchEmitter"]
