from conftest import load_tool, seed

tool = load_tool("s3_file_write_tool")


def test_write_creates_new_file(patched_storage, fake_client):
    result = tool.main(file_path="a.txt", content="hello")

    assert "Wrote" in result
    assert fake_client.objects["a.txt"]["Body"] == b"hello"


def test_write_overwrites_existing_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "old content")

    result = tool.main(file_path="a.txt", content="new content")

    assert "Wrote" in result
    assert fake_client.objects["a.txt"]["Body"] == b"new content"
