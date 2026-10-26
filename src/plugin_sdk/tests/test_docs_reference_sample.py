import fnmatch
import importlib
import json
import re

import pytest

from conftest import REPO_ROOT
from epicstaff_plugin.contracts.hook_api import HOOK_PATHS

DOCS = REPO_ROOT / "docs" / "plugins"
TUTORIAL = DOCS / "tutorial" / "build-your-first-plugin.md"
DOC_PAGES = sorted(DOCS.rglob("*.md"))
SAMPLE = REPO_ROOT / "plugin-samples" / "weather"
SAMPLE_README = SAMPLE / "README.md"
SAMPLE_MANIFEST = SAMPLE / "manifest.json"
SAMPLE_PATH = re.compile(r"`(plugin-samples/weather[^`\s]*)`")
# The sample README names the sample's own files relative to the sample.
SAMPLE_RELATIVE_PATH = re.compile(r"`((?:backend|database|spa)/[^`\s]*|manifest\.json|icon\.svg)`")
# What the docs tell an author to create or build, which no checkout has.
AUTHOR_MADE_NAMES = (".venv", "dist", "node_modules", "*-development-runtime.json")
ROUTE = re.compile(r"^\| `(GET|POST|PUT|PATCH|DELETE) (/api/[^` ]+)`", re.MULTILINE)
JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.DOTALL)
NPM_SCRIPT = re.compile(r"npm --prefix (?:<SRC>/)?([\w./-]+) (?:run ([\w:.-]+)|(test)\b)")
MAKE_TEST_FILES = re.compile(r"make (?:-C \S+ )?([\w-]+)-tests ARGS=\"([^\"]*)\"")
TEST_FILE = re.compile(r"\btests/[\w/.-]+\.py")
# `make <service>-tests` runs in `src/<service>`; django_app's target is named `django-tests`.
TEST_SERVICE_DIRECTORIES = {"django": "django_app"}


def is_author_made(path: str) -> bool:
    return any(
        fnmatch.fnmatch(part, name) for part in path.split("/") for name in AUTHOR_MADE_NAMES
    )


def page_id(page):
    return str(page.relative_to(REPO_ROOT))


@pytest.mark.parametrize("page", [*DOC_PAGES, SAMPLE_README], ids=page_id)
def test_every_sample_file_a_page_names_exists(page):
    named = SAMPLE_PATH.findall(page.read_text())

    missing = [path for path in named if not is_author_made(path) and not (REPO_ROOT / path).exists()]

    assert missing == []


def test_every_file_the_sample_readme_names_exists():
    named = SAMPLE_RELATIVE_PATH.findall(SAMPLE_README.read_text())

    missing = [path for path in named if not is_author_made(path) and not (SAMPLE / path).exists()]

    assert named
    assert missing == []


@pytest.mark.parametrize("page", [*DOC_PAGES, SAMPLE_README], ids=page_id)
def test_every_npm_script_a_page_runs_exists(page):
    missing = []
    for directory, script, test in NPM_SCRIPT.findall(page.read_text()):
        package = REPO_ROOT / directory / "package.json"
        name = script or test
        if not package.is_file():
            missing.append(f"{directory}: no package.json")
        elif name not in json.loads(package.read_text()).get("scripts", {}):
            missing.append(f"{directory}: no script {name!r}")

    assert missing == []


@pytest.mark.parametrize("page", [*DOC_PAGES, SAMPLE_README], ids=page_id)
def test_every_test_file_a_page_runs_exists(page):
    missing = []
    for target, arguments in MAKE_TEST_FILES.findall(page.read_text()):
        service = REPO_ROOT / "src" / TEST_SERVICE_DIRECTORIES.get(target, target)
        missing += [
            f"make {target}-tests: {path}"
            for path in TEST_FILE.findall(arguments)
            if not (service / path).is_file()
        ]

    assert missing == []


