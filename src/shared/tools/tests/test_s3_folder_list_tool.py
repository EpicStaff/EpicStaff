from conftest import load_tool, seed

tool = load_tool("s3_folder_list_tool")


def test_list_flat(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")
    seed(fake_client, "dir/sub/b.txt", "y")

    result = tool.main(path="dir")

    assert "a.txt" in result
    assert "sub/" in result
    assert "b.txt" not in result


def test_list_recursive(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")
    seed(fake_client, "dir/sub/b.txt", "y")

    result = tool.main(path="dir", recursive=True)

    assert "dir/a.txt" in result
    assert "dir/sub/b.txt" in result


def test_list_long_includes_size(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "hello")

    result = tool.main(path="dir", long=True)

    assert "5" in result


def test_list_empty_path_returns_message(patched_storage, fake_client):
    result = tool.main(path="nowhere")

    assert "No files or folders found" in result


def test_list_truncates_large_output(patched_storage, fake_client, monkeypatch):
    monkeypatch.setattr(tool, "_MAX_OUTPUT_CHARS", 50)
    for i in range(20):
        seed(fake_client, f"dir/file{i}.txt", "x")

    result = tool.main(path="dir", recursive=True)

    assert "narrow the path" in result
