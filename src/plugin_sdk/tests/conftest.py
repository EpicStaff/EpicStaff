import copy
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MINISIGN_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "minisign"

ICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<circle cx="12" cy="12" r="5" fill="currentColor"/></svg>'
)

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


# The finished Weather plugin from the manifest reference: every section filled in.
FULL_MANIFEST = {
    **SAMPLE_MANIFEST,
    "version": "1.0.0",
    "backend": {"python": "3.13", "entrypoint": "weather_plugin.app:app"},
    "database": {},
    "access": [
        {
            "resource_type": "flows",
            "actions": ["read", "create", "update", "delete", "use"],
            "reason": "Creates the Weather forecast flow and runs it for you.",
        },
        {"resource_type": "files", "actions": ["read", "create"], "reason": "Stores forecast reports."},
    ],
    "user_permissions": [
        {
            "action": "read",
            "description": "Open Weather and see forecasts.",
            "defaults": {"org_admin": True, "member": True, "viewer": True},
        },
        {
            "action": "update",
            "description": "Add and remove saved places.",
            "defaults": {"org_admin": True, "member": True, "viewer": False},
        },
        {
            "action": "delete",
            "description": "Change the organization's Weather settings.",
            "defaults": {"org_admin": True, "member": False, "viewer": False},
        },
    ],
    "public_paths": [
        {"path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0}
    ],
    "outbound_hosts": [{"host": "geocoding-api.open-meteo.com", "reason": "City search."}],
    "settings": [
        {
            "key": "units",
            "type": "enum",
            "label": "Units",
            "description": "Units for every organization.",
            "required": True,
            "default": "metric",
            "values": ["metric", "imperial"],
        }
    ],
    "limits": {
        "memory_mb": 256,
        "db_connections": 5,
        "statement_timeout_seconds": 10,
        "requests_per_minute": 120,
        "cpu_priority": "normal",
    },
    "hooks": {"install": True, "upgrade": True, "org_removed": True, "timeouts_seconds": {"install": 300}},
}


@pytest.fixture
def full_manifest_document():
    """A fresh copy of the complete manifest example, safe to modify."""
    return copy.deepcopy(FULL_MANIFEST)


@pytest.fixture
def manifest_document():
    """A fresh copy of the Weather sample manifest, safe to modify."""
    return copy.deepcopy(SAMPLE_MANIFEST)


@pytest.fixture
def plugin_source(tmp_path):
    """A frontend-only plugin source directory and its built SPA, as (source, spa) paths."""
    source = tmp_path / "weather"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps(SAMPLE_MANIFEST, indent=2))
    (source / "icon.svg").write_bytes(ICON_SVG)
    spa = tmp_path / "dist"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<!doctype html><title>Weather</title><script src=app.js></script>")
    (spa / "assets" / "app.js").write_text("console.log('weather');\n")
    return source, spa