def test_the_command_checks_read_the_forms_the_docs_use():
    text = (
        'npm --prefix plugin-samples/weather/spa run dev\n'
        'npm --prefix plugin-sdk test\n'
        'make plugin_sdk-tests ARGS="-m postgres tests/test_weather_sample_database.py"\n'
        'make -C <SRC> django-tests ARGS="tests/plugins_tests/test_error_codes_doc.py -q"\n'
    )

    assert NPM_SCRIPT.findall(text) == [
        ("plugin-samples/weather/spa", "dev", ""),
        ("plugin-sdk", "", "test"),
    ]
    assert MAKE_TEST_FILES.findall(text) == [
        ("plugin_sdk", "-m postgres tests/test_weather_sample_database.py"),
        ("django", "tests/plugins_tests/test_error_codes_doc.py -q"),
    ]
    assert is_author_made("plugin-samples/weather/.venv")
    assert is_author_made("plugin-samples/weather/backend/weather-development-runtime.json")
    assert not is_author_made("plugin-samples/weather/backend/src")


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


def test_part_two_names_the_retention_files():
    named = set(SAMPLE_PATH.findall(TUTORIAL.read_text()))

    assert {
        "plugin-samples/weather/database/migrations/002_retention.sql",
        "plugin-samples/weather/backend/src/weather_plugin/retention.py",
    } <= named


def test_part_four_and_the_hook_guide_name_the_files_of_the_organization_removed_hook():
    files = {
        "plugin-samples/weather/manifest.json",
        "plugin-samples/weather/backend/src/weather_plugin/app.py",
        "plugin-samples/weather/backend/src/weather_plugin/organization_data.py",
    }
    part_four = TUTORIAL.read_text().split("## Part 4:", 1)[1]

    assert files <= set(SAMPLE_PATH.findall(part_four))
    assert files - {"plugin-samples/weather/manifest.json"} <= set(
        SAMPLE_PATH.findall((DOCS / "how-to" / "org-removed-hook.md").read_text())
    )


def test_part_five_and_the_upgrade_hook_guide_name_the_files_of_the_new_version():
    part_five = TUTORIAL.read_text().split("## Part 5:", 1)[1]
    guide = (DOCS / "how-to" / "upgrade-hook.md").read_text()

    assert {
        "plugin-samples/weather/manifest.json",
        "plugin-samples/weather/database/migrations/003_place_conditions.sql",
        "plugin-samples/weather/backend/src/weather_plugin/current_conditions.py",
        "plugin-samples/weather/backend/src/weather_plugin/places.py",
        "plugin-samples/weather/backend/src/weather_plugin/organization_data.py",
        "plugin-samples/weather/backend/src/weather_plugin/upgrade_hook.py",
        "plugin-samples/weather/backend/src/weather_plugin/forecast_flow.py",
    } <= set(SAMPLE_PATH.findall(part_five))
    assert {
        "plugin-samples/weather/backend/src/weather_plugin/upgrade_hook.py",
        "plugin-samples/weather/backend/src/weather_plugin/app.py",
        "plugin-samples/weather/backend/src/weather_plugin/forecast_flow.py",
    } <= set(SAMPLE_PATH.findall(guide))


@pytest.mark.parametrize("page", [TUTORIAL, DOCS / "how-to" / "upgrade-hook.md"], ids=lambda page: page.name)
def test_the_upgrade_hook_a_page_quotes_is_the_samples(page):
    sample = (REPO_ROOT / "plugin-samples" / "weather" / "backend" / "src" / "weather_plugin" / "upgrade_hook.py").read_text()
    (quoted,) = re.findall(r"```python\n(@hook_registry\.on_upgrade\n.*?)\n```", page.read_text(), re.DOTALL)

    assert quoted in sample


def test_the_sql_the_tutorial_quotes_is_in_the_samples_migrations():
    migrations = [path.read_text() for path in sorted((REPO_ROOT / "plugin-samples" / "weather" / "database" / "migrations").glob("*.sql"))]
    quoted = re.findall(r"```sql\n(.*?)\n```", TUTORIAL.read_text(), re.DOTALL)

    assert len(quoted) >= 3
    assert [block for block in quoted if not any(block in migration for migration in migrations)] == []


def test_the_organization_removed_code_the_hook_guide_quotes_is_the_samples():
    sample = (REPO_ROOT / "plugin-samples" / "weather" / "backend" / "src" / "weather_plugin" / "organization_data.py").read_text()
    guide = (DOCS / "how-to" / "org-removed-hook.md").read_text()
    (statements,) = re.findall(r"(DELETE_ORGANIZATION_ROWS = \(.*?\n\))", guide, re.DOTALL)

    assert statements in sample


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
