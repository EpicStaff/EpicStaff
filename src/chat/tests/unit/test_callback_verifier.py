import json
from pathlib import Path

import pytest
from domain.errors import CallbackRejectedError
from infrastructure.callback_verifier import sign, verify

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "session_callback_contract.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
BODY = CONTRACT["body"].encode("utf-8")
NOW = int(CONTRACT["timestamp"])


def test_fixture_matches_django_copy():
    # src/chat/tests/contracts -> src/django_app/tests/contracts.
    django_copy = CONTRACT_PATH.parents[3] / "django_app" / "tests" / "contracts" / "session_callback_contract.json"
    assert django_copy.read_bytes() == CONTRACT_PATH.read_bytes(), "the two copies of the contract drifted"


def test_signature_vector_is_pinned():
    assert sign(CONTRACT["secret"], CONTRACT["timestamp"], BODY) == CONTRACT["signature"]


def test_canonical_body_is_what_json_dumps_sorted_compact_produces():
    assert json.dumps(CONTRACT["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False) == CONTRACT["body"]


def test_verify_accepts_the_vector_within_skew():
    verify(CONTRACT["secret"], CONTRACT["timestamp"], BODY, CONTRACT["signature"], now=NOW + 120, max_skew_seconds=300)


@pytest.mark.parametrize(
    "timestamp, signature, now",
    [
        (CONTRACT["timestamp"], CONTRACT["signature"], NOW + 301),       # stale: replayed later
        (CONTRACT["timestamp"], CONTRACT["signature"], NOW - 301),       # from the future
        (CONTRACT["timestamp"], "sha256=" + "0" * 64, NOW),              # wrong digest
        (CONTRACT["timestamp"], CONTRACT["signature"][7:], NOW),         # missing prefix
        ("not-a-number", CONTRACT["signature"], NOW),                    # bad timestamp
        (None, CONTRACT["signature"], NOW),                              # missing header
        (CONTRACT["timestamp"], None, NOW),
        (CONTRACT["timestamp"], "sha256=" + "é" * 64, NOW),              # non-ASCII: compare_digest would raise TypeError
    ],
)
def test_verify_rejects(timestamp, signature, now):
    with pytest.raises(CallbackRejectedError):
        verify(CONTRACT["secret"], timestamp, BODY, signature, now=now, max_skew_seconds=300)


def test_verify_rejects_a_changed_body():
    with pytest.raises(CallbackRejectedError):
        verify(CONTRACT["secret"], CONTRACT["timestamp"], BODY.replace(b"Hello", b"Hullo"), CONTRACT["signature"], now=NOW, max_skew_seconds=300)
