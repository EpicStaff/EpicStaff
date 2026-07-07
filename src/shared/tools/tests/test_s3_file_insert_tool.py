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


def test_insert_append_preserves_trailing_newline(patched_storage, fake_client):
    # "a\nb\n" is a 2-line file (wc-style: a trailing "\n" terminates the
    # last line, it doesn't start a phantom 3rd line). Line 3 is the
    # correct append position, and the file's own trailing newline must be
    # preserved round-trip.
    seed(fake_client, "a.txt", "a\nb\n")

    result = tool.main(file_path="a.txt", line_number=3, content="c")

    assert "Content inserted" in result
    assert fake_client.objects["a.txt"]["Body"] == b"a\nb\nc\n"


def test_insert_prepend_preserves_trailing_newline(patched_storage, fake_client):
    seed(fake_client, "a.txt", "a\nb\n")

    result = tool.main(file_path="a.txt", line_number=1, content="x")

    assert "Content inserted" in result
    assert fake_client.objects["a.txt"]["Body"] == b"x\na\nb\n"


def test_insert_middle_preserves_trailing_newline(patched_storage, fake_client):
    seed(fake_client, "a.txt", "a\nb\n")

    result = tool.main(file_path="a.txt", line_number=2, content="x")

    assert "Content inserted" in result
    assert fake_client.objects["a.txt"]["Body"] == b"a\nx\nb\n"


def test_insert_out_of_range_on_trailing_newline_file_reports_true_line_count(
    patched_storage, fake_client
):
    # Regression: "a\nb\n" must be reported/validated as 2 lines, not 3
    # (len("a\nb\n".split("\n"))). Before the fix, line_number=4 was wrongly
    # accepted as a valid append position and corrupted the file with a
    # spurious blank line.
    seed(fake_client, "a.txt", "a\nb\n")

    result = tool.main(file_path="a.txt", line_number=4, content="x")

    assert "out of range" in result
    assert "2 lines" in result
    assert "between 1 and 3" in result
    assert fake_client.objects["a.txt"]["Body"] == b"a\nb\n"


def test_insert_into_empty_existing_file(patched_storage, fake_client):
    # An existing-but-empty file has 0 lines; line 1 is the only valid
    # (append) position, distinct from the file-not-found path.
    seed(fake_client, "a.txt", "")

    result = tool.main(file_path="a.txt", line_number=1, content="hello")

    assert "Content inserted" in result
    assert fake_client.objects["a.txt"]["Body"] == b"hello\n"


def test_insert_into_empty_existing_file_out_of_range(patched_storage, fake_client):
    seed(fake_client, "a.txt", "")

    result = tool.main(file_path="a.txt", line_number=2, content="hello")

    assert "out of range" in result
    assert "0 lines" in result


def test_insert_unicode_content_round_trip(patched_storage, fake_client):
    seed(fake_client, "a.txt", "héllo\nwörld\n")

    result = tool.main(file_path="a.txt", line_number=3, content="日本語 🎉")

    assert "Content inserted" in result
    assert fake_client.objects["a.txt"]["Body"] == "héllo\nwörld\n日本語 🎉\n".encode(
        "utf-8"
    )
