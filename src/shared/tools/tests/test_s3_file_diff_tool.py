from conftest import load_tool, seed

tool = load_tool("s3_file_diff_tool")


def test_diff_identical_files(patched_storage, fake_client):
    seed(fake_client, "a.txt", "same content\n")
    seed(fake_client, "b.txt", "same content\n")

    result = tool.main(file_path_a="a.txt", file_path_b="b.txt")

    assert "identical" in result


def test_diff_different_files(patched_storage, fake_client):
    seed(fake_client, "a.txt", "line1\nline2\n")
    seed(fake_client, "b.txt", "line1\nchanged\n")

    result = tool.main(file_path_a="a.txt", file_path_b="b.txt")

    assert "-line2" in result
    assert "+changed" in result


def test_diff_missing_file_a(patched_storage, fake_client):
    seed(fake_client, "b.txt", "content")

    result = tool.main(file_path_a="missing.txt", file_path_b="b.txt")

    assert "not found" in result.lower()
    assert "missing.txt" in result


def test_diff_missing_file_b(patched_storage, fake_client):
    seed(fake_client, "a.txt", "content")

    result = tool.main(file_path_a="a.txt", file_path_b="missing.txt")

    assert "not found" in result.lower()
    assert "missing.txt" in result


def test_diff_truncates_large_output(patched_storage, fake_client, monkeypatch):
    monkeypatch.setattr(tool, "_MAX_OUTPUT_CHARS", 50)
    content_a = "\n".join(f"line {i}" for i in range(50))
    content_b = "\n".join(f"line {i} changed" for i in range(50))
    seed(fake_client, "a.txt", content_a)
    seed(fake_client, "b.txt", content_b)

    result = tool.main(file_path_a="a.txt", file_path_b="b.txt")

    assert "truncated" in result
