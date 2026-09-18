from __future__ import annotations

from dataclasses import dataclass

from app.loop.agent_loop import AgentLoop
from app.resources.resolver import AgentResolver


@dataclass(frozen=True)
class RunnerDependencies:
    resolver: AgentResolver
    loop: AgentLoop
