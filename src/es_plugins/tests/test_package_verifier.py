import json
import zipfile

import pytest
from epicstaff_plugin.signing import generate_secret_key

from es_plugins.packages.package_unpacker import unpack_backend
from es_plugins.packages.package_verifier import PackageVerificationError, verify_package
from tests.helpers import backend_wheels, make_wheel, manifest, package_files, placement, write_package


def verify(path, desired):
    return verify_package(path, desired.plugin_identifier, desired.package, desired.runtime)


@pytest.fixture
def files(tmp_path):
    return package_files(backend_wheels(tmp_path / "wheels"))


def test_an_untrusted_package_is_checked_by_its_digests_and_accepted(tmp_path, files):
    package = write_package(tmp_path / "weather.esplugin", files)

    archive = verify(package, placement(package.read_bytes()))

    assert archive.manifest.id == "weather"
    assert archive.signature is None


def test_a_trusted_package_signed_by_the_named_key_is_accepted(tmp_path, files):
    key = generate_secret_key()
    package = write_package(tmp_path / "weather.esplugin", files, secret_key=key)
    desired = placement(
        package.read_bytes(), trust="trusted", signer_public_key=key.public_key.to_text()
    )

    archive = verify(package, desired)

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
        verify(package, placement(package.read_bytes()))


def test_a_package_whose_lock_pins_pip_is_refused(tmp_path):
    wheels = [*backend_wheels(tmp_path / "wheels"), make_wheel(tmp_path / "wheels", "pip", "26.0.1")]
    package = write_package(tmp_path / "weather.esplugin", package_files(wheels))

    with pytest.raises(PackageVerificationError, match="pip may not be pinned"):
        verify(package, placement(package.read_bytes()))


def test_a_trusted_package_signed_by_another_key_is_refused(tmp_path, files):
    signer = generate_secret_key()
    expected = generate_secret_key()
    package = write_package(tmp_path / "weather.esplugin", files, secret_key=signer)
    desired = placement(
        package.read_bytes(), trust="trusted", signer_public_key=expected.public_key.to_text()
    )

    with pytest.raises(PackageVerificationError) as refused:
        verify(package, desired)

    assert signer.public_key.display_id in str(refused.value)
    assert expected.public_key.display_id in str(refused.value)


def test_a_trusted_package_without_a_signature_is_refused(tmp_path, files):
    key = generate_secret_key()
    package = write_package(tmp_path / "weather.esplugin", files)
    desired = placement(
        package.read_bytes(), trust="trusted", signer_public_key=key.public_key.to_text()
    )

    with pytest.raises(PackageVerificationError, match="has no signature"):
        verify(package, desired)


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
        verify(package, desired)


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
        verify(package, placement(package.read_bytes()))


def test_unpacking_writes_only_the_backend_files(tmp_path, files):
    package = write_package(tmp_path / "weather.esplugin", files)
    archive = verify(package, placement(package.read_bytes()))
    destination = tmp_path / "unpacked"
    (destination / "stale").mkdir(parents=True)

    unpack_backend(package, archive, destination)

    written = sorted(
        str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()
    )
    assert written == sorted(path for path in files if path.startswith("backend/"))
    assert not (destination / "stale").exists()


def test_an_upgrade_target_is_checked_against_its_own_package_and_runtime(tmp_path):
    target_files = package_files(backend_wheels(tmp_path / "wheels"), manifest(version="0.3.0"))
    target = write_package(tmp_path / "weather-0.3.0.esplugin", target_files, version="0.3.0")
    running = placement(b"the running version's package")
    target_placement = placement(target.read_bytes(), version="0.3.0")

    archive = verify_package(target, "weather", target_placement.package, target_placement.runtime)

    assert archive.manifest.version == "0.3.0"
    with pytest.raises(PackageVerificationError, match="version '0.3.0', the desired state '0.2.0'"):
        verify_package(target, "weather", running.package, running.runtime)
