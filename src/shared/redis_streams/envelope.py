import json

from pydantic import BaseModel


class StreamEnvelope(BaseModel):
    type: str
    correlation_id: str
    payload: dict

    def to_fields(self) -> dict[str, str]:
        return self.encoded_fields(self.type, self.correlation_id, json.dumps(self.payload))

    @staticmethod
    def encoded_fields(
        envelope_type: str, correlation_id: str, encoded_payload: str
    ) -> dict[str, str]:
        """Stream entry fields for a payload the producer has already encoded as JSON."""
        return {
            "type": envelope_type,
            "correlation_id": correlation_id,
            "payload": encoded_payload,
        }

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "StreamEnvelope":
        return cls(
            type=fields["type"],
            correlation_id=fields["correlation_id"],
            payload=json.loads(fields["payload"]),
        )
