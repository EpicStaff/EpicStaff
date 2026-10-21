"""Builds `.esplugin` packages in memory, valid or deliberately broken."""

import copy
import hashlib
import io
import json
import zipfile

from epicstaff_plugin.package_layout import PackageFile, build_contents
from epicstaff_plugin.signing import SecretKey, sign_package

ICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<circle cx="12" cy="12" r="5" fill="currentColor"/></svg>'
)
PNG_ICON = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
INDEX_HTML = b"<!doctype html><title>Weather</title><script src=app.js></script>"
APP_JS = b"document.title = 'Weather';\n"

SAMPLE_MANIFEST = {
    "manifest_version": 1,
    "id": "weather",
    "version": "0.1.0",
    "name": "Weather",
    "description": "Forecasts for the places your organization cares about.",
    "publisher": {"name": "EpicStaff"},
    "icon": "icon.svg",
    "platform": {"frame_protocol": 1, "gateway_context": 1, "hook_api": 1},
    "spa": {"entry": "index.html"},
    "user_permissions": [
        {
            "action": "read",
            "description": "Open Weather and see forecasts.",
            "defaults": {"org_admin": True, "member": True, "viewer": False},
        }
    ],
}

BACKEND = {"python": "3.12", "entrypoint": "plugin.app:app"}
# Every backend's lock pins the SDK and uvicorn, each with a sha256.
BACKEND_LOCK = (
    "uvicorn==0.52.3 --hash=sha256:" + "a" * 64 + "\n"
    "epicstaff-plugin==0.1.0 --hash=sha256:" + "b" * 64 + "\n"
).encode("utf-8")
BACKEND_FILES = {"backend/requirements.lock": BACKEND_LOCK, "backend/src/plugin/app.py": b"app = None\n"}

PING_PATH = {"path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0}
UNITS_SETTING = {
    "key": "units",
    "type": "enum",
    "label": "Units",
    "description": "Units for every organization.",
    "required": True,
    "default": "metric",
    "values": ["metric", "imperial"],
}
TOKEN_SETTING = {
    "key": "forecast_api_token",
    "type": "secret",
    "label": "Forecast API token",
    "description": "Token for the forecast provider.",
    "required": False,
}
WEATHER_LIMITS = {
    "memory_mb": 256,
    "db_connections": 5,
    "statement_timeout_seconds": 10,
    "requests_per_minute": 120,
    "cpu_priority": "normal",
}


def sample_manifest(**changes) -> dict:
    """A copy of the Weather sample manifest with top-level `changes` applied."""
    manifest = copy.deepcopy(SAMPLE_MANIFEST)
    manifest.update(changes)
    return manifest


def backend_manifest(**changes) -> dict:
    """The Weather sample with a backend: a public ping path, two settings and limits."""
    return sample_manifest(
        **{
            "version": "0.2.0",
            "backend": dict(BACKEND),
            "public_paths": [dict(PING_PATH)],
            "settings": [dict(UNITS_SETTING), dict(TOKEN_SETTING)],
            "limits": dict(WEATHER_LIMITS),
            **changes,
        }
    )


def sample_files(manifest: dict | None = None) -> dict[str, bytes]:
    """The files of a frontend-only package for `manifest`, without CONTENTS.json."""
    manifest = manifest or sample_manifest()
    files = {
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        manifest.get("icon", "icon.svg"): ICON_SVG,
        "spa/index.html": INDEX_HTML,
        "spa/assets/app.js": APP_JS,
    }
    if "backend" in manifest:
        files.update(BACKEND_FILES)
    return files


def contents_for(files: dict[str, bytes], plugin_id: str = "weather", version: str = "0.1.0") -> bytes:
    return build_contents(
        plugin_id,
        version,
        [
            PackageFile(path=path, size=len(data), sha256=hashlib.sha256(data).hexdigest())
            for path, data in files.items()
        ],
    )


def build_package(
    files: dict[str, bytes] | None = None,
    *,
    manifest: dict | None = None,
    signed_with: SecretKey | None = None,
    contents: bytes | None = None,
    signature: str | None = None,
    unlisted: dict[str, bytes] | None = None,
    raw_entries: list[tuple[zipfile.ZipInfo, bytes]] | None = None,
) -> bytes:
    """Return a package's bytes.

    `files` default to the sample files of `manifest`; CONTENTS.json is computed from them
    unless `contents` overrides it. `unlisted` files and `raw_entries` are added without
    being listed. `signed_with` signs CONTENTS.json; `signature` puts any text in its place.
    """
    manifest = manifest or sample_manifest()
    files = sample_files(manifest) if files is None else files
    if contents is None:
        contents = contents_for(files, manifest.get("id", "weather"), manifest.get("version", "0.1.0"))
    if signed_with is not None:
        signature = sign_package(contents, manifest["id"], manifest["version"], signed_with)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            archive.writestr(path, data)
        archive.writestr("CONTENTS.json", contents)
        if signature is not None:
            archive.writestr("CONTENTS.json.minisig", signature)
        for path, data in (unlisted or {}).items():
            archive.writestr(path, data)
        for info, data in raw_entries or []:
            archive.writestr(info, data)
    return buffer.getvalue()


def set_entry_flag(data: bytes, name: str, flag: int) -> bytes:
    """Set a general-purpose flag bit of one entry in the central directory.

    zipfile clears these flags when it writes, so an "encrypted" entry has to be made by hand.
    """
    patched = bytearray(data)
    position = patched.find(b"PK\x01\x02")
    while position != -1:
        name_length = int.from_bytes(patched[position + 28 : position + 30], "little")
        if bytes(patched[position + 46 : position + 46 + name_length]) == name.encode("utf-8"):
            flags = int.from_bytes(patched[position + 8 : position + 10], "little") | flag
            patched[position + 8 : position + 10] = flags.to_bytes(2, "little")
            return bytes(patched)
        position = patched.find(b"PK\x01\x02", position + 4)
    raise ValueError(f"{name} is not in the archive")
