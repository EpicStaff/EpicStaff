from datetime import datetime, timedelta, timezone

from conftest import load_tool, seed

tool = load_tool("s3_glob_tool")


def test_glob_matches_pattern(patched_storage, fake_client):
    seed(fake_client, "dir/a.py", "x")
    seed(fake_client, "dir/b.txt", "y")

    result = tool.main(pattern="*.py", path="dir")

    assert "dir/a.py" in result
    assert "dir/b.txt" not in result


def test_glob_double_star_crosses_directories(patched_storage, fake_client):
    seed(fake_client, "src/sub/deep/file.py", "x")

    result = tool.main(pattern="src/**/*.py")

    assert "src/sub/deep/file.py" in result


def test_glob_no_match(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")

    result = tool.main(pattern="*.py", path="dir")

    assert "No files matching pattern" in result


def test_glob_sorted_newest_first(patched_storage, fake_client):
    seed(fake_client, "a.py", "x")
    seed(fake_client, "b.py", "y")

    now = datetime.now(timezone.utc)
    fake_client.objects["a.py"]["LastModified"] = now - timedelta(hours=1)
    fake_client.objects["b.py"]["LastModified"] = now

    result = tool.main(pattern="*.py")

    assert result.index("b.py") < result.index("a.py")


def test_glob_caps_results(patched_storage, fake_client, monkeypatch):
    monkeypatch.setattr(tool, "_MAX_RESULTS", 2)
    for i in range(5):
        seed(fake_client, f"file{i}.py", "x")

    result = tool.main(pattern="*.py")

    assert "showing 2 of 5 matches" in result
