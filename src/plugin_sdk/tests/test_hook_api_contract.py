import hashlib
import json
import time
import typing

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from epicstaff_plugin.contracts.gateway_context import Jwk, Jwks
from epicstaff_plugin.contracts.hook_api import (
    HOOK_ASSERTION_GRACE_SECONDS,
    HOOK_ASSERTION_TYPE,
    HOOK_KINDS,
    HOOK_PATHS,
    MAX_HOOK_BODY_BYTES,
    HookAssertionClaims,
    HookKind,
    HookRequest,
    HookResponse,
    encode_hook_assertion,
    encode_hook_body,
    hook_body_sha256,
)
from epicstaff_plugin.contracts.manifest import MAX_HOOK_TIMEOUT_SECONDS, Hooks, HookTimeouts
from epicstaff_plugin.hooks import HookAssertionRejected, verify_hook_assertion
from epicstaff_plugin.testing import ContextSigner, HookSigner

ISSUER = "https://epicstaff.example.com"
KID = "0123456789abcdef"
BODY = {
    "format": 1,
    "job_id": 41,
    "attempt": 1,
    "kind": "install",
    "org": {"id": 3, "name": "Acme"},
    "plugin": {"identifier": "weather", "version": "0.4.0"},
    "previous_version": None,
}


@pytest.fixture
def private_key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def jwks(private_key):
    return Jwks(keys=[Jwk.from_public_key(KID, private_key.public_key())])


def _claims(body: bytes, **changes):
    now = int(time.time())
    return HookAssertionClaims.model_validate(
        {
            "iss": ISSUER,
            "aud": "weather",
            "iat": now,
            "exp": now + 900 + HOOK_ASSERTION_GRACE_SECONDS,
            "jti": "a" * 32,
            "kind": "install",
            "job_id": 41,
            "attempt": 1,
            "org_id": 3,
            "body_sha256": hook_body_sha256(body),
            **changes,
        }
    )


def _verify(assertion, body, jwks, kind="install"):
    return verify_hook_assertion(
        assertion, body, kind=kind, jwks=jwks, issuer=ISSUER, plugin_identifier="weather"
    )


# --- Kinds and paths ---


def test_every_hook_kind_has_a_path_and_nothing_else_does():
    assert set(HOOK_PATHS) == set(HOOK_KINDS) == set(typing.get_args(HookKind))
    assert HOOK_PATHS == {
        "install": "/_epicstaff/hooks/install",
        "upgrade": "/_epicstaff/hooks/upgrade",
        "org_removed": "/_epicstaff/hooks/org-removed",
    }


def test_every_hook_kind_has_a_manifest_switch_a_timeout_and_a_platform_maximum():
    assert set(Hooks.model_fields) - {"timeouts_seconds"} == set(HOOK_KINDS)
    assert set(HookTimeouts.model_fields) == set(HOOK_KINDS)
    assert set(MAX_HOOK_TIMEOUT_SECONDS) == set(HOOK_KINDS)


def test_the_hook_paths_cannot_be_changed():
    with pytest.raises(TypeError):
        HOOK_PATHS["install"] = "/elsewhere"


# --- The body ---


def test_the_body_is_the_compact_json_epicstaff_digests():
    request = HookRequest.model_validate(BODY)

    body = encode_hook_body(request)

    assert json.loads(body) == BODY
    assert hook_body_sha256(body) == hashlib.sha256(body).hexdigest()
    assert HookRequest.model_validate_json(body) == request


def test_a_body_a_newer_epicstaff_extends_is_read_leniently():
    assert HookRequest.model_validate({**BODY, "reason": "granted"}, extra="ignore").job_id == 41


@pytest.mark.parametrize(
    "changes",
    [
        {"format": 2},
        {"job_id": 0},
        {"attempt": 0},
        {"kind": "uninstall"},
        {"org": {"id": 0, "name": "Acme"}},
        {"plugin": {"identifier": "Weather", "version": "0.4.0"}},
        {"previous_version": "not-semver"},
        {"unknown": True},
    ],
)
def test_epicstaff_cannot_build_a_malformed_body(changes):
    with pytest.raises(ValidationError):
        HookRequest.model_validate({**BODY, **changes})


