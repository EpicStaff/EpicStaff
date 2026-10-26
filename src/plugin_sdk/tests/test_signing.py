"""Signature checks against vectors made by the reference minisign tool (fixtures/minisign/regenerate.sh)."""

import pytest

from conftest import MINISIGN_FIXTURES
from epicstaff_plugin.signing import (
    EncryptedSecretKeyError,
    InvalidPackageSignatureError,
    PublicKey,
    SecretKey,
    SignatureFile,
    SignatureFormatError,
    TrustedKey,
    evaluate_package_signature,
    generate_secret_key,
    package_trusted_comment,
    parse_trusted_keys,
    sign_package,
)

CONTENTS = (MINISIGN_FIXTURES / "CONTENTS.json").read_bytes()
MINISIGN_SIGNATURE = (MINISIGN_FIXTURES / "CONTENTS.json.minisig").read_text()
MINISIGN_PUBLIC_KEY_FILE = (MINISIGN_FIXTURES / "minisign.pub").read_text()
MINISIGN_SECRET_KEY_FILE = (MINISIGN_FIXTURES / "minisign.key").read_text()


@pytest.fixture
def minisign_public_key():
    return PublicKey.from_text(MINISIGN_PUBLIC_KEY_FILE)


@pytest.fixture
def trusted(minisign_public_key):
    return [TrustedKey(name="epicstaff-release", public_key=minisign_public_key)]


def test_the_public_key_id_is_shown_as_minisign_shows_it(minisign_public_key):
    comment = MINISIGN_PUBLIC_KEY_FILE.splitlines()[0]

    assert comment.endswith(minisign_public_key.display_id)
    assert len(minisign_public_key.display_id) == 16
    assert minisign_public_key.to_text() == MINISIGN_PUBLIC_KEY_FILE.splitlines()[1]


def test_a_minisign_signature_verifies(minisign_public_key):
    signature = SignatureFile.from_text(MINISIGN_SIGNATURE)

    assert signature.verifies_with(minisign_public_key, CONTENTS)
    assert signature.trusted_comment == package_trusted_comment("weather", "0.1.0", CONTENTS)


def test_signing_with_a_minisign_key_gives_minisign_s_exact_signature():
    secret_key = SecretKey.from_file_text(MINISIGN_SECRET_KEY_FILE)

    assert sign_package(CONTENTS, "weather", "0.1.0", secret_key) == MINISIGN_SIGNATURE


def test_a_written_secret_key_has_minisign_s_layout():
    secret_key = SecretKey.from_file_text(MINISIGN_SECRET_KEY_FILE)

    assert secret_key.to_file_text().splitlines()[1] == MINISIGN_SECRET_KEY_FILE.splitlines()[1]


def test_a_password_protected_key_is_refused_with_a_pointer_to_minisign():
    with pytest.raises(EncryptedSecretKeyError, match="minisign"):
        SecretKey.from_file_text((MINISIGN_FIXTURES / "encrypted.key").read_text())


def test_a_legacy_signature_is_refused():
    with pytest.raises(SignatureFormatError, match="pre-hashed"):
        SignatureFile.from_text((MINISIGN_FIXTURES / "legacy.minisig").read_text())


@pytest.mark.parametrize(
    "text",
    [
        "",
        "untrusted comment: x\n",
        MINISIGN_SIGNATURE.replace("trusted comment: ", "comment: "),
        MINISIGN_SIGNATURE.replace("untrusted comment: ", ""),
        MINISIGN_SIGNATURE + "extra line\n",
    ],
)
def test_malformed_signature_files_are_refused(text):
    with pytest.raises(SignatureFormatError):
        SignatureFile.from_text(text)


def test_no_signature_is_untrusted_and_absent(trusted):
    verdict = evaluate_package_signature(CONTENTS, "weather", "0.1.0", None, trusted)

    assert (verdict.trust, verdict.signature, verdict.key_id, verdict.key_name) == (
        "untrusted",
        "absent",
        None,
        None,
    )


