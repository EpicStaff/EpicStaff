from conftest import load_tool, seed

tool = load_tool("s3_file_line_read_tool")


def test_read_default_offset_and_limit(patched_storage, fake_client):
    seed(fake_client, "notes.txt", "a\nb\nc")

    result = tool.main(file_path="notes.txt")

    assert result == "     1\ta\n     2\tb\n     3\tc"


def test_read_with_offset_and_limit(patched_storage, fake_client):
    seed(fake_client, "notes.txt", "a\nb\nc\nd")

    result = tool.main(file_path="notes.txt", offset=2, limit=2)

    assert result == "     2\tb\n     3\tc"


def test_read_file_not_found(patched_storage, fake_client):
    result = tool.main(file_path="missing.txt")

    assert "not found" in result.lower()


def test_read_offset_out_of_range(patched_storage, fake_client):
    seed(fake_client, "notes.txt", "a\nb")

    result = tool.main(file_path="notes.txt", offset=10)

    assert "out of range" in result


def test_read_invalid_offset(patched_storage, fake_client):
    result = tool.main(file_path="notes.txt", offset=0)

    assert "offset must be >= 1" in result


def test_read_invalid_limit(patched_storage, fake_client):
    result = tool.main(file_path="notes.txt", limit=0)

    assert "limit must be >= 1" in result


def test_read_trailing_newline_file_has_no_phantom_line(patched_storage, fake_client):
    # "a\nb\n" is a 2-line file; a naive content.split("\n") would produce
    # a phantom empty 3rd line.
    seed(fake_client, "notes.txt", "a\nb\n")

    result = tool.main(file_path="notes.txt")

    assert result == "     1\ta\n     2\tb"


def test_read_offset_out_of_range_on_trailing_newline_file(
    patched_storage, fake_client
):
    seed(fake_client, "notes.txt", "a\nb\n")

    result = tool.main(file_path="notes.txt", offset=3)

    assert "out of range" in result
    assert "2 lines" in result


def test_read_empty_file_offset_out_of_range(patched_storage, fake_client):
    seed(fake_client, "notes.txt", "")

    result = tool.main(file_path="notes.txt", offset=1)

    assert "out of range" in result
    assert "0 lines" in result


def test_read_unicode_content(patched_storage, fake_client):
    seed(fake_client, "notes.txt", "héllo\nwörld\n日本語\n")

    result = tool.main(file_path="notes.txt")

    assert result == "     1\théllo\n     2\twörld\n     3\t日本語"


def test_read_refuses_oversized_file(patched_storage, fake_client, monkeypatch):
    import sys

    storage_module = sys.modules["epicstaff_storage.storage"]
    monkeypatch.setattr(storage_module, "MAX_LINE_READ_BYTES", 5)
    seed(fake_client, "big.txt", "0123456789")

    result = tool.main(file_path="big.txt")

    assert "MB read limit" in result
