from conftest import load_tool, seed

tool = load_tool("s3_file_count_lines_tool")


def test_count_lines_basic(patched_storage, fake_client):
    text = "one two\nthree\n"
    seed(fake_client, "a.txt", text)

    result = tool.main(file_path="a.txt")

    parts = result.split()
    assert parts[0] == "2"
    assert parts[1] == "3"
    assert parts[2] == str(len(text.encode("utf-8")))
    assert parts[3] == "a.txt"


def test_count_lines_file_not_found(patched_storage, fake_client):
    result = tool.main(file_path="missing.txt")

    assert "not found" in result.lower()


def test_count_lines_unterminated_file_counts_final_fragment(
    patched_storage, fake_client
):
    # Regression: content.count("\n") under-counts a file that doesn't end
    # in a newline — "a\nb" has 1 "\n" but 2 logical lines ("a", "b"); the
    # unterminated final fragment must still count as a line.
    seed(fake_client, "a.txt", "a\nb")

    result = tool.main(file_path="a.txt")

    parts = result.split()
    assert parts[0] == "2"


def test_count_lines_trailing_newline_file(patched_storage, fake_client):
    # "a\nb\n" is still 2 lines, not 3 — no phantom empty trailing line.
    seed(fake_client, "a.txt", "a\nb\n")

    result = tool.main(file_path="a.txt")

    parts = result.split()
    assert parts[0] == "2"


def test_count_lines_empty_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "")

    result = tool.main(file_path="a.txt")

    parts = result.split()
    assert parts[0] == "0"


def test_count_lines_unicode_content(patched_storage, fake_client):
    seed(fake_client, "a.txt", "héllo\nwörld\n日本語")

    result = tool.main(file_path="a.txt")

    parts = result.split()
    assert parts[0] == "3"


def test_count_lines_refuses_oversized_file(patched_storage, fake_client, monkeypatch):
    import sys

    storage_module = sys.modules["epicstaff_storage.storage"]
    monkeypatch.setattr(storage_module, "MAX_LINE_READ_BYTES", 5)
    seed(fake_client, "big.txt", "0123456789")

    result = tool.main(file_path="big.txt")

    assert "MB read limit" in result
