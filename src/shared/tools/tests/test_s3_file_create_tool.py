from conftest import load_tool, seed

tool = load_tool("s3_file_create_tool")


def test_create_new_file(patched_storage, fake_client):
    result = tool.main(file_path="a.txt", content="hello")

    assert "created" in result.lower()
    assert fake_client.objects["a.txt"]["Body"] == b"hello"


def test_create_fails_if_exists_by_default(patched_storage, fake_client):
    seed(fake_client, "a.txt", "existing")

    result = tool.main(file_path="a.txt", content="new")

    assert "already exists" in result
    assert fake_client.objects["a.txt"]["Body"] == b"existing"


def test_create_overwrites_when_fail_if_exists_false(patched_storage, fake_client):
    seed(fake_client, "a.txt", "existing")

    result = tool.main(file_path="a.txt", content="new", fail_if_exists=False)

    assert "created" in result.lower()
    assert fake_client.objects["a.txt"]["Body"] == b"new"


def test_create_default_empty_content(patched_storage, fake_client):
    tool.main(file_path="a.txt")

    assert fake_client.objects["a.txt"]["Body"] == b""
