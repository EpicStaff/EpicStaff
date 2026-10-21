"""The cap on a package's migrations, which the plugin node holds in memory while it runs them."""

import shutil

import pytest

from conftest import REPO_ROOT
from epicstaff_plugin.cli.main import main
from epicstaff_plugin.package_layout import MAX_MIGRATIONS_TOTAL_BYTES
from package_helpers import write_archive

SAMPLE = REPO_ROOT / "plugin-samples" / "weather"
# Below the size from which a file's compression ratio is checked, so padding compresses freely.
PADDING_FILE_BYTES = 1024 * 1024 - 1
CAP_PROBLEM = f"package.database: holds more than {MAX_MIGRATIONS_TOTAL_BYTES} bytes of migrations"


@pytest.fixture
def database_source(tmp_path):
    """A copy of the Weather sample (a backend with a database) and a built SPA, as (source, spa)."""
    source = tmp_path / "weather"
    shutil.copytree(SAMPLE, source, ignore=shutil.ignore_patterns("spa", "README.md", "__pycache__"))
    lock = source / "backend" / "requirements.lock"
    # Packing without --local-wheel needs the lock to pin the SDK itself.
    lock.write_text(lock.read_text() + f"epicstaff-plugin==0.1.0 --hash=sha256:{'0' * 64}\n")
    spa = tmp_path / "dist"
    spa.mkdir()
    (spa / "index.html").write_text("<!doctype html><title>Weather</title>")
    return source, spa


def _fill_migrations_to(source, total_bytes):
    """Add migrations after the sample's own until all of them hold `total_bytes`."""
    migrations = source / "database" / "migrations"
    missing = total_bytes - sum(path.stat().st_size for path in migrations.iterdir())
    number = 2
    while missing > 0:
        size = min(missing, PADDING_FILE_BYTES)
        (migrations / f"{number:03d}_padding.sql").write_bytes(b"-" * (size - 1) + b"\n")
        missing -= size
        number += 1


def test_migrations_up_to_the_cap_are_valid(database_source, capsys):
    source, spa = database_source
    _fill_migrations_to(source, MAX_MIGRATIONS_TOTAL_BYTES)

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 0
    assert "valid: weather 0.5.0 (source)" in capsys.readouterr().out


def test_validate_refuses_migrations_over_the_cap(database_source, capsys):
    source, spa = database_source
    _fill_migrations_to(source, MAX_MIGRATIONS_TOTAL_BYTES + 1)

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert CAP_PROBLEM in capsys.readouterr().out


def test_pack_refuses_migrations_over_the_cap_and_writes_nothing(database_source, tmp_path, capsys):
    source, spa = database_source
    output = tmp_path / "weather.esplugin"
    assert main(["pack", str(source), "--spa-dir", str(spa), "--out", str(output)]) == 0
    output.unlink()
    capsys.readouterr()

    _fill_migrations_to(source, MAX_MIGRATIONS_TOTAL_BYTES + 1)

    assert main(["pack", str(source), "--spa-dir", str(spa), "--out", str(output)]) == 1
    assert CAP_PROBLEM in capsys.readouterr().out
    assert not output.exists()


def test_validate_refuses_a_package_whose_migrations_are_over_the_cap(database_source, tmp_path, capsys):
    source, spa = database_source
    _fill_migrations_to(source, MAX_MIGRATIONS_TOTAL_BYTES + 1)
    files = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in sorted(source.rglob("*"))
        if path.is_file() and path.name != "requirements.in"
    }
    files["spa/index.html"] = (spa / "index.html").read_bytes()
    package = write_archive(tmp_path / "weather.esplugin", files)

    assert main(["validate", str(package)]) == 1
    assert CAP_PROBLEM in capsys.readouterr().out
