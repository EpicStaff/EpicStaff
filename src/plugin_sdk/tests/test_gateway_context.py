import asyncio
import base64
import json
import time

import jwt
import pytest
from pydantic import ValidationError

from epicstaff_plugin.contracts.gateway_context import CONTEXT_TYPE, GatewayContext, Jwk, Jwks
from epicstaff_plugin.gateway import ContextRejected, ContextVerifier
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.testing import ContextSigner, write_runtime_file

USER = {"id": 7, "email": "ada@example.com", "name": "Ada"}
ORG = {"id": 3, "name": "Acme"}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeJwksEndpoint:
    """EpicStaff's /api/plugin-public/jwks/, with every download recorded."""

    def __init__(self, *signers):
        self.signers = list(signers)
        self.urls = []
        self.error = None

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        keys = [key for signer in self.signers for key in signer.jwks.keys]
        return Jwks(keys=keys).model_dump_json().encode()


def _rejection(verifier, token, method="GET", path="/api/ping"):
    with pytest.raises(ContextRejected) as raised:
        verifier.verify(token, method, path)
    return raised.value.reason


def _claims(signer, **changes):
    claims = signer.context("GET", "/api/ping").model_dump(mode="json")
    claims.update(changes)
    return claims


def _rotated_signer(signer):
    return ContextSigner(
        plugin_identifier=signer.plugin_identifier,
        plugin_version=signer.plugin_version,
        issuer=signer.issuer,
    )


# --- The checks of a context ---


def test_a_public_context_for_this_request_verifies(runtime, signer):
    context = ContextVerifier(runtime).verify(signer.issue("GET", "/api/ping"), "GET", "/api/ping")

    assert (context.mode, context.user, context.org, context.permissions) == ("public", None, None, [])
    assert (context.aud, context.plugin.identifier, context.request.path) == ("weather", "weather", "/api/ping")


def test_a_user_context_carries_the_user_org_and_permissions(runtime, signer):
    token = signer.issue("POST", "/api/places", mode="user", user=USER, org=ORG, permissions=["read", "update"])

    context = ContextVerifier(runtime).verify(token, "POST", "/api/places")

    assert (context.user.email, context.org.name, context.permissions) == ("ada@example.com", "Acme", ["read", "update"])


def test_a_context_for_another_plugin_is_refused(runtime, signer):
    token = signer.sign_claims(_claims(signer, aud="other", plugin={"identifier": "other", "version": "1.0.0"}))

    assert _rejection(ContextVerifier(runtime), token) == "wrong_audience"


def test_a_context_from_another_issuer_is_refused(runtime, signer):
    token = signer.sign_claims(_claims(signer, iss="https://evil.example.com"))

    assert _rejection(ContextVerifier(runtime), token) == "wrong_issuer"


def test_an_expired_context_is_refused(runtime, signer):
    token = signer.issue("GET", "/api/ping", issued_at=int(time.time()) - 200)

    assert _rejection(ContextVerifier(runtime), token) == "expired"


def test_a_context_expired_within_the_leeway_still_verifies(runtime, signer):
    # Expired 20 s ago: inside the 30 s allowed for clocks that disagree.
    token = signer.issue("GET", "/api/ping", issued_at=int(time.time()) - 80)

    assert ContextVerifier(runtime).verify(token, "GET", "/api/ping").mode == "public"


def test_a_context_issued_in_the_future_is_refused(runtime, signer):
    token = signer.issue("GET", "/api/ping", issued_at=int(time.time()) + 300)

    assert _rejection(ContextVerifier(runtime), token) == "not_yet_valid"


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/ping"), ("GET", "/api/ping/"), ("GET", "/api/pong"), ("GET", "/API/ping")],
)
def test_a_context_for_another_request_is_refused(runtime, signer, method, path):
    token = signer.issue("GET", "/api/ping")

    assert _rejection(ContextVerifier(runtime), token, method, path) == "request_mismatch"


@pytest.mark.parametrize("path", ["/api/public/../private", "/api/./ping", "/api/ping/.."])
def test_a_path_with_dot_segments_is_refused_even_when_signed_for(runtime, signer, path):
    claims = _claims(signer, request={"method": "GET", "path": path})

    assert _rejection(ContextVerifier(runtime), signer.sign_claims(claims), "GET", path) == "dot_segment"


def test_a_tampered_payload_is_refused(runtime, signer):
    header, payload, signature = signer.issue("GET", "/api/ping").split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["permissions"] = ["read"]
    claims["mode"] = "user"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    assert _rejection(ContextVerifier(runtime), f"{header}.{forged}.{signature}") == "bad_signature"


