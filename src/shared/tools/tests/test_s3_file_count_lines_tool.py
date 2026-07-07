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


def test_count_lines_refuses_oversized_file(patched_storage, fake_client, monkeypatch):
    import sys

    storage_module = sys.modules["epicstaff_storage.storage"]
    monkeypatch.setattr(storage_module, "MAX_LINE_READ_BYTES", 5)
    seed(fake_client, "big.txt", "0123456789")

    result = tool.main(file_path="big.txt")

    assert "MB read limit" in result
