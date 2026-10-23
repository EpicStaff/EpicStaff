import hashlib
import json
import os
import stat
import zipfile

import pytest

from conftest import ICON_SVG
from epicstaff_plugin.cli.main import main
from epicstaff_plugin.contracts.manifest import parse_manifest
from epicstaff_plugin.package_layout import PackageFile, layout_problems, path_set_problems
from epicstaff_plugin.testing import service_account_key, write_runtime_file
from package_helpers import (
    MENU_ICON_PNG,
    MENU_ICON_SVG,
    add_menu,
    contents_for,
    manifest_with_menu,
    menu_files,
    sample_files,
    write_archive,
)


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


MENU_ICONS = {"icons/overview.svg": MENU_ICON_SVG, "icons/projects.png": MENU_ICON_PNG}
# One byte over the 16 KiB cap on a menu icon, and still a valid SVG.
OVERSIZED_MENU_ICON = MENU_ICON_SVG[:-6] + b" " * (16 * 1024 + 1 - len(MENU_ICON_SVG)) + b"</svg>"
SCRIPTED_MENU_ICON = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def test_a_source_with_a_menu_passes(plugin_source, capsys):
    source, spa = plugin_source
    add_menu(source, MENU_ICONS)

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 0
    assert "valid: weather 0.1.0 (source)" in capsys.readouterr().out


def test_a_source_may_keep_icons_its_menu_does_not_name(plugin_source):
    source, spa = plugin_source
    add_menu(source, {**MENU_ICONS, "icons/draft.svg": SCRIPTED_MENU_ICON}, named=list(MENU_ICONS))

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 0


def test_a_menu_icon_missing_from_the_source_fails(plugin_source, capsys):
    source, spa = plugin_source
    add_menu(source, MENU_ICONS, named=[*MENU_ICONS, "icons/missing.svg"])

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert "manifest.spa.navigation[2].icon: names icons/missing.svg, which is not in the package" in capsys.readouterr().out


def test_a_symbolic_link_is_not_followed_for_a_menu_icon(plugin_source, tmp_path, capsys):
    source, spa = plugin_source
    (tmp_path / "elsewhere.svg").write_bytes(MENU_ICON_SVG)
    add_menu(source, {}, named=["icons/overview.svg"])
    (source / "icons").mkdir()
    os.symlink(tmp_path / "elsewhere.svg", source / "icons" / "overview.svg")

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert "manifest.spa.navigation[0].icon: names icons/overview.svg, which is not in the package" in capsys.readouterr().out


def test_a_linked_icons_folder_is_not_followed(plugin_source, tmp_path, capsys):
    source, spa = plugin_source
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "overview.svg").write_bytes(MENU_ICON_SVG)
    add_menu(source, {}, named=["icons/overview.svg"])
    os.symlink(elsewhere, source / "icons")
    output = tmp_path / "weather.esplugin"

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert "manifest.spa.navigation[0].icon: names icons/overview.svg, which is not in the package" in capsys.readouterr().out
    assert main(["pack", str(source), "--spa-dir", str(spa), "--out", str(output)]) == 1
    assert not output.exists()


@pytest.mark.parametrize("folder", ["backend", "database"])
def test_a_linked_backend_or_database_folder_is_refused(weather_source, tmp_path, capsys, folder):
    elsewhere = tmp_path / f"elsewhere-{folder}"
    (weather_source / folder).rename(elsewhere)
    os.symlink(elsewhere, weather_source / folder)

    assert main(["validate", str(weather_source)]) == 1
    output = capsys.readouterr().out
    assert f"package.{folder}: is a symbolic link" in output
    assert f"package.{folder}/" not in output