def test_a_tampered_signature_is_refused(runtime, signer):
    header, payload, signature = signer.issue("GET", "/api/ping").split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

    assert _rejection(ContextVerifier(runtime), f"{header}.{payload}.{flipped}") == "bad_signature"


def test_a_context_signed_by_another_key_under_a_known_key_id_is_refused(runtime, signer):
    impostor = _rotated_signer(signer)
    impostor.kid = signer.kid

    assert _rejection(ContextVerifier(runtime), impostor.issue("GET", "/api/ping")) == "bad_signature"


@pytest.mark.parametrize("typ", ["JWT", None])
def test_a_context_of_another_type_is_refused(runtime, signer, typ):
    token = signer.sign_claims(_claims(signer), headers={"typ": typ})

    assert _rejection(ContextVerifier(runtime), token) == "wrong_type"


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "EdDSA", "typ": CONTEXT_TYPE},
        {"alg": "EdDSA", "typ": CONTEXT_TYPE, "kid": 5},
        {"alg": "none", "typ": CONTEXT_TYPE, "kid": "0123456789abcdef"},
    ],
)
def test_a_context_without_a_usable_key_id_or_algorithm_is_refused(runtime, signer, header):
    def encoded(document):
        return base64.urlsafe_b64encode(json.dumps(document).encode()).rstrip(b"=").decode()

    token = f"{encoded(header)}.{encoded(_claims(signer))}.c2lnbmF0dXJl"

    assert _rejection(ContextVerifier(runtime), token) == "malformed"


def test_a_context_with_another_algorithm_is_refused(runtime, signer):
    token = jwt.encode(
        _claims(signer), "a-shared-secret-of-at-least-32-bytes", algorithm="HS256", headers={"typ": CONTEXT_TYPE, "kid": signer.kid}
    )

    assert _rejection(ContextVerifier(runtime), token) == "malformed"


@pytest.mark.parametrize("token", ["", "not-a-token", "a.b.c", "x" * 9000])
def test_garbage_is_refused(runtime, token):
    assert _rejection(ContextVerifier(runtime), token) == "malformed"


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "public", "user": USER},
        {"mode": "public", "permissions": ["read"]},
        {"mode": "admin"},
        {"permissions": ["fly"]},
        {"jti": "short"},
        {"request": {"method": "GET"}},
    ],
)
def test_a_context_whose_claims_break_the_contract_is_refused(runtime, signer, changes):
    assert _rejection(ContextVerifier(runtime), signer.sign_claims(_claims(signer, **changes))) == "invalid_claims"


def test_a_context_without_a_required_claim_is_refused(runtime, signer):
    claims = _claims(signer)
    del claims["jti"]

    assert _rejection(ContextVerifier(runtime), signer.sign_claims(claims)) == "invalid_claims"


def test_a_claim_a_newer_epicstaff_adds_is_ignored(runtime, signer):
    token = signer.sign_claims(_claims(signer, session={"id": 1}))

    assert ContextVerifier(runtime).verify(token, "GET", "/api/ping").mode == "public"


# --- Keys: rotation, refetching, expiry of downloaded keys ---


def test_an_unknown_key_id_downloads_the_jwks_once_and_then_verifies(runtime, signer):
    rotated = _rotated_signer(signer)
    endpoint = FakeJwksEndpoint(signer, rotated)
    verifier = ContextVerifier(runtime, fetch_jwks=endpoint, clock=FakeClock())

    assert verifier.verify(rotated.issue("GET", "/api/ping"), "GET", "/api/ping").mode == "public"
    assert verifier.verify(rotated.issue("GET", "/api/ping"), "GET", "/api/ping").mode == "public"
    assert endpoint.urls == ["http://epicstaff-api:8081/api/plugin-public/jwks/"]


def test_unknown_key_ids_download_the_jwks_at_most_once_per_30_seconds(runtime, signer):
    clock = FakeClock()
    endpoint = FakeJwksEndpoint(signer)
    verifier = ContextVerifier(runtime, fetch_jwks=endpoint, clock=clock)
    forged = _rotated_signer(signer)

    for _ in range(5):
        assert _rejection(verifier, forged.issue("GET", "/api/ping")) == "unknown_key"
    clock.now += 29
    assert _rejection(verifier, forged.issue("GET", "/api/ping")) == "unknown_key"
    assert len(endpoint.urls) == 1

    clock.now += 2
    assert _rejection(verifier, forged.issue("GET", "/api/ping")) == "unknown_key"
    assert len(endpoint.urls) == 2


