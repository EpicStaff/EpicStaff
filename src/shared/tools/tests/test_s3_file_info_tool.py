from conftest import load_tool, seed

tool = load_tool("s3_file_info_tool")


def test_info_returns_metadata(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(file_path="a.txt")

    assert isinstance(result, dict)
    assert result["name"] == "a.txt"
    assert result["size"] == 5


def test_info_file_not_found(patched_storage, fake_client):
    result = tool.main(file_path="missing.txt")

    assert isinstance(result, str)
    assert "not found" in result.lower()
