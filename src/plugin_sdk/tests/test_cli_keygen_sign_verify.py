import stat
import zipfile

import pytest

from conftest import MINISIGN_FIXTURES
from epicstaff_plugin.cli.main import main
from epicstaff_plugin.package_layout import read_package_file
from epicstaff_plugin.signing import PublicKey


@pytest.fixture
def unsigned_package(plugin_source, tmp_path):
    source, spa = plugin_source
    output = tmp_path / "weather-0.1.0.esplugin"
    assert main(["pack", str(source), "--spa-dir", str(spa), "--out", str(output)]) == 0
    return output


@pytest.fixture
def key_prefix(tmp_path, capsys):
    prefix = tmp_path / "release"
    assert main(["keygen", "--out", str(prefix)]) == 0
    capsys.readouterr()
    return prefix


def _trusted_entry(prefix, name="release"):
    return f"{name}:{PublicKey.from_text(prefix.with_suffix('.pub').read_text()).to_text()}"


def test_keygen_writes_a_private_secret_key_and_prints_the_trusted_key_entry(tmp_path, capsys):
    prefix = tmp_path / "release"

    assert main(["keygen", "--out", str(prefix)]) == 0

    output = capsys.readouterr().out
    public_key = PublicKey.from_text((tmp_path / "release.pub").read_text())
    assert stat.S_IMODE((tmp_path / "release.key").stat().st_mode) == 0o600
    assert f"key id: {public_key.display_id}" in output
    assert f"PLUGINS_TRUSTED_SIGNING_KEYS entry: release:{public_key.to_text()}" in output


def test_keygen_never_overwrites_a_key(key_prefix, capsys):
    before = key_prefix.with_suffix(".key").read_bytes()

    assert main(["keygen", "--out", str(key_prefix)]) == 2

    assert "already exists" in capsys.readouterr().err
    assert key_prefix.with_suffix(".key").read_bytes() == before


def test_sign_then_verify_with_the_key_listed_is_trusted(unsigned_package, key_prefix, capsys):
    assert main(["sign", str(unsigned_package), "--key", f"{key_prefix}.key"]) == 0

    exit_code = main(["verify", str(unsigned_package), "--trusted-key", _trusted_entry(key_prefix)])

    lines = capsys.readouterr().out.splitlines()
    assert exit_code == 0
    assert "trusted" in lines
    assert "key name: release" in lines


def test_verify_without_the_key_listed_is_untrusted_and_shows_the_key_id(unsigned_package, key_prefix, capsys):
    main(["sign", str(unsigned_package), "--key", f"{key_prefix}.key"])
    key_id = PublicKey.from_text(key_prefix.with_suffix(".pub").read_text()).display_id
    capsys.readouterr()

    assert main(["verify", str(unsigned_package)]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["untrusted", f"key id: {key_id}"]


def test_verify_of_an_unsigned_package_is_untrusted(unsigned_package, capsys):
    assert main(["verify", str(unsigned_package)]) == 0
    assert capsys.readouterr().out.splitlines()[:2] == ["untrusted", "key id: none (unsigned)"]


def test_sign_replaces_an_existing_signature(unsigned_package, key_prefix, tmp_path, capsys):
    other_prefix = tmp_path / "other"
    main(["keygen", "--out", str(other_prefix)])
    main(["sign", str(unsigned_package), "--key", f"{key_prefix}.key"])

    assert main(["sign", str(unsigned_package), "--key", f"{other_prefix}.key"]) == 0

    capsys.readouterr()
    main(["verify", str(unsigned_package), "--trusted-key", _trusted_entry(other_prefix, "other")])
    assert "key name: other" in capsys.readouterr().out
    with zipfile.ZipFile(unsigned_package) as archive:
        assert archive.namelist().count("CONTENTS.json.minisig") == 1


def test_signing_keeps_the_package_contents(unsigned_package, key_prefix):
    before = read_package_file(unsigned_package)

    main(["sign", str(unsigned_package), "--key", f"{key_prefix}.key"])

    after = read_package_file(unsigned_package)
    assert after.contents == before.contents
    assert after.files == before.files


def test_sign_refuses_a_password_protected_key(unsigned_package, capsys):
    assert main(["sign", str(unsigned_package), "--key", str(MINISIGN_FIXTURES / "encrypted.key")]) == 2
    assert "sign with the minisign tool instead" in capsys.readouterr().err


def test_a_package_signed_by_the_minisign_tool_verifies(unsigned_package, capsys):
    # The minisign fixture key signs any CONTENTS.json through `sign`, the same bytes
    # minisign itself would write (see test_signing.py).
    main(["sign", str(unsigned_package), "--key", str(MINISIGN_FIXTURES / "minisign.key")])
    entry = f"minisign:{PublicKey.from_text((MINISIGN_FIXTURES / 'minisign.pub').read_text()).to_text()}"
    capsys.readouterr()

    assert main(["verify", str(unsigned_package), "--trusted-key", entry]) == 0
    assert "trusted" in capsys.readouterr().out.splitlines()


def test_verify_reports_a_signature_that_does_not_belong_to_the_package(unsigned_package, key_prefix, capsys):
    main(["sign", str(unsigned_package), "--key", f"{key_prefix}.key"])
    with zipfile.ZipFile(unsigned_package) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["CONTENTS.json.minisig"] = files["CONTENTS.json.minisig"].replace(b"version=0.1.0", b"version=0.2.0")
    with zipfile.ZipFile(unsigned_package, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    capsys.readouterr()

    assert main(["verify", str(unsigned_package), "--trusted-key", _trusted_entry(key_prefix)]) == 1
    assert capsys.readouterr().out.splitlines()[0] == "invalid"


def test_verify_refuses_a_malformed_trusted_key(unsigned_package, capsys):
    assert main(["verify", str(unsigned_package), "--trusted-key", "no-colon"]) == 2
    assert "--trusted-key entry 1" in capsys.readouterr().err
