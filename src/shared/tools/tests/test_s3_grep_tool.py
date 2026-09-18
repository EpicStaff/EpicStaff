from conftest import TEST_BUCKET, load_tool, seed

tool = load_tool("s3_grep_tool")


def test_grep_matches_lines_with_line_numbers(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello\nworld\nhello again")

    result = tool.main(pattern="hello")

    assert "a.txt:1: hello" in result
    assert "a.txt:3: hello again" in result
    assert "world" not in result


def test_grep_ignore_case(patched_storage, fake_client):
    seed(fake_client, "a.txt", "Hello World")

    result = tool.main(pattern="hello", ignore_case=True)

    assert "Hello World" in result


def test_grep_no_line_numbers(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello world")

    result = tool.main(pattern="hello", show_line_numbers=False)

    assert "a.txt: hello world" in result
    assert "a.txt:1:" not in result


def test_grep_files_with_matches(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")
    seed(fake_client, "b.txt", "nope")

    result = tool.main(pattern="hello", files_with_matches=True)

    assert result == "a.txt"


def test_grep_single_file_path(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "target line")
    seed(fake_client, "dir/b.txt", "target line")

    result = tool.main(pattern="target", path="dir/a.txt")

    assert "dir/a.txt" in result
    assert "dir/b.txt" not in result


def test_grep_non_recursive_skips_nested(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "target")
    seed(fake_client, "dir/sub/b.txt", "target")

    result = tool.main(pattern="target", path="dir", recursive=False)

    assert "dir/a.txt" in result
    assert "dir/sub/b.txt" not in result


def test_grep_no_matches(patched_storage, fake_client):
    seed(fake_client, "a.txt", "nothing here")

    result = tool.main(pattern="xyz")

    assert "No matches" in result


def test_grep_invalid_regex(patched_storage, fake_client):
    result = tool.main(pattern="[unclosed")

    assert "Invalid regex" in result


def test_grep_skips_binary_file(patched_storage, fake_client):
    fake_client.put_object(Bucket=TEST_BUCKET, Key="bin.dat", Body=b"\xff\xfe\x00\x01")
    seed(fake_client, "a.txt", "hello")

    result = tool.main(pattern="hello")

    assert "a.txt" in result
    assert "1 file(s) skipped (binary" in result


def test_grep_match_cap(patched_storage, fake_client, monkeypatch):
    monkeypatch.setattr(tool, "_MAX_MATCHES", 2)
    content = "\n".join("target" for _ in range(5))
    seed(fake_client, "a.txt", content)

    result = tool.main(pattern="target")

    assert "showing partial results" in result


def test_grep_char_cap(patched_storage, fake_client, monkeypatch):
    monkeypatch.setattr(tool, "_MAX_OUTPUT_CHARS", 20)
    content = "\n".join(f"target line number {i}" for i in range(5))
    seed(fake_client, "a.txt", content)

    result = tool.main(pattern="target")

    assert "showing partial results" in result
