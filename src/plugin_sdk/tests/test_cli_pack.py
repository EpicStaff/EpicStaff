import hashlib
import json
import zipfile

from epicstaff_plugin.cli.main import main
from epicstaff_plugin.package_layout import icon_media_type_of, read_package_file
from epicstaff_plugin.signing import SecretKey, SignatureFile
from epicstaff_plugin.testing import service_account_key, write_runtime_file
from package_helpers import MENU_ICON_PNG, MENU_ICON_SVG, add_menu


def _pack(source, spa, output, *extra):
    return main(["pack", str(source), "--spa-dir", str(spa), "--out", str(output), *extra])


def test_packing_twice_gives_identical_bytes(plugin_source, tmp_path):
    source, spa = plugin_source
    first, second = tmp_path / "first.esplugin", tmp_path / "second.esplugin"

    assert _pack(source, spa, first) == 0
    # A later modification time must not change the package.
    (spa / "index.html").touch()
    assert _pack(source, spa, second) == 0

    assert first.read_bytes() == second.read_bytes()


def test_entries_are_sorted_with_fixed_time_mode_and_compression(plugin_source, tmp_path):
    source, spa = plugin_source
    output = tmp_path / "weather-0.1.0.esplugin"

    _pack(source, spa, output)

    with zipfile.ZipFile(output) as archive:
        infos = archive.infolist()
    names = [info.filename for info in infos]
    assert names == sorted(names)
    assert names == ["CONTENTS.json", "icon.svg", "manifest.json", "spa/assets/app.js", "spa/index.html"]
    assert {info.date_time for info in infos} == {(1980, 1, 1, 0, 0, 0)}
    assert {info.external_attr >> 16 for info in infos} == {0o100644}
    assert {info.compress_type for info in infos} == {zipfile.ZIP_DEFLATED}


def test_contents_json_lists_every_file_in_canonical_form(plugin_source, tmp_path):
    source, spa = plugin_source
    output = tmp_path / "weather.esplugin"

    _pack(source, spa, output)

    with zipfile.ZipFile(output) as archive:
        raw = archive.read("CONTENTS.json")
        index = archive.read("spa/index.html")
    document = json.loads(raw)
    assert raw == json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert (document["plugin_id"], document["version"], document["format"]) == ("weather", "0.1.0", 1)
    assert {"path": "spa/index.html", "sha256": hashlib.sha256(index).hexdigest(), "size": len(index)} in document["files"]
    assert [entry["path"] for entry in document["files"]] == [
        "icon.svg",
        "manifest.json",
        "spa/assets/app.js",
        "spa/index.html",
    ]


def test_only_the_icons_the_menu_names_are_packed(plugin_source, tmp_path):
    source, spa = plugin_source
    add_menu(
        source,
        {"icons/overview.svg": MENU_ICON_SVG, "icons/projects.png": MENU_ICON_PNG, "icons/draft.svg": MENU_ICON_SVG},
        # Two items share one icon; icons/draft.svg is in the source but on no item.
        named=["icons/overview.svg", "icons/projects.png", "icons/overview.svg"],
    )
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output) == 0

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        listed = [entry["path"] for entry in json.loads(archive.read("CONTENTS.json"))["files"]]
    assert [name for name in names if name.startswith("icons/")] == ["icons/overview.svg", "icons/projects.png"]
    assert {"icons/overview.svg", "icons/projects.png"} <= set(listed)
    assert "icons/draft.svg" not in listed


def test_a_packed_menu_reads_back_with_its_icons(plugin_source, tmp_path):
    source, spa = plugin_source
    add_menu(source, {"icons/projects.png": MENU_ICON_PNG, "icons/overview.svg": MENU_ICON_SVG})
    output = tmp_path / "weather.esplugin"
    _pack(source, spa, output)

    package = read_package_file(output)

    assert dict(package.navigation_icons) == {"icons/overview.svg": MENU_ICON_SVG, "icons/projects.png": MENU_ICON_PNG}
    assert list(package.navigation_icons) == ["icons/overview.svg", "icons/projects.png"]
    assert [icon_media_type_of(path) for path in package.navigation_icons] == ["image/svg+xml", "image/png"]
    assert [(item.label, item.path, item.icon) for item in package.manifest.spa.navigation] == [
        ("Page 0", "/", "icons/projects.png"),
        ("Page 1", "/page-1", "icons/overview.svg"),
    ]


