import hashlib
import hmac
import json
from pathlib import Path

from tables.services.session_callbacks.signing import canonical_body, sign

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts" / "session_callback_contract.json").read_text(encoding="utf-8")
)


def test_canonical_body_is_sorted_and_compact():
    assert canonical_body(CONTRACT["payload"]) == CONTRACT["body"]


def test_signature_matches_contract_vector():
    expected = "sha256=" + hmac.new(
        CONTRACT["secret"].encode(),
        f"{CONTRACT['timestamp']}.{CONTRACT['body']}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert CONTRACT["signature"] == expected, "update the fixture's signature to this value"
    assert sign(CONTRACT["secret"], CONTRACT["timestamp"], CONTRACT["body"]) == expected
