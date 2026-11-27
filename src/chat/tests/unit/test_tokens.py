import base64
import hashlib
import hmac
import time

import jwt
import pytest
from application.tokens import identity_subject, issue_visitor_token, new_callback_secret, visitor_token_hash
from domain.errors import InvalidIdentityError

SECRET = "identity-secret"


def test_visitor_token_and_hash():
    token, digest = issue_visitor_token()
    assert len(token) >= 32 and digest == visitor_token_hash(token) and len(digest) == 64


def test_callback_secret_is_long_enough_for_django():
    assert len(new_callback_secret()) >= 32


def test_identity_subject_accepts_valid_token():
    now = int(time.time())
    token = jwt.encode({"sub": "user-9", "exp": now + 600}, SECRET, algorithm="HS256")
    assert identity_subject(token, SECRET, now=now, max_lifetime_seconds=3600) == "user-9"
    widest = jwt.encode({"sub": "x" * 255, "exp": now + 600}, SECRET, algorithm="HS256")
    assert identity_subject(widest, SECRET, now=now, max_lifetime_seconds=3600) == "x" * 255


@pytest.mark.parametrize(
    "claims, secret",
    [
        ({"sub": "u", "exp": int(time.time()) - 1}, SECRET),            # expired
        ({"sub": "u", "exp": int(time.time()) + 7200}, SECRET),         # lives longer than an hour
        ({"exp": int(time.time()) + 60}, SECRET),                        # no subject
        ({"sub": "u", "exp": int(time.time()) + 60}, "other-secret"),   # wrong key
        ({"sub": "x" * 256, "exp": int(time.time()) + 60}, SECRET),     # wider than the subject column
        ({"sub": "user\x00-9", "exp": int(time.time()) + 60}, SECRET),  # NUL: the subject column cannot hold it
        ({"sub": "user\ud800-9", "exp": int(time.time()) + 60}, SECRET),  # lone surrogate: not encodable as UTF-8
    ],
)
def test_identity_subject_rejects(claims, secret):
    token = jwt.encode(claims, secret, algorithm="HS256")
    with pytest.raises(InvalidIdentityError):
        identity_subject(token, SECRET, now=int(time.time()), max_lifetime_seconds=3600)


def test_identity_subject_rejects_a_pair_sent_as_raw_cesu8_bytes():
    # PyJWT hands the payload's bytes to json.loads, which keeps raw surrogate bytes ("surrogatepass").
    def segment(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    payload = b'{"sub": "user\xed\xa0\xbd\xed\xb8\x80", "exp": %d}' % (int(time.time()) + 60)
    signing_input = segment(b'{"alg": "HS256", "typ": "JWT"}') + b"." + segment(payload)
    signature = hmac.new(SECRET.encode(), signing_input, hashlib.sha256).digest()
    token = (signing_input + b"." + segment(signature)).decode()
    with pytest.raises(InvalidIdentityError, match="surrogate"):
        identity_subject(token, SECRET, now=int(time.time()), max_lifetime_seconds=3600)


def test_identity_subject_rejects_none_algorithm_and_garbage():
    unsigned = jwt.encode({"sub": "u", "exp": int(time.time()) + 60}, key=None, algorithm="none")
    for token in (unsigned, "not.a.jwt", None, ""):
        with pytest.raises(InvalidIdentityError):
            identity_subject(token, SECRET, now=int(time.time()), max_lifetime_seconds=3600)
