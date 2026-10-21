"""Package caps and path rules, as Django applies them to an upload."""

import io
import json
import secrets
import stat
import unicodedata
import zipfile

import pytest
from plugins.exceptions import InvalidPluginError
from plugins.packages.package_reader import read_uploaded_package

from tests.plugins_tests.package_builder import (
    APP_JS,
    ICON_SVG,
    PNG_ICON,
    build_package,
    contents_for,
    sample_files,
    sample_manifest,
    set_entry_flag,
)


def _locs(data: bytes) -> list[str]:
    with pytest.raises(InvalidPluginError) as raised:
        read_uploaded_package(io.BytesIO(data))
    return [error["loc"] for error in raised.value.errors]


def _messages(data: bytes) -> list[str]:
    with pytest.raises(InvalidPluginError) as raised:
        read_uploaded_package(io.BytesIO(data))
    return [f"{error['loc']}: {error['message']}" for error in raised.value.errors]


def _with_file(path: str, data: bytes, manifest=None) -> bytes:
    """A package holding an extra, properly listed file."""
    files = {**sample_files(manifest), path: data}
    return build_package(files, manifest=manifest)


def test_a_valid_package_is_read():
    package = read_uploaded_package(io.BytesIO(build_package()))

    assert package.manifest.id == "weather"
    assert package.icon == ICON_SVG
    assert package.icon_media_type == "image/svg+xml"
    assert [file.path for file in package.spa_files] == ["spa/assets/app.js", "spa/index.html"]
    assert package.summary.spa_file_count == 2
    assert package.summary.spa_bytes == len(APP_JS) + len(sample_files()["spa/index.html"])


def test_directory_entries_are_ignored():
    directory = zipfile.ZipInfo("spa/assets/")
    directory.external_attr = (stat.S_IFDIR | 0o755) << 16

    package = read_uploaded_package(io.BytesIO(build_package(raw_entries=[(directory, b"")])))

    assert package.summary.spa_file_count == 2


def test_a_file_that_is_not_a_zip_is_rejected():
    assert _messages(b"not a zip") == ["package: is not a zip archive"]


def test_more_than_ten_thousand_entries_are_rejected():
    files = sample_files()
    files.update({f"spa/{index}.js": b"" for index in range(10_000)})

    assert _messages(build_package(files)) == ["package: has more than 10000 entries"]


def test_the_uncompressed_total_is_capped_while_streaming(monkeypatch):
    monkeypatch.setattr("plugins.packages.package_reader.MAX_UNCOMPRESSED_BYTES", 100)

    [message] = _messages(build_package())

    assert message.startswith("package: ")
    assert "pushes the extraction past 100 bytes" in message


def test_a_single_file_is_capped(monkeypatch):
    monkeypatch.setattr("epicstaff_plugin.package_layout.MAX_FILE_BYTES", len(APP_JS) - 1)

    assert "package.spa/assets/app.js" in _locs(build_package())


def test_a_file_above_one_mib_that_expands_more_than_a_hundred_times_is_rejected():
    assert _messages(_with_file("spa/zeros.bin", bytes(2 * 1024 * 1024))) == [
        "package.spa/zeros.bin: is larger than 1048576 bytes and expands more than 100 times "
        "when uncompressed"
    ]


@pytest.mark.parametrize("size", [20 * 1024, 1024 * 1024], ids=["20 KiB", "exactly 1 MiB"])
def test_a_file_up_to_one_mib_may_compress_well(size):
    package = read_uploaded_package(io.BytesIO(_with_file("spa/padding.txt", b" " * size)))

    assert "spa/padding.txt" in [file.path for file in package.files]


@pytest.mark.parametrize(
    ("paths", "clash"),
    [
        (["spa/a", "spa/a/b.js"], "package.spa/a/b.js: is inside 'spa/a', which is a file"),
        (["spa/a/b.js", "spa/a"], "package.spa/a: is a file, but 'spa/a/b.js' needs it to be a folder"),
        (["spa/A", "spa/a/b.js"], "package.spa/a/b.js: is inside 'spa/A', which is a file"),
        (["spa/a/b/c.js", "spa/a/b"], "package.spa/a/b: is a file, but 'spa/a/b/c.js' needs it to be a folder"),
    ],
    ids=["file first", "folder first", "differing case", "nested"],
)
def test_a_file_that_is_also_a_folder_of_another_is_rejected(paths, clash):
    files = {**sample_files(), **{path: b"x" for path in paths}}

    assert _messages(build_package(files)) == [clash]


