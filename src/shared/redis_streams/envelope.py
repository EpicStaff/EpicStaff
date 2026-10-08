import json
from collections.abc import Callable

from pydantic import BaseModel


class StreamEnvelope(BaseModel):
    type: str
    correlation_id: str
    payload: dict

    def to_fields(self, json_default: Callable[[object], object] | None = None) -> dict[str, str]:
        """Stream entry fields; ``json_default`` is passed to ``json.dumps`` as ``default``."""
        return {
            "type": self.type,
            "correlation_id": self.correlation_id,
            "payload": json.dumps(self.payload, default=json_default),
        }

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "StreamEnvelope":
        return cls(
            type=fields["type"],
            correlation_id=fields["correlation_id"],
            payload=json.loads(fields["payload"]),
        )
