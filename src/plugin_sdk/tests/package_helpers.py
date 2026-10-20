"""Hand-built package archives, including broken ones the CLI would never write."""

import hashlib
import json
import zipfile
from pathlib import Path

from conftest import ICON_SVG, SAMPLE_MANIFEST
from epicstaff_plugin.package_layout import PackageFile, build_contents

INDEX_HTML = b"<!doctype html><title>Weather</title>"


def sample_files(manifest=None):
    """The files of a valid frontend-only package, without CONTENTS.json."""
    return {
        "manifest.json": json.dumps(manifest or SAMPLE_MANIFEST).encode("utf-8"),
        "icon.svg": ICON_SVG,
        "spa/index.html": INDEX_HTML,
    }


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