def test_more_than_two_thousand_spa_files_are_rejected():
    files = sample_files()
    files.update({f"spa/chunk-{index}.js": f"// {index}".encode() for index in range(2000)})

    assert _messages(build_package(files)) == ["package.spa: holds more than 2000 files"]


def test_the_spa_size_is_capped(monkeypatch):
    monkeypatch.setattr("epicstaff_plugin.package_layout.MAX_SPA_BYTES", 10)

    assert _messages(build_package()) == ["package.spa: holds more than 10 bytes"]


@pytest.mark.parametrize(
    "path",
    [
        "../evil.js",
        "spa/../../evil.js",
        "/etc/passwd",
        "spa\\evil.js",
        "C:/evil.js",
        "spa/./index2.html",
        "spa//index2.html",
        "spa/bad\x01name.js",
        unicodedata.normalize("NFD", "spa/caf\u00e9.js"),
    ],
    ids=["dot-dot", "nested dot-dot", "absolute", "backslash", "drive letter", "dot segment", "empty segment", "control character", "not NFC"],
)
def test_unsafe_paths_are_rejected(path):
    [message] = _messages(build_package(unlisted={path: b"x"}))

    assert message.startswith(f"package: the path {path!r} ")


def test_paths_that_differ_only_in_case_are_rejected():
    assert "package.spa/Index.html" in _locs(build_package(unlisted={"spa/Index.html": b"x"}))


def test_a_symbolic_link_is_rejected():
    link = zipfile.ZipInfo("spa/passwd")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16

    assert _messages(build_package(raw_entries=[(link, b"/etc/passwd")])) == [
        "package.spa/passwd: is a symbolic link"
    ]


def test_a_special_file_is_rejected():
    fifo = zipfile.ZipInfo("spa/pipe")
    fifo.create_system = 3
    fifo.external_attr = (stat.S_IFIFO | 0o644) << 16

    assert _messages(build_package(raw_entries=[(fifo, b"")])) == ["package.spa/pipe: is not a regular file"]


def test_an_encrypted_entry_is_rejected():
    data = set_entry_flag(build_package(unlisted={"spa/secret.js": b"x"}), "spa/secret.js", 0x1)

    assert "package.spa/secret.js: is encrypted" in _messages(data)


def test_an_unsupported_compression_method_is_rejected():
    entry = zipfile.ZipInfo("spa/data.js")
    entry.compress_type = zipfile.ZIP_BZIP2

    assert "package.spa/data.js: uses a compression method other than stored or deflate" in _messages(
        build_package(raw_entries=[(entry, b"x")])
    )


def test_an_unlisted_file_is_rejected():
    assert _messages(build_package(unlisted={"spa/extra.js": b"x"})) == [
        "package.spa/extra.js: is not listed in CONTENTS.json"
    ]


def test_a_listed_file_that_is_missing_is_rejected():
    files = sample_files()
    contents = contents_for({**files, "spa/missing.js": b"x"})

    [message] = _messages(build_package(files, contents=contents))

    assert message.startswith("contents.files[")
    assert "spa/missing.js, which is not in the package" in message


def test_a_size_mismatch_is_rejected():
    files = sample_files()
    contents = contents_for(files).replace(b'"size":%d' % len(APP_JS), b'"size":%d' % (len(APP_JS) + 1))

    [loc] = _locs(build_package(files, contents=contents))
    assert loc.startswith("contents.files[") and loc.endswith("].size")


def test_a_sha256_mismatch_is_rejected():
    files = sample_files()
    contents = contents_for(files)
    files["spa/assets/app.js"] = APP_JS.replace(b"Weather", b"Wxather")

    [loc] = _locs(build_package(files, contents=contents))
    assert loc.startswith("contents.files[") and loc.endswith("].sha256")


@pytest.mark.parametrize(
    "rewrite",
    [
        lambda raw: raw + b"\n",
        lambda raw: json.dumps(json.loads(raw), indent=2).encode(),
        lambda raw: json.dumps(json.loads(raw), separators=(", ", ": "), sort_keys=True).encode(),
    ],
    ids=["trailing newline", "indented", "spaces"],
)
def test_a_contents_json_not_in_canonical_form_is_rejected(rewrite):
    files = sample_files()

    assert _locs(build_package(files, contents=rewrite(contents_for(files)))) == ["contents"]


