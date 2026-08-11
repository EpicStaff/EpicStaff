from conftest import load_tool, seed

tool = load_tool("s3_file_edit_tool")


def test_edit_replaces_unique_match(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello world")

    result = tool.main(file_path="a.txt", old_string="world", new_string="there")

    assert "Replaced 1 occurrence" in result
    assert fake_client.objects["a.txt"]["Body"] == b"hello there"


def test_edit_file_not_found(patched_storage, fake_client):
    result = tool.main(file_path="missing.txt", old_string="x", new_string="y")

    assert "not found" in result.lower()


def test_edit_old_string_not_found(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello world")

    result = tool.main(file_path="a.txt", old_string="nope", new_string="y")

    assert "not found" in result.lower()
    assert fake_client.objects["a.txt"]["Body"] == b"hello world"


def test_edit_multiple_matches_without_replace_all(patched_storage, fake_client):
    seed(fake_client, "a.txt", "foo foo foo")

    result = tool.main(file_path="a.txt", old_string="foo", new_string="bar")

    assert "found 3 times" in result
    assert fake_client.objects["a.txt"]["Body"] == b"foo foo foo"


def test_edit_replace_all(patched_storage, fake_client):
    seed(fake_client, "a.txt", "foo foo foo")

    result = tool.main(
        file_path="a.txt", old_string="foo", new_string="bar", replace_all=True
    )

    assert "Replaced 3 occurrence" in result
    assert fake_client.objects["a.txt"]["Body"] == b"bar bar bar"


def test_edit_identical_strings_rejected(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(file_path="a.txt", old_string="hello", new_string="hello")

    assert "identical" in result