def test_previous_version_must_be_stated_even_when_null():
    body = dict(BODY)
    del body["previous_version"]

    with pytest.raises(ValidationError):
        HookRequest.model_validate(body)


def test_the_largest_body_fits_the_cap():
    request = HookRequest.model_validate({**BODY, "org": {"id": 2**63 - 1, "name": "é" * 255}})

    assert len(encode_hook_body(request)) < MAX_HOOK_BODY_BYTES


# --- The answer ---


def test_done_and_failed_answers():
    assert HookResponse.model_validate({"status": "done"}).succeeded
    failed = HookResponse.model_validate({"status": "failed", "error": {"message": "no flow"}})
    assert not failed.succeeded
    assert failed.error.message == "no flow"


@pytest.mark.parametrize(
    "document",
    [
        {"status": "done", "error": {"message": "x"}},
        {"status": "failed"},
        {"status": "failed", "error": {"message": "x" * 2001}},
        {"status": "ok"},
    ],
)
def test_a_malformed_answer_is_refused(document):
    with pytest.raises(ValidationError):
        HookResponse.model_validate(document)


# --- The claims ---


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "Weather"},
        {"kind": "uninstall"},
        {"job_id": 0},
        {"attempt": 0},
        {"org_id": 0},
        {"jti": "short"},
        {"body_sha256": "A" * 64},
        {"body_sha256": "a" * 63},
        {"exp": 0},
        {"iss": ""},
    ],
)
def test_epicstaff_cannot_build_malformed_claims(changes):
    with pytest.raises(ValidationError):
        _claims(b"{}", **changes)


def test_claims_expire_after_they_are_issued():
    with pytest.raises(ValidationError, match="exp must be later than iat"):
        _claims(b"{}", iat=100, exp=100)


# --- Round trip: EpicStaff signs, the SDK verifies ---


def test_an_assertion_epicstaff_signs_verifies_with_its_body(private_key, jwks):
    body = encode_hook_body(HookRequest.model_validate(BODY))
    claims = _claims(body)

    verified = _verify(encode_hook_assertion(claims, private_key, KID), body, jwks)

    assert verified.claims == claims
    assert verified.request == HookRequest.model_validate(BODY)


def test_the_assertion_header_names_the_hook_type_and_the_key(private_key):
    body = encode_hook_body(HookRequest.model_validate(BODY))

    header = jwt.get_unverified_header(encode_hook_assertion(_claims(body), private_key, KID))

    assert header == {"alg": "EdDSA", "typ": HOOK_ASSERTION_TYPE, "kid": KID}


def test_a_gateway_context_is_never_taken_for_a_hook_assertion(jwks):
    signer = ContextSigner(plugin_identifier="weather", issuer=ISSUER)

    with pytest.raises(HookAssertionRejected) as rejected:
        _verify(signer.issue("POST", "/_epicstaff/hooks/install"), b"{}", signer.jwks)

    assert rejected.value.reason == "wrong_type"


def test_the_dev_signer_signs_what_epicstaff_signs():
    signer = ContextSigner(plugin_identifier="weather", plugin_version="0.4.0", issuer=ISSUER)

    call = HookSigner(signer).call("install", org={"id": 3, "name": "Acme"}, job_id=41)

    assert call.path == "/_epicstaff/hooks/install"
    assert json.loads(call.body) == {**BODY}
    assert call.claims.exp - call.claims.iat == MAX_HOOK_TIMEOUT_SECONDS["install"] + HOOK_ASSERTION_GRACE_SECONDS
    verified = verify_hook_assertion(
        call.headers["X-EpicStaff-Hook"],
        call.body,
        kind="install",
        jwks=signer.jwks,
        issuer=ISSUER,
        plugin_identifier="weather",
    )
    assert verified.request == call.request


def test_an_unknown_key_is_rejected(private_key, jwks):
    body = encode_hook_body(HookRequest.model_validate(BODY))
    other = Ed25519PrivateKey.generate()

    with pytest.raises(HookAssertionRejected) as rejected:
        _verify(encode_hook_assertion(_claims(body), other, "fedcba9876543210"), body, jwks)

    assert rejected.value.reason == "unknown_key"
