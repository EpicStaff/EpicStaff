import json
import zipfile

import pytest
from epicstaff_plugin.signing import generate_secret_key

from es_plugins.packages.package_unpacker import unpack_backend
from es_plugins.packages.package_verifier import PackageVerificationError, verify_package
from tests.helpers import backend_wheels, manifest, package_files, placement, write_package


@pytest.fixture
def files(tmp_path):
    return package_files(backend_wheels(tmp_path / "wheels"))


def test_an_untrusted_package_is_checked_by_its_digests_and_accepted(tmp_path, files):
    package = write_package(tmp_path / "weather.esplugin", files)

    archive = verify_package(package, placement(package.read_bytes()))

    assert archive.manifest.id == "weather"
    assert archive.signature is None


def test_a_trusted_package_signed_by_the_named_key_is_accepted(tmp_path, files):
    key = generate_secret_key()
    package = write_package(tmp_path / "weather.esplugin", files, secret_key=key)
    desired = placement(
        package.read_bytes(), trust="trusted", signer_public_key=key.public_key.to_text()
    )

    archive = verify_package(package, desired)

    assert archive.signature is not None


def test_a_file_whose_digest_differs_from_contents_json_is_refused(tmp_path, files):
    package = write_package(tmp_path / "weather.esplugin", files)
    listed = json.loads(zipfile.ZipFile(package).read("CONTENTS.json"))
    for entry in listed["files"]:
        if entry["path"] == "backend/src/weather_plugin/app.py":
            entry["sha256"] = "0" * 64
    tampered = json.dumps(listed, sort_keys=True, separators=(",", ":")).encode()
    package = write_package(tmp_path / "tampered.esplugin", files, contents=tampered)

    with pytest.raises(PackageVerificationError, match="sha256"):
        verify_package(package, placement(package.read_bytes()))


def test_a_trusted_package_signed_by_another_key_is_refused(tmp_path, files):
    signer = generate_secret_key()
    expected = generate_secret_key()
    package = write_package(tmp_path / "weather.esplugin", files, secret_key=signer)
    desired = placement(
        package.read_bytes(), trust="trusted", signer_public_key=expected.public_key.to_text()
    )

    with pytest.raises(PackageVerificationError) as refused:
        verify_package(package, desired)

    assert signer.public_key.display_id in str(refused.value)
    assert expected.public_key.display_id in str(refused.value)


def test_a_trusted_package_without_a_signature_is_refused(tmp_path, files):
    key = generate_secret_key()
    package = write_package(tmp_path / "weather.esplugin", files)
    desired = placement(
        package.read_bytes(), trust="trusted", signer_public_key=key.public_key.to_text()
    )

    with pytest.raises(PackageVerificationError, match="has no signature"):
        verify_package(package, desired)


def test_a_signature_over_other_contents_is_refused(tmp_path, files):
    key = generate_secret_key()
    signed = write_package(tmp_path / "signed.esplugin", files, secret_key=key)
    signature = zipfile.ZipFile(signed).read("CONTENTS.json.minisig")
    changed = dict(files, **{"backend/src/weather_plugin/app.py": b"app = None\n"})
    package = write_package(tmp_path / "changed.esplugin", changed)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("CONTENTS.json.minisig", signature)
    desired = placement(
        package.read_bytes(), trust="trusted", signer_public_key=key.public_key.to_text()
    )

    with pytest.raises(PackageVerificationError, match="signature is invalid"):
        verify_package(package, desired)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"version": "0.3.0"}, "version"),
        ({"python": "3.12"}, "backend.python"),
        ({"entrypoint": "weather_plugin.other:app"}, "backend.entrypoint"),
    ],
)
def test_a_manifest_that_is_not_the_desired_one_is_refused(tmp_path, overrides, field):
    wheels = backend_wheels(tmp_path / "wheels")
    plugin_manifest = manifest(**overrides)
    files = package_files(wheels, plugin_manifest)
    if "entrypoint" in overrides:
        files["backend/src/weather_plugin/other.py"] = b"app = None\n"
    package = write_package(
        tmp_path / "weather.esplugin", files, version=plugin_manifest["version"]
    )

    with pytest.raises(PackageVerificationError, match=f"has {field}"):
        verify_package(package, placement(package.read_bytes()))


def test_unpacking_writes_only_the_backend_files(tmp_path, files):
    package = write_package(tmp_path / "weather.esplugin", files)
    archive = verify_package(package, placement(package.read_bytes()))
    destination = tmp_path / "unpacked"
    (destination / "stale").mkdir(parents=True)

    unpack_backend(package, archive, destination)

    written = sorted(
        str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()
    )
    assert written == sorted(path for path in files if path.startswith("backend/"))
    assert not (destination / "stale").exists()
