"""Trusted or Untrusted: the four outcomes of a package signature."""

import base64

import pytest
from epicstaff_plugin.signing import generate_secret_key, sign_package
from plugins.exceptions import InvalidPluginError, InvalidSignatureError
from plugins.models import SignatureStatus, Trust

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import (
    APP_JS,
    build_package,
    contents_for,
    sample_files,
    sample_manifest,
)

pytestmark = pytest.mark.django_db


def _upload(installation, user, data):
    return installation.upload(upload_file(data), len(data), user)


def test_an_unsigned_package_is_untrusted(installation, superadmin, trusts_release_key):
    package = _upload(installation, superadmin, build_package())

    assert (package.trust, package.signature_status) == (Trust.UNTRUSTED, SignatureStatus.ABSENT)
    assert (package.signer_key_id, package.signer_key_name) == (None, None)


def test_a_package_signed_by_a_listed_key_is_trusted(installation, superadmin, trusts_release_key):
    package = _upload(installation, superadmin, build_package(signed_with=trusts_release_key))

    assert (package.trust, package.signature_status) == (Trust.TRUSTED, SignatureStatus.VALID)
    assert package.signer_key_id == trusts_release_key.public_key.display_id
    assert package.signer_key_name == "release"


def test_a_package_signed_by_an_unlisted_key_is_untrusted_with_its_key_id(installation, superadmin, trusts_release_key):
    stranger = generate_secret_key()

    package = _upload(installation, superadmin, build_package(signed_with=stranger))

    assert (package.trust, package.signature_status) == (Trust.UNTRUSTED, SignatureStatus.UNKNOWN_KEY)
    assert package.signer_key_id == stranger.public_key.display_id
    assert package.signer_key_name is None


def test_a_listed_key_whose_signature_does_not_verify_is_rejected(installation, superadmin, trusts_release_key):
    files = sample_files()
    contents = contents_for(files)
    lines = sign_package(contents, "weather", "0.1.0", trusts_release_key).splitlines()
    raw = bytearray(base64.b64decode(lines[1]))
    raw[-1] ^= 0x01
    lines[1] = base64.b64encode(bytes(raw)).decode()

    with pytest.raises(InvalidSignatureError):
        _upload(installation, superadmin, build_package(files, signature="\n".join(lines) + "\n"))


def test_one_byte_changed_in_a_signed_file_is_rejected(installation, superadmin, trusts_release_key):
    files = sample_files()
    contents = contents_for(files)
    signature = sign_package(contents, "weather", "0.1.0", trusts_release_key)
    files["spa/assets/app.js"] = APP_JS.replace(b"W", b"V", 1)

    with pytest.raises(InvalidPluginError) as raised:
        _upload(installation, superadmin, build_package(files, contents=contents, signature=signature))

    assert raised.value.errors[0]["loc"].endswith(".sha256")


def test_one_byte_changed_in_signed_contents_is_rejected(installation, superadmin, trusts_release_key):
    files = sample_files()
    signature = sign_package(contents_for(files), "weather", "0.1.0", trusts_release_key)
    files["spa/assets/app.js"] = APP_JS.replace(b"W", b"V", 1)

    # CONTENTS.json now matches the changed file, so only the signature can catch it.
    with pytest.raises(InvalidSignatureError):
        _upload(installation, superadmin, build_package(files, signature=signature))


@pytest.mark.parametrize("known_key", [True, False], ids=["listed key", "unlisted key"])
@pytest.mark.parametrize(
    "changes", [{"id": "forecast"}, {"version": "0.2.0"}], ids=["other id", "other version"]
)
def test_a_signature_moved_onto_another_id_or_version_is_rejected(
    installation, superadmin, trusts_release_key, known_key, changes
):
    signer = trusts_release_key if known_key else generate_secret_key()
    other_manifest = sample_manifest(**changes)
    other_files = sample_files(other_manifest)
    signature = sign_package(contents_for(sample_files()), "weather", "0.1.0", signer)

    with pytest.raises(InvalidSignatureError):
        _upload(installation, superadmin, build_package(other_files, manifest=other_manifest, signature=signature))


def test_a_malformed_signature_file_is_an_invalid_package(installation, superadmin):
    with pytest.raises(InvalidPluginError) as raised:
        _upload(installation, superadmin, build_package(signature="untrusted comment: x\nnot base64\n"))

    assert [error["loc"] for error in raised.value.errors] == ["signature"]


def test_the_upload_api_answers_invalid_signature(plugins_enabled, package_store, spa_root, superadmin_client, trusts_release_key):
    files = sample_files()
    signature = sign_package(contents_for(files), "weather", "0.1.0", trusts_release_key)
    files["spa/index.html"] += b" "

    response = superadmin_client.post(
        "/api/admin/plugins/packages/", {"file": upload_file(build_package(files, signature=signature))}, format="multipart"
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_signature"
