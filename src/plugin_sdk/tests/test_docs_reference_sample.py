import importlib
import json
import re

import pytest

from conftest import REPO_ROOT
from epicstaff_plugin.contracts.hook_api import HOOK_PATHS

DOCS = REPO_ROOT / "docs" / "plugins"
TUTORIAL = DOCS / "tutorial" / "build-your-first-plugin.md"
PAGES_NAMING_THE_SAMPLE = [
    TUTORIAL,
    DOCS / "how-to" / "install-hook.md",
    DOCS / "how-to" / "call-epicstaff-from-the-backend.md",
    DOCS / "how-to" / "database-migrations.md",
    DOCS / "how-to" / "external-callbacks.md",
    DOCS / "reference" / "python-sdk.md",
]
SAMPLE_MANIFEST = REPO_ROOT / "plugin-samples" / "weather" / "manifest.json"
SAMPLE_PATH = re.compile(r"`(plugin-samples/weather[^`\s]*)`")
ROUTE = re.compile(r"^\| `(GET|POST|PUT|PATCH|DELETE) (/api/[^` ]+)`", re.MULTILINE)
JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


@pytest.mark.parametrize("page", PAGES_NAMING_THE_SAMPLE, ids=lambda page: page.name)
def test_every_sample_file_a_page_names_exists(page):
    named = SAMPLE_PATH.findall(page.read_text())

    missing = [path for path in named if not (REPO_ROOT / path).exists()]

    assert missing == []


def test_the_tutorial_names_the_sample_files_it_explains():
    named = set(SAMPLE_PATH.findall(TUTORIAL.read_text()))

    assert {
        "plugin-samples/weather/manifest.json",
        "plugin-samples/weather/backend/src/weather_plugin/app.py",
        "plugin-samples/weather/backend/src/weather_plugin/install_hook.py",
    } <= named


def test_parts_two_and_three_name_the_files_they_explain():
    named = set(SAMPLE_PATH.findall(TUTORIAL.read_text()))

    assert {
        "plugin-samples/weather/database/migrations/001_weather.sql",
        "plugin-samples/weather/backend/src/weather_plugin/database.py",
        "plugin-samples/weather/backend/src/weather_plugin/places.py",
        "plugin-samples/weather/backend/src/weather_plugin/place_search.py",
    } <= named


def test_the_sql_the_tutorial_quotes_is_in_the_samples_migration():
    migration = (REPO_ROOT / "plugin-samples" / "weather" / "database" / "migrations" / "001_weather.sql").read_text()
    quoted = re.findall(r"```sql\n(.*?)\n```", TUTORIAL.read_text(), re.DOTALL)

    assert quoted
    assert [block for block in quoted if block not in migration] == []


def test_the_manifest_the_tutorial_shows_is_the_samples():
    shown = [json.loads(block) for block in JSON_BLOCK.findall(TUTORIAL.read_text()) if '"manifest_version"' in block]

    assert shown == [json.loads(SAMPLE_MANIFEST.read_text())]


def test_every_route_the_tutorial_names_is_served_by_the_sample(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "plugin-samples" / "weather" / "backend" / "src"))
    app = importlib.import_module("weather_plugin.app").app
    served = {(method, route.path) for route in app.routes for method in getattr(route, "methods", ())}

    named = ROUTE.findall(TUTORIAL.read_text())

    assert named
    assert [route for route in named if route not in served] == []


def test_the_hook_api_page_lists_every_kind_with_its_path():
    rows = re.findall(r"^\| `(\w+)` \| `(/_epicstaff/hooks/[\w-]+)` \|", (DOCS / "reference" / "hook-api.md").read_text(), re.MULTILINE)

    assert dict(rows) == dict(HOOK_PATHS)
