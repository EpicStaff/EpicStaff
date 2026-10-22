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
    ],
)
def test_identity_subject_rejects(claims, secret):
    token = jwt.encode(claims, secret, algorithm="HS256")
    with pytest.raises(InvalidIdentityError):
        identity_subject(token, SECRET, now=int(time.time()), max_lifetime_seconds=3600)


def test_identity_subject_rejects_none_algorithm_and_garbage():
    unsigned = jwt.encode({"sub": "u", "exp": int(time.time()) + 60}, key=None, algorithm="none")
    for token in (unsigned, "not.a.jwt", None, ""):
        with pytest.raises(InvalidIdentityError):
            identity_subject(token, SECRET, now=int(time.time()), max_lifetime_seconds=3600)
