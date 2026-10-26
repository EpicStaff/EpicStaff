"""Plugin login tokens: their key, their claims, and every check their verification makes."""

import hashlib
import hmac
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from plugins.identity.plugin_login_tokens import (
    PluginLoginTokenRejected,
    issue_plugin_login_token,
    looks_like_plugin_login_token,
    password_fingerprint,
    signing_key,
    verify_plugin_login_token,
)
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.utils import get_md5_hash_password

from tests.plugins_tests.login_helpers import EPICSTAFF_ORIGIN, WEATHER_ORIGIN

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled")]

HEADER = {"typ": "epicstaff-plugin-login+jwt"}


@pytest.fixture
def person(django_user_model):
    return django_user_model.objects.create_user(email="token-person@example.com", password="StrongPass123!")


def _claims(person, **changes):
    now = int(time.time())
    claims = {
        "token_type": "plugin_login",
        "iss": EPICSTAFF_ORIGIN,
        "aud": WEATHER_ORIGIN,
        "sub": str(person.pk),
        "org": 3,
        "plugin": "weather",
        "grant": 7,
        "pwd": password_fingerprint(person.password),
        "iat": now,
        "exp": now + 900,
        "jti": "9c" * 16,
        **changes,
    }
    return {name: value for name, value in claims.items() if value is not None}


def _signed(claims, key=None, algorithm="HS256", headers=HEADER):
    return jwt.encode(claims, key or signing_key(), algorithm=algorithm, headers=headers)


def _rejection(token, identifier="weather"):
    with pytest.raises(PluginLoginTokenRejected) as rejected:
        verify_plugin_login_token(token, identifier)
    return rejected.value.reason


def test_the_key_is_derived_from_the_secret_key_and_differs_from_it(settings):
    key = signing_key()

    assert len(key) == 32
    assert key != settings.SECRET_KEY.encode("utf-8")[:32]
    settings.SECRET_KEY = "another-secret-key-of-the-deployment"
    assert signing_key() != key


def test_an_issued_token_verifies_to_its_claims(person):
    issued = issue_plugin_login_token(user=person, org_id=3, grant_id=7, identifier="weather")

    claims = verify_plugin_login_token(issued.token, "weather")

    assert (claims.user_id, claims.org_id, claims.grant_id, claims.plugin) == (person.pk, 3, 7, "weather")
    assert claims.password_fingerprint == password_fingerprint(person.password)
    assert claims.jti == issued.jti
    assert issued.expires_in == 900
    assert jwt.get_unverified_header(issued.token) == {"alg": "HS256", "typ": "epicstaff-plugin-login+jwt"}
    assert looks_like_plugin_login_token(issued.token)


def test_pwd_is_an_hmac_of_the_password_hash_not_simplejwt_s_fingerprint(person):
    token = issue_plugin_login_token(user=person, org_id=3, grant_id=7, identifier="weather").token

    pwd = jwt.decode(token, options={"verify_signature": False})["pwd"]

    expected = hmac.new(signing_key(), person.password.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    assert pwd == expected
    assert pwd != get_md5_hash_password(person.password)
    assert pwd not in person.password


@pytest.mark.parametrize(
    ("headers", "reason"),
    [({"typ": "JWT"}, "wrong_type"), ({}, "wrong_type"), ({"typ": "epicstaff-plugin-context+jwt"}, "wrong_type")],
)
def test_the_type_header_must_match_exactly(person, headers, reason):
    assert _rejection(_signed(_claims(person), headers=headers)) == reason


def test_alg_none_is_refused(person):
    token = jwt.encode(_claims(person), None, algorithm="none", headers=HEADER)

    assert _rejection(token) == "wrong_algorithm"


def test_hs512_with_the_right_key_is_refused(person):
    assert _rejection(_signed(_claims(person), algorithm="HS512")) == "wrong_algorithm"


def test_rs256_is_refused(person):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert _rejection(_signed(_claims(person), key=private_key, algorithm="RS256")) == "wrong_algorithm"


def test_a_token_signed_with_the_secret_key_itself_is_refused(person, settings):
    assert _rejection(_signed(_claims(person), key=settings.SECRET_KEY)) == "bad_signature"


def test_rotating_the_secret_key_ends_every_token(person, settings):
    token = issue_plugin_login_token(user=person, org_id=3, grant_id=7, identifier="weather").token
    settings.SECRET_KEY = "a-rotated-secret-key-for-the-deployment"

    assert _rejection(token) == "bad_signature"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"iss": "http://evil.localhost"}, "wrong_issuer"),
        ({"aud": "http://other.plugins.epicstaff.localhost"}, "wrong_audience"),
        ({"exp": int(time.time()) - 1}, "expired"),
        ({"token_type": "access"}, "wrong_token_type"),
        ({"token_type": None}, "wrong_token_type"),
        ({"plugin": "other"}, "wrong_plugin"),
        ({"jti": None}, "invalid_claims"),
        ({"sub": None}, "invalid_claims"),
        ({"iat": None}, "invalid_claims"),
        ({"sub": "abc"}, "invalid_claims"),
        ({"org": "3"}, "invalid_claims"),
        ({"org": True}, "invalid_claims"),
        ({"grant": 0}, "invalid_claims"),
        ({"pwd": "short"}, "invalid_claims"),
    ],
)
def test_every_claim_is_checked(person, changes, reason):
    assert _rejection(_signed(_claims(person, **changes))) == reason


def test_a_token_is_only_for_the_plugin_whose_frame_origin_it_names(person):
    token = issue_plugin_login_token(user=person, org_id=3, grant_id=7, identifier="weather").token

    assert _rejection(token, identifier="other") == "wrong_audience"


@pytest.mark.parametrize("token", ["not-a-token", "", "a.b.c"])
def test_a_malformed_token_is_refused(token):
    assert _rejection(token) == "malformed"
    assert not looks_like_plugin_login_token(token)


def test_simplejwt_rejects_a_plugin_login_token(person):
    token = issue_plugin_login_token(user=person, org_id=3, grant_id=7, identifier="weather").token

    with pytest.raises(TokenError):
        AccessToken(token)
