from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from datetime import datetime, timezone


@dataclass
class Event:
    type: str
    flow_name: str
    timestamp: datetime = field(init=False)

    def __post_init__(self):
        now = datetime.now(timezone.utc)
        self.timestamp = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class FlowStartedEvent(Event):
    pass


@dataclass
class MethodExecutionStartedEvent(Event):
    method_name: str


@dataclass
class MethodExecutionFinishedEvent(Event):
    method_name: str


@dataclass
class FlowFinishedEvent(Event):
    result: Optional[Any] = None