def test_a_signature_by_a_listed_key_is_trusted(trusted, minisign_public_key):
    verdict = evaluate_package_signature(CONTENTS, "weather", "0.1.0", MINISIGN_SIGNATURE, trusted)

    assert (verdict.trust, verdict.signature) == ("trusted", "valid")
    assert verdict.key_id == minisign_public_key.display_id
    assert verdict.key_name == "epicstaff-release"


def test_a_signature_by_an_unlisted_key_is_untrusted_with_its_key_id(minisign_public_key):
    verdict = evaluate_package_signature(CONTENTS, "weather", "0.1.0", MINISIGN_SIGNATURE, [])

    assert (verdict.trust, verdict.signature, verdict.key_name) == ("untrusted", "unknown_key", None)
    assert verdict.key_id == minisign_public_key.display_id


def test_one_changed_byte_is_rejected_for_a_listed_key(trusted):
    tampered = CONTENTS.replace(b'"size":0', b'"size":1', 1)
    signature = MINISIGN_SIGNATURE.replace(
        package_trusted_comment("weather", "0.1.0", CONTENTS),
        package_trusted_comment("weather", "0.1.0", tampered),
    )

    with pytest.raises(InvalidPackageSignatureError):
        evaluate_package_signature(tampered, "weather", "0.1.0", signature, trusted)


@pytest.mark.parametrize(("plugin_id", "version"), [("forecast", "0.1.0"), ("weather", "0.2.0")])
@pytest.mark.parametrize("known_key", [True, False])
def test_a_signature_moved_onto_another_id_or_version_is_rejected(trusted, plugin_id, version, known_key):
    with pytest.raises(InvalidPackageSignatureError, match="trusted comment"):
        evaluate_package_signature(
            CONTENTS, plugin_id, version, MINISIGN_SIGNATURE, trusted if known_key else []
        )


def test_a_rewritten_trusted_comment_fails_the_global_signature(trusted):
    other_contents = CONTENTS + b" "
    forged = MINISIGN_SIGNATURE.replace(
        package_trusted_comment("weather", "0.1.0", CONTENTS),
        package_trusted_comment("weather", "0.1.0", other_contents),
    )

    with pytest.raises(InvalidPackageSignatureError, match="does not verify"):
        evaluate_package_signature(other_contents, "weather", "0.1.0", forged, trusted)


def test_a_signature_by_another_key_with_the_same_comment_is_not_trusted(trusted):
    impostor = generate_secret_key()
    signature = sign_package(CONTENTS, "weather", "0.1.0", impostor)

    verdict = evaluate_package_signature(CONTENTS, "weather", "0.1.0", signature, trusted)

    assert verdict.signature == "unknown_key"


def test_a_generated_key_round_trips_through_its_files():
    secret_key = generate_secret_key()

    reread = SecretKey.from_file_text(secret_key.to_file_text())
    public_key = PublicKey.from_text(secret_key.public_key.to_file_text())

    assert reread == secret_key
    assert public_key == secret_key.public_key


def test_trusted_keys_are_parsed_from_the_environment_form(minisign_public_key):
    [key] = parse_trusted_keys([f" release:{minisign_public_key.to_text()} "])

    assert key.name == "release"
    assert key.public_key == minisign_public_key


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (["release"], "<name>:<minisign public key>"),
        (["release:not-a-key"], "base64"),
        ([":RWQ"], "name"),
        (["bad name:RWQ"], "name"),
    ],
)
def test_malformed_trusted_keys_are_refused(entries, message):
    with pytest.raises(SignatureFormatError, match=message):
        parse_trusted_keys(entries)


def test_a_trusted_key_name_or_key_listed_twice_is_refused(minisign_public_key):
    key = minisign_public_key.to_text()
    other = generate_secret_key().public_key.to_text()

    with pytest.raises(SignatureFormatError, match="used twice"):
        parse_trusted_keys([f"release:{key}", f"release:{other}"])
    with pytest.raises(SignatureFormatError, match="listed twice"):
        parse_trusted_keys([f"release:{key}", f"backup:{key}"])