@pytest.mark.parametrize(
    ("icon", "expected"),
    [
        (OVERSIZED_MENU_ICON, "package.icons/overview.svg: is larger than 16384 bytes"),
        (SCRIPTED_MENU_ICON, "package.icons/overview.svg: contains a <script> element"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "package.icons/overview.svg: has an event handler attribute (onload)"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/a.png"/></svg>', "package.icons/overview.svg: references an outside resource (href)"),
        (MENU_ICON_PNG, "package.icons/overview.svg: is not UTF-8"),
    ],
    ids=["oversized", "script", "event handler", "outside reference", "PNG named .svg"],
)
def test_a_menu_icon_is_checked_like_the_plugin_icon_in_a_source_and_a_package(plugin_source, tmp_path, capsys, icon, expected):
    source, spa = plugin_source
    add_menu(source, {"icons/overview.svg": icon})
    package = write_archive(tmp_path / "weather.esplugin", menu_files({"icons/overview.svg": icon}))

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 1
    assert expected in capsys.readouterr().out
    assert main(["validate", str(package)]) == 1
    assert expected in capsys.readouterr().out


def test_a_menu_png_that_is_not_a_png_fails(tmp_path, capsys):
    package = write_archive(tmp_path / "weather.esplugin", menu_files({"icons/projects.png": MENU_ICON_SVG}))

    assert main(["validate", str(package)]) == 1
    assert "package.icons/projects.png: is not a PNG image" in capsys.readouterr().out


def test_the_plugin_icon_keeps_its_own_size_cap(plugin_source):
    source, spa = plugin_source
    (source / "icon.svg").write_bytes(OVERSIZED_MENU_ICON)

    assert main(["validate", str(source), "--spa-dir", str(spa)]) == 0


def test_a_valid_built_package_with_a_menu_passes(tmp_path, capsys):
    package = write_archive(tmp_path / "weather.esplugin", menu_files(MENU_ICONS))

    assert main(["validate", str(package)]) == 0
    assert "valid: weather 0.1.0 (signature absent)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("manifest", "unnamed"),
    [
        (None, ["icons/extra.svg", "icons/overview.svg"]),
        (manifest_with_menu(["icons/overview.svg"]), ["icons/extra.svg"]),
    ],
    ids=["no menu", "a menu"],
)
def test_a_package_with_an_icons_file_no_menu_item_names_fails(tmp_path, capsys, manifest, unnamed):
    files = {**sample_files(manifest), "icons/overview.svg": MENU_ICON_SVG, "icons/extra.svg": MENU_ICON_SVG}
    package = write_archive(tmp_path / "weather.esplugin", files)

    assert main(["validate", str(package)]) == 1
    problems = [line for line in capsys.readouterr().out.splitlines() if "spa.navigation names" in line]
    assert problems == [f"package.{path}: is not an icon spa.navigation names" for path in unnamed]


def test_a_package_with_more_than_twelve_files_in_icons_fails(tmp_path, capsys):
    named = {f"icons/page-{index}.svg": MENU_ICON_SVG for index in range(12)}
    package = write_archive(tmp_path / "weather.esplugin", {**menu_files(named), "icons/page-12.svg": MENU_ICON_SVG})

    assert main(["validate", str(package)]) == 1
    output = capsys.readouterr().out
    assert "package.icons: holds more than 12 files" in output
    assert output.count("holds more than") == 1


def test_twelve_menu_icons_pass(tmp_path):
    named = {f"icons/page-{index}.svg": MENU_ICON_SVG for index in range(12)}
    package = write_archive(tmp_path / "weather.esplugin", menu_files(named))

    assert main(["validate", str(package)]) == 0


def test_a_root_icon_in_icons_is_not_the_plugin_icon(tmp_path, capsys):
    files = {**sample_files(), "icons/icon.svg": ICON_SVG}
    package = write_archive(tmp_path / "weather.esplugin", files)

    assert main(["validate", str(package)]) == 1
    assert "package.icons/icon.svg: is not an icon spa.navigation names" in capsys.readouterr().out


def test_path_set_problems_reports_files_used_as_folders():
    problems = path_set_problems(["spa/a", "spa/b/c.js", "spa/a/d.js", "spa/b"])

    assert [(problem.loc, problem.message) for problem in problems] == [
        ("package.spa/a/d.js", "is inside 'spa/a', which is a file"),
        ("package.spa/b", "is a file, but 'spa/b/c.js' needs it to be a folder"),
    ]


def test_a_menu_icon_in_the_files_without_its_contents_is_a_problem():
    # Every caller passes the contents of each menu icon in the files; one that did not must
    # not skip the icon's content checks.
    files = menu_files({"icons/overview.svg": MENU_ICON_SVG})
    described = {path: PackageFile(path=path, size=len(data), sha256=hashlib.sha256(data).hexdigest()) for path, data in files.items()}

    problems = layout_problems(parse_manifest(files["manifest.json"]), described, ICON_SVG, navigation_icons={})

    assert [(problem.loc, problem.message) for problem in problems] == [
        ("package.icons/overview.svg", "was not read, so it could not be checked"),
    ]



SECRET_LINE = "holds an EpicStaff key or runtime file; never package it"


def test_a_source_holding_a_runtime_file_is_refused_by_name(weather_source, signer, capsys):
    copy = weather_source / "backend" / "src" / "weather-development-runtime.json"
    write_runtime_file(copy, signer=signer, service_accounts={"3": {"key": service_account_key(), "org_name": "Acme", "grant_state": "active"}})

    assert main(["validate", str(weather_source)]) == 1

    output = capsys.readouterr().out
    assert f"package.backend/src/weather-development-runtime.json: {SECRET_LINE}" in output
    assert "esp-" not in output


def test_a_built_package_holding_a_key_is_refused_by_name(tmp_path, capsys):
    key = service_account_key()
    package = write_archive(tmp_path / "weather.esplugin", {**sample_files(), "spa/app.js": f"const k = '{key}';".encode()})

    assert main(["validate", str(package)]) == 1

    output = capsys.readouterr().out
    assert f"package.spa/app.js: {SECRET_LINE}" in output
    assert key not in output
