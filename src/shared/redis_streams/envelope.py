import json

from pydantic import BaseModel


class StreamEnvelope(BaseModel):
    type: str
    correlation_id: str
    payload: dict

    def to_fields(self) -> dict[str, str]:
        return {
            "type": self.type,
            "correlation_id": self.correlation_id,
            "payload": json.dumps(self.payload),
        }

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "StreamEnvelope":
        return cls(
            type=fields["type"],
            correlation_id=fields["correlation_id"],
            payload=json.loads(fields["payload"]),
        )
