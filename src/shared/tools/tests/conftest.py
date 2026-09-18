"""Shared test infrastructure for the built-in python-code tools under
`src/shared/tools/`.

Each tool directory ships a standalone `main.py` (no package imports between
tools — only `main.py`'s source text is uploaded and executed by the
sandbox), so tests import each `main.py` directly by file path via
`importlib`, exactly as the sandbox loads it (as a bare module, not part of
the `shared.tools` package).

This also covers the ``src/shared/tools/s3_*`` sandbox tools specifically:
those tests reuse the in-memory S3 fake from
``src/shared/epicstaff_storage/tests/fakes.py`` so no real network/boto3
calls happen. Every s3 tool does a lazy ``from epicstaff_storage import
EpicStaffStorage`` *inside* ``main()``, creating a fresh instance per call.
That means the instance-level monkeypatch pattern used by
``epicstaff_storage``'s own tests (patch ``instance._client``) can't reach
it — instead ``patched_storage`` below patches
``EpicStaffStorage._get_client`` at the class level, so any instance
constructed during a tool call picks up the fake client.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from urllib.parse import urljoin

import pytest
import requests

TOOLS_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = TOOLS_ROOT
SHARED_DIR = TOOLS_DIR.parent
STORAGE_TESTS_DIR = SHARED_DIR / "epicstaff_storage" / "tests"

for _path in (str(SHARED_DIR), str(STORAGE_TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fakes import FakeS3Client  # noqa: E402
from epicstaff_storage import EpicStaffStorage, clear_mutations  # noqa: E402

# NOTE: `epicstaff_storage/__init__.py` ends with `storage = EpicStaffStorage()`,
# which rebinds the *attribute* `epicstaff_storage.storage` to that instance,
# shadowing the submodule of the same name. Both `from epicstaff_storage import
# storage` and `import epicstaff_storage.storage as x` resolve via that
# (now-shadowed) attribute and would bind to the instance, not the module —
# go through `sys.modules` to reach the actual submodule object, where the
# module-level `__cache` / `_mutations` state actually lives.
import epicstaff_storage  # noqa: E402,F401 (ensures the package — and its .storage submodule — are imported)

storage_module = sys.modules["epicstaff_storage.storage"]

TEST_BUCKET = "test-bucket"


@pytest.fixture(autouse=True)
def _reset_module_state():
    storage_module.__cache.clear()
    clear_mutations()
    yield
    storage_module.__cache.clear()
    clear_mutations()


@pytest.fixture
def fake_client() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def patched_storage(
    monkeypatch: pytest.MonkeyPatch, fake_client: FakeS3Client
) -> FakeS3Client:
    def _get_client(self: EpicStaffStorage):
        self._client = fake_client
        self._bucket = TEST_BUCKET
        return fake_client

    monkeypatch.setattr(EpicStaffStorage, "_get_client", _get_client)
    return fake_client


@pytest.fixture
def sandbox_dir(tmp_path, monkeypatch):
    """Point CONTAINER_SAVEFILES_PATH at an isolated temp directory, mirroring
    the sandbox's savefiles/ cwd convention used by RouteTool in each main.py."""
    monkeypatch.setenv("CONTAINER_SAVEFILES_PATH", str(tmp_path))
    return tmp_path


def load_tool_main(tool_dir_name: str) -> ModuleType:
    """Import a tool's main.py as an isolated module, e.g. load_tool_main("read_file_tool")."""
    main_path = TOOLS_ROOT / tool_dir_name / "main.py"
    module_name = f"_shared_tool_{tool_dir_name}_main"

    spec = importlib.util.spec_from_file_location(module_name, main_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_tool(tool_dir_name: str) -> ModuleType:
    """Import a tool's ``main.py`` by path (tool dirs have no package init)."""
    tool_path = TOOLS_DIR / tool_dir_name / "main.py"
    spec = importlib.util.spec_from_file_location(f"_tool_{tool_dir_name}", tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed(fake_client: FakeS3Client, path: str, body: str) -> None:
    fake_client.put_object(Bucket=TEST_BUCKET, Key=path, Body=body.encode("utf-8"))


class FakeResponse:
    """Stand-in for `requests.Response` used by the `_guarded_get` tests
    below -- carries just the attributes the 4 scraping tools read off a
    real response (`status_code`, `headers`, `text`/`content`,
    `apparent_encoding`) plus a `raise_for_status()` that mirrors
    `requests`'s behavior for 4xx/5xx."""

    def __init__(self, status_code: int = 200, headers: dict | None = None, text: str = ""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.content = text.encode("utf-8")
        self.apparent_encoding = "utf-8"
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def make_fake_requests_get(responses_by_url: dict[str, FakeResponse]):
    """Build a `requests.get` stand-in that mimics real `requests` redirect
    semantics precisely, keyed off the `allow_redirects` kwarg: with
    `allow_redirects=True` (the library default) it silently chases the 3xx
    chain in `responses_by_url` itself and returns only the final response,
    the same way the real library does -- so a tool that forgets to pass
    `allow_redirects=False` would (like the pre-fix bug) never see the
    intermediate redirect at all. With `allow_redirects=False` it returns
    the response for the requested URL as-is, letting the caller walk the
    chain (and re-run the SSRF guard on each hop) itself.
    """

    def _fake_get(url, headers=None, timeout=None, allow_redirects=True):
        response = responses_by_url[url]
        if not allow_redirects:
            return response

        seen_urls = set()
        while 300 <= response.status_code < 400:
            if url in seen_urls:
                raise AssertionError(f"redirect loop in test fixture at {url}")
            seen_urls.add(url)
            location = response.headers["location"]
            url = urljoin(url, location)
            response = responses_by_url[url]
        return response

    return _fake_get
