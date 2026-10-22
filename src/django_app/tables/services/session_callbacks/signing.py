import hashlib
import hmac
import json

SIGNATURE_HEADER = "X-EpicStaff-Signature"
TIMESTAMP_HEADER = "X-EpicStaff-Timestamp"
SESSION_ID_HEADER = "X-EpicStaff-Session-Id"


def canonical_body(payload: dict) -> str:
    """Serialize the payload exactly as it is signed and sent: sorted keys, no spaces."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(secret: str, timestamp: str, body: str) -> str:
    """Return the `sha256=<hex>` HMAC of `timestamp + "." + body` under `secret`."""
    digest = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"sha256={digest}"
