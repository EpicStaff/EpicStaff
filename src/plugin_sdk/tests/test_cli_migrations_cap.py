"""The caps on a package's migrations: their total size, which the plugin node holds in memory
while it runs them, and the length of each file name, which EpicStaff records and shows."""

import json
import re
import shutil
import zipfile
from typing import Annotated

import pytest
from pydantic import StringConstraints, TypeAdapter, ValidationError

from conftest import REPO_ROOT
from epicstaff_plugin.cli.main import main
from epicstaff_plugin.contracts.manifest import parse_manifest
from epicstaff_plugin.package_layout import (
    MAX_MIGRATION_NAME_LENGTH,
    MAX_MIGRATIONS_TOTAL_BYTES,
    MIGRATION_NAME_PATTERN,
    MIGRATION_PATTERN,
    MIGRATIONS_DIRECTORY,
    PackageFile,
    layout_problems,
)
from epicstaff_plugin.package_source import collect_source
from package_helpers import contents_for, write_archive

SAMPLE = REPO_ROOT / "plugin-samples" / "weather"
SAMPLE_VERSION = json.loads((SAMPLE / "manifest.json").read_text())["version"]
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
    number = max(int(path.name[:3]) for path in migrations.iterdir()) + 1
    while missing > 0:
        size = min(missing, PADDING_FILE_BYTES)
        (migrations / f"{number:03d}_padding.sql").write_bytes(b"-" * (size - 1) + b"\n")
        missing -= size
        number += 1


def test_migrations_up_to_the_cap_are_valid(database_source, capsys):
    source, spa = database_source
    _fill_migrations_to(source, MAX_MIGRATIONS_TOTAL_BYTES)

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 0
    assert f"valid: weather {SAMPLE_VERSION} (source)" in capsys.readouterr().out


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


def _package_files(source, spa):
    """The files `pack` puts in a package of `source`, read from disk, without CONTENTS.json."""
    return {file.path: file.source.read_bytes() for file in collect_source(source, spa).files}


def test_validate_refuses_a_package_whose_migrations_are_over_the_cap(database_source, tmp_path, capsys):
    source, spa = database_source
    _fill_migrations_to(source, MAX_MIGRATIONS_TOTAL_BYTES + 1)
    package = write_archive(tmp_path / "weather.esplugin", _package_files(source, spa))

    assert main(["validate", str(package)]) == 1
    assert CAP_PROBLEM in capsys.readouterr().out


# --- The file name of each migration ---


def _migration_name(length):
    """A valid migration file name, numbered 900, exactly `length` characters long."""
    return "900_" + "a" * (length - len("900_.sql")) + ".sql"


def _archive_names(package):
    with zipfile.ZipFile(package) as archive:
        return archive.namelist()


def _name_problem(name):
    return f"package.{MIGRATIONS_DIRECTORY}{name}: has a file name longer than {MAX_MIGRATION_NAME_LENGTH} characters"


def test_the_name_rule_is_one_plain_pattern_for_the_name_alone():
    assert MIGRATION_NAME_PATTERN == r"^[0-9]{3}_[a-z0-9][a-z0-9_]*\.sql$"
    assert isinstance(MIGRATION_NAME_PATTERN, str)
    assert MAX_MIGRATION_NAME_LENGTH == 255


@pytest.mark.parametrize(
    "name",
    ["001_weather.sql", "002_retention.sql", "123_a.sql", "001_9.sql", "1_weather.sql", "0001_x.sql",
     "001_Weather.sql", "001__x.sql", "001_x.SQL", "001_x.sql.bak", "001-x.sql", "001_x", "../001_x.sql"],
)
def test_the_path_pattern_follows_the_name_rule(name):
    assert bool(MIGRATION_PATTERN.match(MIGRATIONS_DIRECTORY + name)) == bool(re.fullmatch(MIGRATION_NAME_PATTERN, name))


def test_pydantic_takes_the_name_rule_as_a_string_constraint():
    migration_name = TypeAdapter(
        Annotated[str, StringConstraints(pattern=MIGRATION_NAME_PATTERN, max_length=MAX_MIGRATION_NAME_LENGTH)]
    )

    assert migration_name.validate_python("001_weather.sql") == "001_weather.sql"
    assert migration_name.validate_python(_migration_name(255)) == _migration_name(255)
    for refused in ("1_weather.sql", "001_Weather.sql", _migration_name(256)):
        with pytest.raises(ValidationError):
            migration_name.validate_python(refused)


def test_a_migration_name_of_255_characters_validates_and_packs(database_source, tmp_path, capsys):
    source, spa = database_source
    name = _migration_name(255)
    (source / "database" / "migrations" / name).write_text("SELECT 1;\n")
    output = tmp_path / "weather.esplugin"

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 0
    assert main(["pack", str(source), "--spa-dir", str(spa), "--out", str(output)]) == 0
    assert main(["validate", str(output)]) == 0
    assert f"{MIGRATIONS_DIRECTORY}{name}" in _archive_names(output)


def test_the_layout_check_refuses_a_migration_name_of_256_characters(database_source):
    # pack and validate check a source directory with this function. A file system refuses a
    # 256-character file name, so that path is checked here, without a file on disk.
    source, _ = database_source
    manifest = parse_manifest((source / "manifest.json").read_bytes())
    files = {
        path: PackageFile(path=path, size=10, sha256="0" * 64)
        for path in (f"{MIGRATIONS_DIRECTORY}001_weather.sql", f"{MIGRATIONS_DIRECTORY}{_migration_name(256)}")
    }

    problems = [f"{problem.loc}: {problem.message}" for problem in layout_problems(manifest, files, None, check_spa=False)]

    assert _name_problem(_migration_name(256)) in problems
    assert not any("001_weather.sql" in problem for problem in problems)


def test_validate_refuses_a_package_with_a_migration_name_of_256_characters(database_source, tmp_path, capsys):
    # A hand-built archive is how such a name would reach EpicStaff's upload and the plugin
    # node: both read every package through the same check.
    source, spa = database_source
    files = _package_files(source, spa)
    name = _migration_name(256)
    files[f"{MIGRATIONS_DIRECTORY}{name}"] = b"SELECT 1;\n"
    package = write_archive(tmp_path / "weather.esplugin", files, contents=contents_for(files, version=SAMPLE_VERSION))

    assert main(["validate", str(package)]) == 1
    output = capsys.readouterr().out
    assert _name_problem(name) in output
    assert output.count("package.") == 1


def test_two_migrations_with_one_number_are_refused(database_source, capsys):
    source, spa = database_source
    (source / "database" / "migrations" / "001_again.sql").write_text("SELECT 1;\n")

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert (
        f"package.{MIGRATIONS_DIRECTORY}001_weather.sql: has the same number as {MIGRATIONS_DIRECTORY}001_again.sql"
        in capsys.readouterr().out
    )
