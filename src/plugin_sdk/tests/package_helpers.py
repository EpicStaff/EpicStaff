"""Hand-built package archives, including broken ones the CLI would never write, and app menus
for packages and plugin sources."""

import copy
import hashlib
import json
import zipfile
from pathlib import Path

from conftest import ICON_SVG, SAMPLE_MANIFEST
from epicstaff_plugin.package_layout import PackageFile, build_contents

INDEX_HTML = b"<!doctype html><title>Weather</title>"
MENU_ICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path d="M4 4h16v16H4z" fill="currentColor"/></svg>'
)
# The format check reads only the PNG signature.
MENU_ICON_PNG = b"\x89PNG\r\n\x1a\n" + bytes(32)


def sample_files(manifest=None):
    """The files of a valid frontend-only package, without CONTENTS.json."""
    return {
        "manifest.json": json.dumps(manifest or SAMPLE_MANIFEST).encode("utf-8"),
        "icon.svg": ICON_SVG,
        "spa/index.html": INDEX_HTML,
    }


def manifest_with_menu(icons, manifest=None):
    """`manifest` (the sample by default) with one menu item per entry of `icons`, at `/`,
    `/page-1`, `/page-2`, ...; an icon listed twice is shared by two items."""
    document = copy.deepcopy(manifest or SAMPLE_MANIFEST)
    document["spa"]["navigation"] = [
        {"label": f"Page {index}", "path": f"/page-{index}" if index else "/", "icon": icon}
        for index, icon in enumerate(icons)
    ]
    return document


def menu_files(icons):
    """The files of a valid frontend-only package with a menu item per icon (path -> bytes)."""
    return {**sample_files(manifest_with_menu(list(icons))), **icons}


def add_menu(source: Path, icons, named=None):
    """Write `icons` (path -> bytes) into the plugin source at `source` and give its manifest a
    menu item per icon in `named` (default: every one of `icons`)."""
    manifest = json.loads((source / "manifest.json").read_text())
    named = list(icons) if named is None else named
    (source / "manifest.json").write_text(json.dumps(manifest_with_menu(named, manifest)))
    for path, data in icons.items():
        (source / path).parent.mkdir(parents=True, exist_ok=True)
        (source / path).write_bytes(data)


def contents_for(files, plugin_id="weather", version="0.1.0"):
    return build_contents(
        plugin_id,
        version,
        [
            PackageFile(path=path, size=len(data), sha256=hashlib.sha256(data).hexdigest())
            for path, data in files.items()
        ],
    )


def write_archive(path: Path, files, *, contents=None, extra=None, signature=None, infos=None):
    """Write a zip holding `files`, their CONTENTS.json (unless `contents` is given), and
    `extra` files that CONTENTS.json does not list. `infos` are raw ZipInfo entries."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("CONTENTS.json", contents_for(files) if contents is None else contents)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
        if signature is not None:
            archive.writestr("CONTENTS.json.minisig", signature)
        for info, data in infos or []:
            archive.writestr(info, data)
    return path