def test_a_package_without_a_menu_reads_back_without_menu_icons(plugin_source, tmp_path):
    source, spa = plugin_source
    output = tmp_path / "weather.esplugin"
    _pack(source, spa, output)

    package = read_package_file(output)

    assert dict(package.navigation_icons) == {}
    assert icon_media_type_of(package.manifest.icon) == package.icon_media_type == "image/svg+xml"


def test_a_menu_icon_missing_from_the_source_writes_no_package(plugin_source, tmp_path, capsys):
    source, spa = plugin_source
    add_menu(source, {}, named=["icons/overview.svg"])
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output) == 1
    assert "manifest.spa.navigation[0].icon: names icons/overview.svg, which is not in the package" in capsys.readouterr().out
    assert not output.exists()


def test_packing_with_a_key_signs_the_package(plugin_source, tmp_path):
    source, spa = plugin_source
    key_prefix = tmp_path / "release"
    assert main(["keygen", "--out", str(key_prefix)]) == 0
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output, "--key", str(key_prefix) + ".key") == 0

    package = read_package_file(output)
    public_key = SecretKey.from_file_text((tmp_path / "release.key").read_text()).public_key
    assert SignatureFile.from_text(package.signature).verifies_with(public_key, package.contents)


def test_editor_and_interpreter_litter_is_left_out(plugin_source, tmp_path):
    source, spa = plugin_source
    (spa / ".DS_Store").write_bytes(b"\0")
    (spa / "__pycache__").mkdir()
    (spa / "__pycache__" / "x.pyc").write_bytes(b"\0")
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output) == 0

    with zipfile.ZipFile(output) as archive:
        assert not [name for name in archive.namelist() if "DS_Store" in name or "pycache" in name]


def test_a_manifest_with_an_spa_needs_the_spa_directory(plugin_source, tmp_path, capsys):
    source, _ = plugin_source
    output = tmp_path / "weather.esplugin"

    assert main(["pack", str(source), "--out", str(output)]) == 1
    assert "manifest.spa: pass the built single-page app with --spa-dir" in capsys.readouterr().out
    assert not output.exists()


def test_an_invalid_source_writes_no_package(plugin_source, tmp_path):
    source, spa = plugin_source
    (source / "icon.svg").unlink()
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output) == 1
    assert not output.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_a_large_file_that_compresses_too_well_is_caught_after_writing(plugin_source, tmp_path, capsys):
    source, spa = plugin_source
    (spa / "zeros.bin").write_bytes(bytes(2 * 1024 * 1024))
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output) == 1
    assert (
        "package.spa/zeros.bin: is larger than 1048576 bytes and expands more than 100 times"
        in capsys.readouterr().out
    )
    assert not output.exists()


def test_a_small_file_may_compress_well(plugin_source, tmp_path):
    source, spa = plugin_source
    (spa / "padding.txt").write_bytes(b" " * 20 * 1024)

    assert _pack(source, spa, tmp_path / "weather.esplugin") == 0


def test_a_key_in_the_page_writes_no_package_and_is_never_printed(plugin_source, tmp_path, capsys):
    source, spa = plugin_source
    key = service_account_key()
    (spa / "assets" / "config.js").write_text(f"export const key = '{key}';\n")
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output) == 1

    printed = capsys.readouterr()
    assert "package.spa/assets/config.js: holds an EpicStaff key or runtime file; never package it" in printed.out
    assert key not in printed.out + printed.err
    assert not output.exists()


def test_a_runtime_file_in_the_page_writes_no_package(plugin_source, tmp_path, signer, capsys):
    source, spa = plugin_source
    write_runtime_file(spa / "runtime.json", signer=signer, secret_settings={"forecast_api_token": "s3cret-value"})
    output = tmp_path / "weather.esplugin"

    assert _pack(source, spa, output) == 1

    printed = capsys.readouterr().out
    assert "package.spa/runtime.json: holds an EpicStaff key or runtime file; never package it" in printed
    assert "s3cret-value" not in printed
    assert not output.exists()