def test_contents_json_files_must_be_sorted():
    files = sample_files()
    document = json.loads(contents_for(files))
    document["files"].reverse()
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()

    assert _locs(build_package(files, contents=raw)) == ["contents.files"]


def test_contents_json_must_name_the_manifest_s_plugin_and_version():
    files = sample_files()

    assert sorted(_locs(build_package(files, contents=contents_for(files, "forecast", "9.9.9")))) == [
        "contents.plugin_id",
        "contents.version",
    ]


@pytest.mark.parametrize("missing", ["manifest.json", "CONTENTS.json"])
def test_the_manifest_and_contents_json_are_required(missing):
    files = sample_files()
    if missing == "manifest.json":
        del files["manifest.json"]
        data = build_package(files, contents=contents_for(files))
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for path, content in files.items():
                archive.writestr(path, content)
        data = buffer.getvalue()

    assert f"package: {missing} is missing" in _messages(data)


def test_a_file_outside_the_fixed_layout_is_rejected():
    assert _messages(_with_file("notes.txt", b"x")) == ["package.notes.txt: is not a file a plugin package may hold"]


def test_spa_files_without_an_spa_section_are_rejected():
    manifest = sample_manifest()
    del manifest["spa"]

    assert "package.spa/index.html: is under spa/, but the manifest has no spa section" in _messages(
        build_package(manifest=manifest)
    )


def test_the_spa_entry_must_exist():
    manifest = sample_manifest(spa={"entry": "app.html"})

    assert _locs(build_package(manifest=manifest)) == ["manifest.spa.entry"]


def test_the_icon_is_capped_at_64_kb():
    filler = secrets.token_hex(33 * 1024).encode()
    big_icon = ICON_SVG.replace(b"</svg>", b"<!--" + filler + b"--></svg>")
    files = {**sample_files(), "icon.svg": big_icon}

    assert _messages(build_package(files)) == ["package.icon.svg: is larger than 65536 bytes"]


@pytest.mark.parametrize(
    ("svg", "problem"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "contains a <script> element"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>',
            "contains a <foreignObject> element",
        ),
        (b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "has an event handler attribute (onload)"),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            b'<image xlink:href="https://example.com/x.png"/></svg>',
            "references an outside resource (href)",
        ),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill: url(https://example.com/x)"/></svg>',
            "references an outside resource (style)",
        ),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://example.com/x.css);</style></svg>',
            "has a style that references an outside resource",
        ),
        (
            b'<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
            "must not contain a DOCTYPE or entity declaration",
        ),
        (b"<html><body/></html>", "does not have an <svg> root element"),
        (b"<svg", "is not well-formed XML"),
    ],
    ids=["script", "foreignObject", "event handler", "external href", "css url", "css import", "doctype", "not svg", "broken xml"],
)
def test_an_unsafe_svg_icon_is_rejected(svg, problem):
    [message] = _messages(build_package({**sample_files(), "icon.svg": svg}))

    assert message.startswith(f"package.icon.svg: {problem}")


def test_internal_svg_references_are_allowed():
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        b'<defs><linearGradient id="g"/></defs><rect fill="url(#g)"/><use xlink:href="#g"/></svg>'
    )

    assert read_uploaded_package(io.BytesIO(build_package({**sample_files(), "icon.svg": svg}))).icon == svg


def test_a_png_icon_must_be_a_png():
    manifest = sample_manifest(icon="icon.png")
    files = {**sample_files(manifest), "icon.png": b"GIF89a"}

    assert _messages(build_package(files, manifest=manifest)) == ["package.icon.png: is not a PNG image"]


def test_a_png_icon_is_read():
    manifest = sample_manifest(icon="icon.png")
    files = {**sample_files(manifest), "icon.png": PNG_ICON}

    package = read_uploaded_package(io.BytesIO(build_package(files, manifest=manifest)))

    assert package.icon_media_type == "image/png"


def test_an_icon_the_manifest_does_not_name_is_rejected():
    assert _messages(_with_file("icon.png", PNG_ICON)) == [
        "package.icon.png: is not the icon the manifest names (icon.svg)"
    ]


def test_manifest_problems_are_located_under_manifest():
    manifest = sample_manifest(id="Weather!")

    assert "manifest.id" in _locs(build_package(manifest=manifest))
