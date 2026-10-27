"""The crewai tools that fetch a document take only an http(s) URL: a local path
or a file:// URL gets an error and no local file is opened."""

import builtins
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import FakeResponse, load_tool

IMAGE_URL = "https://example.com/picture.png"
SECRET = "SECRET-LOCAL-CONTENT"


@pytest.fixture
def opened_paths(monkeypatch) -> list[str]:
    paths: list[str] = []
    real_open = builtins.open

    def recording_open(file, *args, **kwargs):
        paths.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recording_open)
    return paths


@pytest.fixture
def vision_api_image_urls(monkeypatch) -> list[str]:
    """Replace the OpenAI client of every tool loaded after it; collects the image URLs sent."""
    sent: list[str] = []

    def create(model, messages, **kwargs):
        for message in messages:
            if isinstance(message["content"], list):
                sent.extend(part["image_url"]["url"] for part in message["content"] if part["type"] == "image_url")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="text from the image"))])

    def fake_openai(api_key):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    return sent


TOOL_CALLS = {
    "crewai_txt_search_tool_tool": lambda tool, source: tool.main(txt=source, search_query="needle"),
    "crewai_xml_search_tool": lambda tool, source: tool.main(search_query="needle", xml=source),
    "crewai_ocr_tool": lambda tool, source: tool.main(openai_api_key="test-key", image_path_url=source),
    "crewai_vision_tool": lambda tool, source: tool.main(image_path_url=source, openai_api_key="test-key"),
    "crewai_github_search_tool": lambda tool, source: tool.main(search_query="needle", repo_path_or_url=source),
}


LOCAL_SOURCE_FORMS = {
    "plain-path": str,
    "file-url": lambda path: path.as_uri(),
    "http-url-without-host": lambda path: f"http://{path}",
}


@pytest.mark.parametrize("source_form", LOCAL_SOURCE_FORMS)
@pytest.mark.parametrize("tool_dir", TOOL_CALLS)
def test_local_source_is_refused_without_opening_it(
    tool_dir, source_form, tmp_path, opened_paths, vision_api_image_urls
):
    # A .png holding XML, so every tool's former local branch would accept and read it.
    local_file = tmp_path / "secret.png"
    local_file.write_text(f"<root><item>needle {SECRET}</item></root>\n")
    local_source = tmp_path if tool_dir == "crewai_github_search_tool" else local_file
    source = LOCAL_SOURCE_FORMS[source_form](local_source)
    tool = load_tool(tool_dir)

    result = TOOL_CALLS[tool_dir](tool, source)

    assert f"'{source}' is not an http(s) URL" in str(result)
    assert SECRET not in str(result)
    assert not [path for path in opened_paths if path.startswith(str(tmp_path))]
    assert vision_api_image_urls == []


class _FakeUrlopenResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _serve_txt(monkeypatch, url):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda requested: _FakeUrlopenResponse(b"first line\nneedle in a line\n") if requested == url else None,
    )


def _serve_xml(monkeypatch, url):
    monkeypatch.setattr(
        "requests.get",
        lambda requested, timeout: FakeResponse(text="<root><item>needle in xml</item></root>")
        if requested == url
        else FakeResponse(status_code=404),
    )


def _serve_git_repo(monkeypatch, url):
    def fake_run(command, **kwargs):
        assert url in command and not kwargs.get("shell")
        # git clone takes the target directory as its last argument.
        Path(command[-1], "README.md").write_text("intro\nneedle in the repo\n")

    monkeypatch.setattr(subprocess, "run", fake_run)


@pytest.mark.parametrize(
    "tool_dir, url, serve, expected",
    [
        ("crewai_txt_search_tool_tool", "https://example.com/notes.txt", _serve_txt, "needle in a line"),
        ("crewai_xml_search_tool", "http://example.com/data.xml", _serve_xml, "<item>needle in xml</item>"),
        ("crewai_ocr_tool", IMAGE_URL, None, "text from the image"),
        ("crewai_vision_tool", IMAGE_URL, None, "text from the image"),
        ("crewai_github_search_tool", "https://github.com/org/repo", _serve_git_repo, "needle in the repo"),
    ],
)
def test_url_source_is_fetched_and_searched(tool_dir, url, serve, expected, monkeypatch, vision_api_image_urls):
    if serve:
        serve(monkeypatch, url)
    tool = load_tool(tool_dir)

    result = TOOL_CALLS[tool_dir](tool, url)

    assert expected in result
    if url == IMAGE_URL:
        assert vision_api_image_urls == [IMAGE_URL]


@pytest.mark.parametrize(
    "clone_error, expected",
    [
        (FileNotFoundError(2, "No such file or directory", "git"), "could not run git"),
        (subprocess.CalledProcessError(128, "git", stderr=b"repository not found"), "repository not found"),
    ],
    ids=["git-missing", "clone-failed"],
)
def test_github_clone_failure_returns_error_and_removes_temp_dir(clone_error, expected, tmp_path, monkeypatch):
    def failing_run(command, **kwargs):
        raise clone_error

    monkeypatch.setattr(subprocess, "run", failing_run)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    tool = load_tool("crewai_github_search_tool")

    result = tool.main(search_query="needle", repo_path_or_url="https://github.com/org/repo")

    assert result.startswith("Error cloning repo") and expected in result
    assert list(tmp_path.iterdir()) == []
