from conftest import load_tool, seed

tool = load_tool("s3_file_move_tool")


def test_move_success(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(from_path="a.txt", to_path="b.txt")

    assert "Moved" in result
    assert fake_client.objects["b.txt"]["Body"] == b"hello"
    assert "a.txt" not in fake_client.objects


def test_move_source_not_found(patched_storage, fake_client):
    result = tool.main(from_path="missing.txt", to_path="b.txt")

    assert "not found" in result.lower()
