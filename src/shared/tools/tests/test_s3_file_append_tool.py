from conftest import load_tool, seed

tool = load_tool("s3_file_append_tool")


def test_append_to_existing_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(file_path="a.txt", content=" world")

    assert "Appended" in result
    assert fake_client.objects["a.txt"]["Body"] == b"hello world"


def test_append_creates_missing_file(patched_storage, fake_client):
    tool.main(file_path="a.txt", content="hello")

    assert fake_client.objects["a.txt"]["Body"] == b"hello"
