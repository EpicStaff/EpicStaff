import json
import os
import stat
import zipfile

import pytest

from epicstaff_plugin.cli.main import main
from epicstaff_plugin.package_layout import path_set_problems
from package_helpers import contents_for, sample_files, write_archive


def test_a_valid_source_directory_with_its_spa_passes(plugin_source, capsys):
    source, spa = plugin_source

    exit_code = main(["validate", str(source), "--spa-dir", str(spa)])

    assert exit_code == 0
    assert "valid: weather 0.1.0 (source)" in capsys.readouterr().out


def test_a_source_directory_without_its_spa_passes_with_a_note(plugin_source, capsys):
    source, _ = plugin_source

    exit_code = main(["validate", str(source)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "was not checked" in output


def test_a_broken_manifest_fails_with_located_problems(plugin_source, capsys):
    source, spa = plugin_source
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["id"] = "admin"
    del manifest["user_permissions"]
    (source / "manifest.json").write_text(json.dumps(manifest))

    exit_code = main(["validate", str(source), "--spa-dir", str(spa)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "manifest.id: 'admin' is reserved" in output
    assert "manifest.user_permissions: Field required" in output


def test_an_spa_without_its_entry_fails(plugin_source, capsys):
    source, spa = plugin_source
    (spa / "index.html").unlink()

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert "manifest.spa.entry: names spa/index.html" in capsys.readouterr().out


def test_a_symbolic_link_in_the_spa_fails(plugin_source, capsys):
    source, spa = plugin_source
    os.symlink("/etc/passwd", spa / "passwd")

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert "package.spa/passwd: is a symbolic link" in capsys.readouterr().out


def test_an_unsafe_icon_fails(plugin_source, capsys):
    source, spa = plugin_source
    (source / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert "package.icon.svg: contains a <script> element" in capsys.readouterr().out


def test_files_outside_the_layout_fail(plugin_source, capsys):
    source, spa = plugin_source
    (source / "backend").mkdir()
    (source / "backend" / "app.py").write_text("app = None\n")

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert "package.backend/app.py: is under backend/, but the manifest has no backend section" in capsys.readouterr().out


def test_a_valid_built_package_passes(tmp_path, capsys):
    package = write_archive(tmp_path / "weather-0.1.0.esplugin", sample_files())

    assert main(["validate", str(package)]) == 0
    assert "valid: weather 0.1.0 (signature absent)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (lambda path: write_archive(path, sample_files(), extra={"notes.txt": b"x"}), "package.notes.txt: is not listed in CONTENTS.json"),
        (lambda path: write_archive(path, sample_files(), extra={"../evil": b"x"}), "package: the path '../evil' has an empty, '.' or '..' segment"),
        (
            lambda path: write_archive(path, sample_files(), contents=json.dumps(json.loads(contents_for(sample_files())), indent=1).encode()),
            "contents: is not in canonical form",
        ),
        (lambda path: write_archive(path, sample_files(), signature="not a signature"), "signature: CONTENTS.json.minisig: a signature file has exactly four lines"),
    ],
    ids=["unlisted file", "dot-dot path", "non-canonical CONTENTS.json", "malformed signature"],
)
def test_a_broken_built_package_fails(tmp_path, capsys, build, expected):
    package = build(tmp_path / "weather-0.1.0.esplugin")

    assert main(["validate", str(package)]) == 1
    assert expected in capsys.readouterr().out


def test_a_symbolic_link_entry_in_a_package_fails(tmp_path, capsys):
    link = zipfile.ZipInfo("spa/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    package = write_archive(tmp_path / "weather.esplugin", sample_files(), infos=[(link, "/etc/passwd")])

    assert main(["validate", str(package)]) == 1
    assert "package.spa/link: is a symbolic link" in capsys.readouterr().out


def test_a_file_that_is_not_a_zip_fails(tmp_path, capsys):
    package = tmp_path / "weather.esplugin"
    package.write_bytes(b"not a zip")

    assert main(["validate", str(package)]) == 1
    assert "package: is not a zip archive" in capsys.readouterr().out


def test_a_missing_target_is_a_usage_error(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "missing")]) == 2
    assert "is neither a directory nor a file" in capsys.readouterr().err


def test_spa_dir_with_a_built_package_is_a_usage_error(tmp_path, capsys):
    package = write_archive(tmp_path / "weather.esplugin", sample_files())

    assert main(["validate", str(package), "--spa-dir", str(tmp_path)]) == 2


@pytest.mark.parametrize(
    "paths",
    [["spa/a", "spa/a/b.js"], ["spa/a/b.js", "spa/a"], ["spa/A", "spa/a/b.js"]],
    ids=["file first", "folder first", "differing case"],
)
def test_a_path_that_is_also_a_folder_of_another_fails(tmp_path, capsys, paths):
    files = {**sample_files(), **{path: b"x" for path in paths}}
    package = write_archive(tmp_path / "weather.esplugin", files)

    assert main(["validate", str(package)]) == 1
    assert f"package.{paths[1]}: " in capsys.readouterr().out


def test_path_set_problems_reports_files_used_as_folders():
    problems = path_set_problems(["spa/a", "spa/b/c.js", "spa/a/d.js", "spa/b"])

    assert [(problem.loc, problem.message) for problem in problems] == [
        ("package.spa/a/d.js", "is inside 'spa/a', which is a file"),
        ("package.spa/b", "is a file, but 'spa/b/c.js' needs it to be a folder"),
    ]

