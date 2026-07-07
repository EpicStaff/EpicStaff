from conftest import load_tool, seed

tool = load_tool("s3_file_insert_tool")


def test_insert_at_top(patched_storage, fake_client):
    seed(fake_client, "a.txt", "b\nc")

    result = tool.main(file_path="a.txt", line_number=1, content="a")

    assert "Content inserted" in result
    assert fake_client.objects["a.txt"]["Body"] == b"a\nb\nc"


def test_insert_creates_missing_file(patched_storage, fake_client):
    tool.main(file_path="a.txt", line_number=1, content="hello")

    # Inserting into a nonexistent (empty) file starts from a single empty
    # line, so the result has a trailing newline after "hello".
    assert fake_client.objects["a.txt"]["Body"] == b"hello\n"


def test_insert_at_exact_end_boundary(patched_storage, fake_client):
    seed(fake_client, "a.txt", "a\nb")

    result = tool.main(file_path="a.txt", line_number=3, content="c")

    assert "Content inserted" in result
    assert fake_client.objects["a.txt"]["Body"] == b"a\nb\nc"


def test_insert_out_of_range_reports_line_count(patched_storage, fake_client):
    seed(fake_client, "a.txt", "a\nb")

    result = tool.main(file_path="a.txt", line_number=10, content="x")

    assert "out of range" in result
    assert "2 lines" in result
    assert fake_client.objects["a.txt"]["Body"] == b"a\nb"


def test_insert_negative_line_number(patched_storage, fake_client):
    result = tool.main(file_path="a.txt", line_number=0, content="x")

    assert "must be >= 1" in result