def test_a_key_the_node_wrote_into_the_runtime_file_is_used_without_a_download(runtime_file, signer):
    endpoint = FakeJwksEndpoint()
    verifier = ContextVerifier(RuntimeConfig.load(runtime_file), fetch_jwks=endpoint, clock=FakeClock())
    rotated = _rotated_signer(signer)
    write_runtime_file(runtime_file, signer=rotated)

    assert verifier.verify(rotated.issue("GET", "/api/ping"), "GET", "/api/ping").mode == "public"
    assert endpoint.urls == []


def test_a_downloaded_key_is_dropped_once_the_runtime_file_changes(runtime_file, signer):
    clock = FakeClock()
    rotated = _rotated_signer(signer)
    verifier = ContextVerifier(RuntimeConfig.load(runtime_file), fetch_jwks=FakeJwksEndpoint(rotated), clock=clock)
    assert verifier.verify(rotated.issue("GET", "/api/ping"), "GET", "/api/ping")

    # The node rewrites the file without that key (it was retired more than 24 h ago).
    write_runtime_file(runtime_file, signer=signer)

    assert _rejection(verifier, rotated.issue("GET", "/api/ping")) == "unknown_key"


def test_a_downloaded_key_is_dropped_after_10_minutes(runtime, signer):
    clock = FakeClock()
    rotated = _rotated_signer(signer)
    endpoint = FakeJwksEndpoint(rotated)
    verifier = ContextVerifier(runtime, fetch_jwks=endpoint, clock=clock)
    assert verifier.verify(rotated.issue("GET", "/api/ping"), "GET", "/api/ping")

    clock.now += 601
    # The next download, allowed again by now, no longer has the key either.
    endpoint.signers = [signer]

    assert _rejection(verifier, rotated.issue("GET", "/api/ping")) == "unknown_key"


@pytest.mark.parametrize("error", [OSError("connection refused"), ValueError("not json")])
def test_a_failed_download_leaves_the_key_unknown(runtime, signer, error, caplog):
    endpoint = FakeJwksEndpoint()
    endpoint.error = error
    verifier = ContextVerifier(runtime, fetch_jwks=endpoint, clock=FakeClock())

    assert _rejection(verifier, _rotated_signer(signer).issue("GET", "/api/ping")) == "unknown_key"
    assert "Could not download EpicStaff's signing keys" in caplog.text


def test_a_downloaded_document_that_is_not_a_jwks_leaves_the_key_unknown(runtime, signer):
    verifier = ContextVerifier(runtime, fetch_jwks=lambda url: b'{"keys": []}', clock=FakeClock())

    assert _rejection(verifier, _rotated_signer(signer).issue("GET", "/api/ping")) == "unknown_key"


def test_verify_async_downloads_an_unknown_key_too(runtime, signer):
    rotated = _rotated_signer(signer)
    endpoint = FakeJwksEndpoint(rotated)
    verifier = ContextVerifier(runtime, fetch_jwks=endpoint, clock=FakeClock())

    context = asyncio.run(verifier.verify_async(rotated.issue("GET", "/api/ping"), "GET", "/api/ping"))

    assert context.mode == "public"
    assert len(endpoint.urls) == 1


# --- The contract models themselves ---


def test_a_jwk_round_trips_its_public_key(signer):
    key = signer.jwks.keys[0]

    assert Jwk.from_public_key(key.kid, key.public_key()) == key


def test_a_jwks_may_not_repeat_a_key_id(signer):
    key = signer.jwks.keys[0].model_dump()

    with pytest.raises(ValidationError, match="more than once"):
        Jwks.model_validate({"keys": [key, key]})


def test_the_context_header_names_the_type_and_key(signer):
    header = jwt.get_unverified_header(signer.issue("GET", "/api/ping"))

    assert header == {"alg": "EdDSA", "typ": "epicstaff-plugin-context+jwt", "kid": signer.kid}


def test_issued_contexts_live_60_seconds(signer):
    context = signer.context("GET", "/api/ping", issued_at=1_000_000)

    assert (context.iat, context.exp) == (1_000_000, 1_000_060)


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "other"},
        {"exp": 1},
        {"permissions": ["read", "read"]},
        {"mode": "public", "org": ORG},
        {"request": {"method": "get", "path": "/api/ping"}},
        {"request": {"method": "GET", "path": "api/ping"}},
        {"extra_claim": True},
    ],
)
def test_epicstaff_cannot_build_a_context_that_breaks_the_contract(signer, changes):
    claims = _claims(signer, **changes)

    with pytest.raises(ValidationError):
        GatewayContext.model_validate(claims)
